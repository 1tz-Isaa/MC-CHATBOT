# MC Chatbot

A local Malden Catholic school assistant built with Python, Ollama, LangChain,
and Chroma. It searches school CSV records and uses the retrieved information
to answer questions in the terminal or on a local web page.

The earlier browser-based prototype remains in [AI chatbot](AI%20chatbot/README.md).
This guide covers the chatbot at the repository root.

## Setup

Install Python 3.13 and [Ollama](https://ollama.com/), then run these commands
from the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirement.txt
ollama pull mxbai-embed-large
ollama pull qwen2.5:7b
python main.py
```

Keep Ollama running for general questions. The first general question builds
or upgrades the local vector index and may take longer than later questions.
Calendar answers use the saved schedule directly and do not need Ollama.
Enter `q` to quit; Ctrl+C during an answer cancels that answer.

## Web page

To chat in a browser instead of the terminal, run:

```bash
python web.py
```

Then open <http://127.0.0.1:8000>. The page streams answers as they are
written, turns `[1]` citations into links to the records consulted, and has a
**Stop** button while an answer is in progress. **Data status** in the top bar
shows the same information as `/status`, and **Check for updates** does the
same as `/sync`.

- `web.py`: a small FastAPI server. It calls the same functions as `main.py`
  and sends each step of an answer to the page as one line of JSON.
- `web/`: the page itself (`index.html`, `styles.css`, `app.js`), with no
  build step or JavaScript libraries.

The server only accepts connections from the same computer. Options:
`--port 8080` to use another port, `--no-sync` to skip background refreshes.

## Terminal commands

Commands inside the terminal chatbot:

- `/status`: show each source's last successful refresh and any connection problem.
- `/sync`: request a refresh in the background.
- `q`: quit.

## Data and updates

- `database/`: school records, with different columns supported in each CSV.
- `Vector.py`: supports different CSV schemas, splits long records into passages,
  and synchronizes only changed records. Reordering rows or inserting a new
  email does not re-embed unchanged records.
- `external_data.py`: downloads the public athletics calendar and provides
  direct schedule answers filtered by sport, team, date, opponent, and venue.
  It refreshes after six hours and shows source links, freshness, and coverage.
- `outlook_news.py`: optionally imports messages from a top-level Outlook
  folder named `MC News`. See [OUTLOOK_SETUP.md](OUTLOOK_SETUP.md) for sign-in
  and configuration instructions.
- `sync_data.py`: refreshes source CSVs independently of the chatbot and Ollama.
- `main.py`: streams answers using `qwen2.5:7b`, numbers the retrieved records,
  and lists their source links or local CSV locations.

While the chatbot is open, a separate process checks for updates at startup
and every five minutes, using each source's refresh interval. Network refreshes
do not block question input. Failed downloads retain the last saved data, and
calendar answers indicate when it is stale. Use `python main.py --no-sync` to
start with saved data without automatic background refreshes.

For an independent or scheduled refresh, run:

```bash
.venv/bin/python sync_data.py
.venv/bin/python sync_data.py --status
```

The first command fetches sources when due; the second only reads status. Add
`--force` to fetch immediately, or `--index` to also update the vector index
(requires Ollama). Otherwise, changed CSVs are indexed on the next general
question. Overlapping refresh processes skip the duplicate run.

A daily Codex task can run the first command while the chatbot is closed.
Local scheduled tasks require the computer to be awake and the Codex desktop
app running. Outlook remains optional and needs the configuration and initial
Microsoft sign-in described in [OUTLOOK_SETUP.md](OUTLOOK_SETUP.md).

The repository excludes `.env`, sign-in tokens, imported Outlook messages,
downloaded sports schedules, the Python environment, and the generated Chroma
index. These remain local. `.env.example` contains configuration placeholders.

## Calendar examples

- “When is the next girls varsity soccer game?”
- “Show boys JV basketball games next week.”
- “Which home games are on November 15?”

Calendar coverage includes the current month and the following six months.
Unconfirmed dates and cancelled/postponed games are not offered as the next
scheduled game. When a request falls outside saved coverage, the answer says so.

## Checks and limitations

Run the offline regression tests with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The calendar is limited to what the school publishes. General answers depend
on retrieved CSV passages; the source list shows the records consulted, not
an independent verification of each generated claim. Check the linked school
source for time-sensitive details. Outlook's live connection cannot be checked
until an account is configured and signed in.
