"""Refresh external CSV caches independently of answering questions.

The default command needs no Ollama process. Run with --index to also update
the vector index, or --status for a read-only connection/freshness check.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from external_data import sports_sync_status, sync_sports_calendar
from file_lock import try_lock
from outlook_news import outlook_status, sync_outlook_news


PROJECT_DIR = Path(__file__).resolve().parent
PRIVATE_DIR = PROJECT_DIR / ".private"


def source_status() -> dict:
    return {"sports": sports_sync_status(), "outlook": outlook_status()}


def run_sync(force: bool = False, index: bool = False) -> dict:
    """Serialize scheduled/background refreshes; each source fails independently."""
    PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (PRIVATE_DIR / "source_sync.lock").open("a") as lock:
        try:
            try_lock(lock)
        except BlockingIOError:
            return {"status": "busy", "message": "A refresh is already running."}

        outcomes = {}
        for name, sync in (("sports", sync_sports_calendar), ("outlook", sync_outlook_news)):
            try:
                outcomes[name] = {"changed": sync(force=force)}
            except Exception as error:
                # Do not expose request URLs, tokens, or message contents in logs.
                outcomes[name] = {"changed": False, "error": type(error).__name__}

        statuses = source_status()
        for name, status in statuses.items():
            outcomes[name].update(status)
        if index:
            try:
                from Vector import sync_vector_store

                outcomes["index"] = {"status": "ready" if sync_vector_store() else "error"}
            except Exception as error:
                outcomes["index"] = {"status": "error", "error": type(error).__name__}
        failed = any(
            item.get("status") in {"error", "needs_sign_in"} or item.get("error")
            for item in outcomes.values()
        )
        return {
            "status": "error" if failed else "ready",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "sources": outcomes,
        }


class BackgroundSync:
    """Check cache freshness in a separate process so input/answers stay usable."""

    def __init__(self, interval_seconds: float = 300):
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="school-data-refresh")
        self._thread.start()

    def request(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
                # Keep only the latest attempt; no mail bodies or credentials are logged.
                log_fd = os.open(PRIVATE_DIR / "sync.log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(log_fd, "w") as log:
                    subprocess.run(
                        [sys.executable, str(PROJECT_DIR / "sync_data.py"), "--quiet"],
                        cwd=PROJECT_DIR,
                        # Windows would otherwise write the log in a legacy encoding.
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        timeout=240,
                        start_new_session=True,
                        check=False,
                    )
            except (OSError, subprocess.TimeoutExpired):
                # Source status retains the last successful fetch; don't break chat input.
                pass
            self._wake.wait(self.interval_seconds)
            self._wake.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="ignore source cache age")
    parser.add_argument("--index", action="store_true", help="also index changed CSV records (needs Ollama)")
    parser.add_argument("--status", action="store_true", help="show cache/auth status without fetching")
    parser.add_argument("--quiet", action="store_true", help="print only problems")
    args = parser.parse_args()
    result = source_status() if args.status else run_sync(force=args.force, index=args.index)
    failed = result.get("status") == "error"
    if not args.quiet or failed:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
