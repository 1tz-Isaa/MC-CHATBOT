// Chat page logic. No libraries: just fetch() and the DOM.
//
// The server (web.py) answers POST /api/chat with one JSON object per line:
//   {"type": "status",  "text": "Searching school records…"}
//   {"type": "notice",  "text": "..."}          extra information to show
//   {"type": "token",   "text": "next words"}   a piece of the answer
//   {"type": "sources", "sources": [...]}       the records the answer used
//   {"type": "error",   "text": "..."}
//   {"type": "done"}

const chat = document.getElementById("chat");
const welcome = document.getElementById("welcome");
const messages = document.getElementById("messages");
const form = document.getElementById("composer");
const input = document.getElementById("question");
const sendButton = document.getElementById("send");

let controller = null; // set while an answer is streaming, so Stop can cancel it

// ---------- Small helpers ----------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function link(url, text) {
  const a = el("a", "", text);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

// ---------- Turning answer text into safe page elements ----------
//
// Answers are never inserted as HTML. Each piece becomes a text node or an
// element we create ourselves, so text from the model or from school records
// cannot inject markup into the page.

// Matches, in order: [label](https://link), a bare https://link, **bold**, [3]
const INLINE = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"\]]+)|\*\*([^*\n]+)\*\*|\[(\d+)\]/g;

function appendInline(parent, text, sources) {
  let position = 0;
  for (const match of text.matchAll(INLINE)) {
    parent.append(text.slice(position, match.index));
    position = match.index + match[0].length;
    const [whole, label, labelUrl, bareUrl, bold, citation] = match;
    if (labelUrl) {
      parent.append(link(labelUrl, label));
    } else if (bareUrl) {
      // Keep sentence punctuation out of the link.
      const url = bareUrl.replace(/[.,;:!?)]+$/, "");
      parent.append(link(url, url), bareUrl.slice(url.length));
    } else if (bold) {
      parent.append(el("strong", "", bold));
    } else {
      const source = sources.find((item) => item.number === Number(citation));
      if (source && source.url) {
        const a = link(source.url, citation);
        a.className = "cite";
        a.title = source.source;
        parent.append(a);
      } else if (source) {
        const chip = el("span", "cite", citation);
        chip.title = source.source;
        parent.append(chip);
      } else {
        parent.append(whole);
      }
    }
  }
  parent.append(text.slice(position));
}

function renderAnswer(container, text, sources) {
  container.replaceChildren();
  let list = null;
  let paragraph = null;
  for (const line of text.split("\n")) {
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) {
      if (!list) list = container.appendChild(el("ul"));
      appendInline(list.appendChild(el("li")), bullet[1], sources);
      paragraph = null;
    } else if (!line.trim()) {
      list = null;
      paragraph = null;
    } else {
      list = null;
      if (paragraph) paragraph.append(el("br"));
      else paragraph = container.appendChild(el("p"));
      appendInline(paragraph, line, sources);
    }
  }
}

