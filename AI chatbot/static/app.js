const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const messages = document.getElementById("messages");
const sendButton = document.getElementById("send-button");
const modelName = document.getElementById("model-name");
const modelStatus = document.getElementById("model-status");
const resourceCount = document.getElementById("resource-count");
const pendingCount = document.getElementById("pending-count");

const history = [];

function renderMessage(role, text, sources = []) {
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}`;

  const body = document.createElement("p");
  body.textContent = text;
  wrapper.appendChild(body);

  if (sources.length > 0) {
    const meta = document.createElement("div");
    meta.className = "meta";

    const sourceTitle = document.createElement("strong");
    sourceTitle.textContent = "Sources";
    meta.appendChild(sourceTitle);

    const list = document.createElement("div");
    list.className = "sources";

    for (const source of sources) {
      const link = document.createElement(source.url ? "a" : "div");
      link.className = "source-link";
      link.textContent = source.title;
      if (source.url) {
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noreferrer";
      }

      const type = document.createElement("span");
      type.className = "source-type";
      type.textContent = source.source_type === "official" ? "Official source" : "Local team data";
      link.appendChild(document.createElement("br"));
      link.appendChild(type);
      list.appendChild(link);
    }

    meta.appendChild(list);
    wrapper.appendChild(meta);
  }

  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

function setBusy(isBusy) {
  sendButton.disabled = isBusy;
  input.disabled = isBusy;
  sendButton.textContent = isBusy ? "Thinking..." : "Send";
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    modelName.textContent = data.model;
    modelStatus.textContent = data.model_available ? "Ready" : "Model missing or Ollama offline";
    resourceCount.textContent = `${data.resource_count} resources`;
    pendingCount.textContent = `${data.catalog_counts.pending_submissions} pending`;
  } catch (error) {
    modelName.textContent = "Unavailable";
    modelStatus.textContent = "Health check failed";
    resourceCount.textContent = "Unknown";
    pendingCount.textContent = "Unknown";
  }
}

async function sendMessage(message) {
  renderMessage("user", message);
  history.push({ role: "user", content: message });
  setBusy(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Chat request failed.");
    }

    renderMessage("assistant", data.answer, data.sources || []);
    history.push({ role: "assistant", content: data.answer });
  } catch (error) {
    renderMessage(
      "assistant",
      error.message || "Something went wrong while contacting the chatbot."
    );
  } finally {
    setBusy(false);
    input.focus();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) {
    return;
  }

  input.value = "";
  await sendMessage(message);
});

document.querySelectorAll(".prompt-chip").forEach((button) => {
  button.addEventListener("click", async () => {
    const prompt = button.dataset.prompt;
    input.value = "";
    await sendMessage(prompt);
  });
});

renderMessage(
  "assistant",
  "Ask about admissions, teachers, classes, rooms, counseling, daily news, school events, sports calendar, or any local catalog information you add."
);
loadHealth();
