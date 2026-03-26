from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from catalog import RAW_SUBMISSIONS_PATH, bootstrap_catalog


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return normalized or "entry"


def summarize(value: str, limit: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def merge_raw_submissions(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["id"]: row for row in existing}
    for row in incoming:
        by_id[row["id"]] = row
    merged = list(by_id.values())
    merged.sort(key=lambda row: (row.get("submitted_at") or "", row["id"]), reverse=True)
    return merged


def create_manual_news_submission(
    *,
    title: str,
    body: str,
    publish_date: str | None = None,
    audience: str = "school community",
    category: str = "daily announcements",
    source_url: str | None = None,
    owner: str = "Manual News Intake",
) -> dict[str, Any]:
    publish_date = publish_date or date.today().isoformat()
    slug = slugify(f"{publish_date}-{title}")
    return {
        "id": f"raw-manual-news-{slug}",
        "collector_name": owner,
        "category": "daily news",
        "target_table": "news_items",
        "raw_text": body,
        "status": "approved",
        "submitted_at": publish_date,
        "source_system": "manual",
        "notes": f"Manual local news import for '{title}'.",
        "payload": {
            "id": f"news-{slug}",
            "title": title,
            "summary": summarize(body),
            "publish_date": publish_date,
            "audience": audience,
            "category": category,
            "source_url": source_url,
            "owner": owner,
            "last_updated": publish_date,
            "active": True,
            "is_placeholder": False,
        },
    }


def create_manual_event_submission(
    *,
    title: str,
    summary: str,
    event_date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    location: str | None = None,
    audience: str = "school community",
    category: str = "school event",
    details: str | None = None,
    source_url: str | None = None,
    owner: str = "Manual Event Intake",
) -> dict[str, Any]:
    event_date = event_date or date.today().isoformat()
    slug = slugify(f"{event_date}-{title}")
    return {
        "id": f"raw-manual-event-{slug}",
        "collector_name": owner,
        "category": "events calendar",
        "target_table": "events",
        "raw_text": details or summary,
        "status": "approved",
        "submitted_at": event_date,
        "source_system": "manual",
        "notes": f"Manual local event import for '{title}'.",
        "payload": {
            "id": f"event-{slug}",
            "title": title,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
            "category": category,
            "audience": audience,
            "summary": summarize(summary),
            "details": details,
            "source_url": source_url,
            "owner": owner,
            "last_updated": event_date,
            "active": True,
            "is_placeholder": False,
        },
    }


def save_raw_submission(submission: dict[str, Any]) -> dict[str, Any]:
    existing = read_json(RAW_SUBMISSIONS_PATH, [])
    merged = merge_raw_submissions(existing, [submission])
    write_json(RAW_SUBMISSIONS_PATH, merged)
    bootstrap_catalog()
    return submission