function renderSources(container, sources) {
  container.replaceChildren();
  if (!sources.length) return;
  container.append(el("h3", "", "Records consulted"));
  const list = container.appendChild(el("ol"));
  for (const source of sources) {
    const item = list.appendChild(el("li"));
    item.append(el("span", "cite", String(source.number)));
    const detail = item.appendChild(el("span"));
    const name = source.source.replace(/^database\//, "").replace(/\.csv$/, "");
    detail.append(source.url ? link(source.url, name) : name);
    const extra = [];
    if (source.row) extra.push(`row ${source.row}`);
    extra.push(...source.notes);
    if (extra.length) detail.append(" ", el("small", "", `(${extra.join("; ")})`));
  }
}

// ---------- Asking a question ----------

function setBusy(busy) {
  sendButton.textContent = busy ? "Stop" : "Send";
  sendButton.classList.toggle("stop", busy);
}

async function ask(question) {
  welcome.hidden = true;
  messages.append(el("div", "message user", question));

  const bubble = messages.appendChild(el("div", "message bot"));
  const working = bubble.appendChild(el("div", "working", "Thinking"));
  const notices = bubble.appendChild(el("div"));
  const answer = bubble.appendChild(el("div", "answer"));
  const sourceBox = bubble.appendChild(el("div", "sources"));
  sourceBox.hidden = true;
  scrollToBottom();

  let text = "";
  let sources = [];

  function handle(event) {
    if (event.type === "status") {
      working.textContent = event.text.replace(/…$/, "");
    } else if (event.type === "notice") {
      notices.append(el("p", "notice", event.text));
    } else if (event.type === "token") {
      working.hidden = true;
      text += event.text;
      renderAnswer(answer, text, sources);
    } else if (event.type === "sources") {
      sources = event.sources;
      renderAnswer(answer, text, sources); // now [1] markers can become links
      renderSources(sourceBox, sources);
      sourceBox.hidden = false;
    } else if (event.type === "error") {
      working.hidden = true;
      notices.append(el("p", "error", event.text));
    }
    scrollToBottom();
  }

  controller = new AbortController();
  setBusy(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Server replied ${response.status}`);

    // Read the response as it arrives and handle each complete line.
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // the last piece may be an incomplete line
      for (const line of lines) {
        if (line.trim()) handle(JSON.parse(line));
      }
    }
  } catch (error) {
    const stopped = error.name === "AbortError";
    notices.append(el("p", stopped ? "notice" : "error",
      stopped ? "Answer stopped." : "Could not reach the chatbot. Is web.py still running?"));
  } finally {
    working.hidden = true;
    controller = null;
    setBusy(false);
    scrollToBottom();
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (controller) {
    controller.abort(); // the button says "Stop" while an answer is streaming
    return;
  }
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  input.style.height = "auto";
  ask(question);
});

// Enter sends; Shift+Enter makes a new line.
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!controller) form.requestSubmit();
  }
});

// Grow the box with the text, up to the max-height in styles.css.
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
});

for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    if (!controller) ask(chip.textContent.trim());
  });
}

// ---------- Data status (like /status and /sync in the terminal) ----------

const statusDot = document.getElementById("status-dot");
const statusList = document.getElementById("status-list");
const syncButton = document.getElementById("sync-button");
const syncNote = document.getElementById("sync-note");

// Outlook is optional, so "not configured" is not a problem worth a warning.
const LEVELS = { ready: "ok", config_missing: "", stale: "warn", unavailable: "warn" };
const NAMES = { sports: "Athletics calendar", outlook: "Outlook news" };

function formatTime(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime())
    ? date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "not yet";
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error();
    const data = await response.json();
    const levels = [];
    statusList.replaceChildren();
    for (const [key, item] of Object.entries(data)) {
      const level = item.status in LEVELS ? LEVELS[item.status] : "bad";
      levels.push(level);
      const row = statusList.appendChild(el("li"));
      row.append(el("span", `dot ${level}`), el("strong", "", NAMES[key] || key));
      row.append(el("small", "", item.message));
      row.append(el("small", "", `Last updated: ${formatTime(item.last_success)}`));
    }
    const overall = levels.includes("bad") ? "bad" : levels.includes("warn") ? "warn" : "ok";
    statusDot.className = `dot ${overall}`;
  } catch {
    statusDot.className = "dot bad";
    statusList.replaceChildren(el("li", "", "Could not load the data status."));
  }
}

syncButton.addEventListener("click", async () => {
  syncButton.disabled = true;
  try {
    const response = await fetch("/api/sync", { method: "POST" });
    syncNote.textContent = (await response.json()).message;
    setTimeout(loadStatus, 5000); // give the background refresh a moment
  } catch {
    syncNote.textContent = "Could not start a refresh.";
  } finally {
    syncButton.disabled = false;
  }
});

// Refresh whenever the panel is opened, and once a minute.
document.getElementById("status").addEventListener("toggle", (event) => {
  if (event.target.open) loadStatus();
});
loadStatus();
setInterval(loadStatus, 60000);
