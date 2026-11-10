"""Browser chat page for the school assistant.

Run `python web.py` and open http://127.0.0.1:8000. This file is only the
"front door": every answer is produced by the same functions the terminal
chatbot in main.py uses, so the two can never disagree.

How a question travels:

1. The page (web/app.js) POSTs {"question": "..."} to /api/chat.
2. answer_events() below does the same steps as main.answer_question(), but
   instead of print() it *yields* small dictionaries called events.
3. Each event is sent to the browser as one line of JSON as soon as it is
   ready, so the answer appears word by word.

Event types: status, notice, token, sources, error, done.
"""

import argparse
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import main as chatbot
from sync_data import BackgroundSync, source_status


WEB_DIR = Path(__file__).resolve().parent / "web"

_background: BackgroundSync | None = None
_sync_enabled = True
_chain = None
_chain_lock = threading.Lock()


def _get_chain():
    """Build the Ollama chain once and share it between requests."""
    global _chain
    with _chain_lock:
        if _chain is None:
            _chain = chatbot.build_chain()
        return _chain


def _answer_steps(question: str):
    # Sports schedule questions are answered straight from the saved
    # calendar, without Ollama. The text already contains its source link.
    calendar_answer = chatbot.calendar_answer_for_question(question)
    if calendar_answer is not None:
        yield {"type": "token", "text": calendar_answer}
        return

    from Vector import get_retriever

    yield {"type": "status", "text": "Searching school records…"}
    documents = get_retriever().invoke(question)
    if not documents:
        yield {"type": "token", "text": "I don't have matching information in the school database."}
        return

    blocks, sources = chatbot.select_records(documents)
    if any(doc.metadata.get("dataset") == "Outlook News" for doc in documents):
        outlook = source_status()["outlook"]
        yield {"type": "notice", "text": (
            f"Outlook: {outlook['message']} Last update: {outlook.get('last_success') or 'unknown'}"
        )}

    yield {"type": "status", "text": "Writing the answer…"}
    for chunk in _get_chain().stream({
        "current_date": datetime.now(chatbot.SCHOOL_TZ).date().isoformat(),
        "data": "\n\n---\n\n".join(blocks),
        "question": question,
    }):
        text = chatbot._chunk_text(chunk)
        if text:
            yield {"type": "token", "text": text}
    # The browser never needs file paths from this computer.
    yield {"type": "sources", "sources": [
        {key: entry[key] for key in ("number", "source", "row", "url", "notes")}
        for entry in sources
    ]}


def answer_events(question: str):
    """Yield the steps of one answer as dictionaries (see module docstring)."""
    try:
        yield from _answer_steps(question)
    except Exception as error:
        # Same message as the terminal; details stay out of the browser.
        yield {"type": "error", "text": (
            f"Could not finish this answer ({type(error).__name__}). "
            "Check that Ollama is running and try again."
        )}
    yield {"type": "done"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background data refresh with the server and stop it afterwards."""
    global _background
    if _sync_enabled:
        _background = BackgroundSync()
        _background.start()
    yield
    if _background:
        _background.stop()


app = FastAPI(title="MC Chatbot", lifespan=lifespan, docs_url=None, redoc_url=None)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.post("/api/chat")
def chat(request: ChatRequest):
    def lines():
        for event in answer_events(request.question.strip()):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    # no-cache/no-buffering so each line reaches the page immediately.
    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@app.get("/api/status")
def status():
    """Same information as the terminal's /status command."""
    return {
        name: {
            "status": item.get("status", "unknown"),
            "message": item.get("message", ""),
            "last_success": item.get("last_success"),
        }
        for name, item in source_status().items()
    }


@app.post("/api/sync")
def sync():
    """Same as the terminal's /sync command: refresh in the background."""
    global _background
    if _background is None:
        _background = BackgroundSync()
        _background.start()
    else:
        _background.request()
    return {"message": "Checking for updates in the background."}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def main() -> int:
    global _sync_enabled
    import uvicorn

    parser = argparse.ArgumentParser(description="Serve the MC Chatbot web page.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to listen on (default: this computer only)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-sync", action="store_true", help="use saved data without background refresh")
    args = parser.parse_args()
    _sync_enabled = not args.no_sync
    print(f"MC Chatbot is running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
