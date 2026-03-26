from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any

import httpx
import msal


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from catalog import RAW_SUBMISSIONS_PATH, bootstrap_catalog


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
CONFIG_PATH = ROOT_DIR / "data" / "outlook_import_config.json"
TOKEN_CACHE_PATH = ROOT_DIR / "data" / ".msal_token_cache.json"


@dataclass
class SenderRule:
    name: str | None
    email: str | None


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


def load_config() -> dict[str, Any]:
    config = read_json(CONFIG_PATH, None)
    if not config:
        raise SystemExit(f"Missing config file: {CONFIG_PATH}")
    client_id = config.get("client_id")
    if not client_id or client_id.startswith("REPLACE_WITH_"):
        raise SystemExit("Set a real Microsoft Entra app client_id in data/outlook_import_config.json")
    return config


def build_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def persist_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def acquire_access_token(config: dict[str, Any], force_login: bool) -> str:
    cache = build_cache()
    authority = f"https://login.microsoftonline.com/{config.get('tenant', 'common')}"
    app = msal.PublicClientApplication(
        client_id=config["client_id"],
        authority=authority,
        token_cache=cache,
    )
    scopes = config.get("scopes") or ["User.Read", "Mail.Read", "offline_access"]

    result: dict[str, Any] | None = None
    if not force_login:
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes=scopes, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise SystemExit(f"Failed to start device flow: {json.dumps(flow, indent=2)}")
        print(flow["message"])
        result = app.acquire_token_by_device_flow(flow)

    persist_cache(cache)

    if not result or "access_token" not in result:
        raise SystemExit(
            "Failed to get a Microsoft Graph access token.\n"
            f"error={result.get('error') if result else 'unknown'}\n"
            f"description={result.get('error_description') if result else 'unknown'}"
        )

    return result["access_token"]


def fetch_messages(config: dict[str, Any], access_token: str) -> list[dict[str, Any]]:
    endpoint = config.get("message_endpoint") or "/me/mailFolders/inbox/messages"
    top = int(config.get("top", 50))
    params = {
        "$top": max(1, min(top, 200)),
        "$orderby": "receivedDateTime DESC",
        "$select": "id,internetMessageId,subject,from,receivedDateTime,bodyPreview,body,webLink",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.body-content-type="text"',
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{GRAPH_BASE_URL}{endpoint}", params=params, headers=headers)
        response.raise_for_status()
    return response.json().get("value", [])


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sender_rules(config: dict[str, Any]) -> list[SenderRule]:
    rules = []
    for sender in config.get("allowed_senders", []):
        rules.append(SenderRule(name=sender.get("name"), email=sender.get("email")))
    return rules


def matches_sender(message: dict[str, Any], rules: list[SenderRule]) -> bool:
    sender = (message.get("from") or {}).get("emailAddress") or {}
    sender_name = (sender.get("name") or "").strip().lower()
    sender_email = (sender.get("address") or "").strip().lower()
    for rule in rules:
        name_ok = not rule.name or sender_name == rule.name.strip().lower()
        email_ok = not rule.email or sender_email == rule.email.strip().lower()
        if name_ok and email_ok:
            return True
    return False


def matches_subject(message: dict[str, Any], subject_regex: re.Pattern[str]) -> bool:
    subject = (message.get("subject") or "").strip()
    return bool(subject_regex.match(subject))


def parse_received_date(received_at: str | None) -> tuple[str, str]:
    if not received_at:
        now = datetime.now(UTC)
        return now.date().isoformat(), now.isoformat()
    parsed = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    return parsed.date().isoformat(), parsed.isoformat()


def build_summary(message: dict[str, Any]) -> tuple[str, str]:
    body = clean_text(((message.get("body") or {}).get("content")))
    preview = clean_text(message.get("bodyPreview"))
    text = body or preview
    if not text:
        text = "No announcement body was available from Outlook."
    summary = text[:280].rstrip()
    if len(text) > 280:
        summary += "..."
    return summary, text


def load_raw_submissions() -> list[dict[str, Any]]:
    return read_json(RAW_SUBMISSIONS_PATH, [])


def save_raw_submissions(rows: list[dict[str, Any]]) -> None:
    write_json(RAW_SUBMISSIONS_PATH, rows)


def merge_imported_submissions(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["id"]: row for row in existing}
    for row in incoming:
        by_id[row["id"]] = row
    merged = list(by_id.values())
    merged.sort(key=lambda row: (row.get("submitted_at") or "", row["id"]), reverse=True)
    return merged


def build_submission(config: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    publish_date, received_at = parse_received_date(message.get("receivedDateTime"))
    summary, full_text = build_summary(message)
    subject = (message.get("subject") or "Daily Announcements").strip()
    message_id = message.get("internetMessageId") or message.get("id")
    normalized_external_id = re.sub(r"[^a-zA-Z0-9]+", "-", message_id).strip("-").lower()
    submission_id = f"raw-outlook-{normalized_external_id or message['id']}"

    return {
        "id": submission_id,
        "collector_name": "Outlook Importer",
        "category": "daily news",
        "target_table": "news_items",
        "raw_text": full_text,
        "status": "approved" if config.get("auto_approve", True) else "pending",
        "submitted_at": publish_date,
        "source_system": "outlook",
        "notes": f"Imported from Outlook subject '{subject}'.",
        "payload": {
            "id": f"news-{normalized_external_id or message['id']}",
            "title": subject,
            "summary": summary,
            "publish_date": publish_date,
            "audience": config.get("audience", "school community"),
            "category": config.get("category", "daily announcements"),
            "source_url": message.get("webLink"),
            "external_id": message_id,
            "owner": config.get("owner", "Daily Announcements Import"),
            "last_updated": received_at,
            "active": True,
            "is_placeholder": False,
        },
    }


def import_announcements(force_login: bool, lookback_days: int) -> dict[str, Any]:
    config = load_config()
    access_token = acquire_access_token(config, force_login=force_login)
    messages = fetch_messages(config, access_token)

    subject_pattern = re.compile(config["subject_regex"])
    allowed = sender_rules(config)
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

    matching_messages = []
    for message in messages:
        received = message.get("receivedDateTime")
        if received:
            received_at = datetime.fromisoformat(received.replace("Z", "+00:00"))
            if received_at < cutoff:
                continue
        if not matches_sender(message, allowed):
            continue
        if not matches_subject(message, subject_pattern):
            continue
        matching_messages.append(message)

    incoming = [build_submission(config, message) for message in matching_messages]
    existing = load_raw_submissions()
    merged = merge_imported_submissions(existing, incoming)
    save_raw_submissions(merged)
    bootstrap_catalog()

    return {
      "matched_count": len(incoming),
      "recent_messages_checked": len(messages),
      "submission_ids": [row["id"] for row in incoming],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Daily Announcements emails from Outlook into the local catalog.")
    parser.add_argument("--force-login", action="store_true", help="Ignore cached tokens and force a new device-code sign-in.")
    parser.add_argument("--lookback-days", type=int, default=30, help="Only import messages received in the last N days.")
    args = parser.parse_args()

    summary = import_announcements(force_login=args.force_login, lookback_days=args.lookback_days)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
