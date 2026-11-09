"""Read selected Outlook news with recoverable authentication and cached status."""

import argparse
import csv
import io
import json
import os
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import msal
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
PRIVATE_DIR = PROJECT_DIR / ".private"
TOKEN_CACHE = PRIVATE_DIR / "outlook_token_cache.json"
STATUS_FILE = PRIVATE_DIR / "outlook_status.json"
NEWS_CSV = PROJECT_DIR / "database" / "Outlook News.csv"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]
_last_status = None


class OutlookSyncError(Exception):
    """An error whose message is safe to show without disclosing auth details."""

    def __init__(self, message: str, status: str = "error"):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _settings() -> dict[str, object]:
    load_dotenv(PROJECT_DIR / ".env")
    settings = {
        "client_id": os.getenv("OUTLOOK_CLIENT_ID", "").strip(),
        "tenant_id": os.getenv("OUTLOOK_TENANT_ID", "organizations").strip(),
        "folder": os.getenv("OUTLOOK_FOLDER", "MC News").strip(),
        "account": os.getenv("OUTLOOK_ACCOUNT", "").strip(),
        "lookback_days": int(os.getenv("OUTLOOK_LOOKBACK_DAYS", "90")),
        "refresh_hours": int(os.getenv("OUTLOOK_REFRESH_HOURS", "1")),
    }
    if int(settings["lookback_days"]) < 1 or int(settings["refresh_hours"]) < 1:
        raise OutlookSyncError("Outlook lookback days and refresh hours must be positive.")
    if not settings["folder"] or not settings["tenant_id"]:
        raise OutlookSyncError("Set an Outlook folder and tenant in .env.")
    return settings


def _atomic_text(path: Path, text: str, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if private:
        path.parent.chmod(stat.S_IRWXU)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            # NamedTemporaryFile creates with 0600 before any token is written.
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _stored_status() -> dict:
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return dict(_last_status or {})
    # If a status write failed, still report that attempt to this process.
    # A newer result from a background process takes precedence over memory.
    if _last_status and str(_last_status.get("last_attempt", "")) >= str(data.get("last_attempt", "")):
        return dict(_last_status)
    return data


def _last_success() -> str | None:
    saved = _stored_status().get("last_success")
    if saved:
        return saved
    try:
        return datetime.fromtimestamp(NEWS_CSV.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _record_status(status: str, message: str, success: bool = False) -> dict:
    global _last_status
    record = {
        "status": status,
        "message": message,
        "last_success": _now().isoformat() if success else _last_success(),
        "last_attempt": _now().isoformat(),
    }
    _last_status = record
    try:
        _atomic_text(STATUS_FILE, json.dumps(record, indent=2) + "\n", private=True)
    except OSError:
        # A status-file permission issue must not interrupt cached answers.
        pass
    return record


def _configured(settings: dict) -> bool:
    return bool(settings["client_id"]) and settings["client_id"] != "your-application-client-id"


def _news_cache_is_fresh(refresh_hours: int) -> bool:
    if not NEWS_CSV.exists():
        return False
    try:
        last = datetime.fromisoformat(_last_success() or "")
        age = (_now() - last).total_seconds()
        return 0 <= age < refresh_hours * 60 * 60
    except (ValueError, TypeError, OSError):
        return False


def outlook_status() -> dict:
    """Report safe connection/freshness information without making a network call."""
    saved = _stored_status()
    last_success = _last_success()
    try:
        settings = _settings()
        if not _configured(settings):
            return {
                "status": "config_missing",
                "last_success": last_success,
                "message": "Outlook is not configured. Follow OUTLOOK_SETUP.md.",
            }
        if saved.get("status") in ("error", "needs_sign_in"):
            return {**saved, "last_success": last_success}
        if not TOKEN_CACHE.exists() and not last_success:
            return {
                "status": "needs_sign_in",
                "last_success": None,
                "message": "Outlook needs sign-in: python outlook_news.py --login",
            }
        fresh = _news_cache_is_fresh(int(settings["refresh_hours"]))
        return {
            "status": "ready" if fresh else "stale",
            "last_success": last_success,
            "message": "Outlook news is up to date." if fresh else "Outlook news is awaiting a successful refresh.",
        }
    except Exception:
        return {
            "status": "error",
            "last_success": last_success,
            "message": "Check Outlook settings in .env; the configuration could not be read.",
        }


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.exists():
        try:
            cache.deserialize(TOKEN_CACHE.read_text(encoding="utf-8"))
        except (ValueError, TypeError):
            raise OutlookSyncError(
                "The Outlook sign-in cache needs renewal: python outlook_news.py --login",
                "needs_sign_in",
            ) from None
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _atomic_text(TOKEN_CACHE, cache.serialize(), private=True)


def _get_access_token(interactive: bool) -> str | None:
    settings = _settings()
    if not _configured(settings):
        return None
    try:
        cache = _load_cache()
    except OutlookSyncError:
        if not interactive:
            raise
        cache = msal.SerializableTokenCache()

    app = msal.PublicClientApplication(
        str(settings["client_id"]),
        authority=f"https://login.microsoftonline.com/{settings['tenant_id']}",
        token_cache=cache,
        timeout=30,
    )
    accounts = app.get_accounts()
    expected_account = str(settings["account"]).casefold()
    if expected_account:
        accounts = [a for a in accounts if a.get("username", "").casefold() == expected_account]
    if len(accounts) > 1:
        raise OutlookSyncError(
            "Multiple Outlook accounts are cached. Set OUTLOOK_ACCOUNT in .env to the intended email address.",
            "needs_sign_in",
        )
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    if (not result or "access_token" not in result) and interactive:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise OutlookSyncError("Microsoft could not start sign-in. Check the app registration and try again.")
        print(flow["message"])
        result = app.acquire_token_by_device_flow(flow)
        if result and "access_token" in result and expected_account:
            claims = result.get("id_token_claims", {})
            signed_in = str(claims.get("preferred_username") or claims.get("email") or "").casefold()
            if signed_in != expected_account:
                raise OutlookSyncError(
                    "The account used for sign-in does not match OUTLOOK_ACCOUNT. Sign in with the configured account.",
                    "needs_sign_in",
                )
    _save_cache(cache)
    return result.get("access_token") if result else None


def _validate_graph_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "graph.microsoft.com"
        or not parsed.path.startswith("/v1.0/")
        or parsed.fragment
    ):
        raise OutlookSyncError("Microsoft returned an unexpected paging URL; the cached news was kept.")


def _graph_get(url: str, token: str, params: dict | None = None) -> dict:
    _validate_graph_url(url)
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            # Keep links in HTML and ask for IDs stable across folder moves.
            "Prefer": 'outlook.body-content-type="html", IdType="ImmutableId"',
        },
        params=params,
        timeout=30,
        allow_redirects=False,
    )
    if 300 <= response.status_code < 400:
        raise OutlookSyncError("Microsoft returned an unexpected redirect; the cached news was kept.")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("value"), list):
        raise OutlookSyncError("Microsoft returned incomplete news data; the cached news was kept.")
    return data


def _pages(url: str, token: str, params: dict):
    visited = set()
    while url:
        _validate_graph_url(url)
        if url in visited:
            raise OutlookSyncError("Microsoft repeated a results page; the cached news was kept.")
        visited.add(url)
        data = _graph_get(url, token, params)
        params = None
        rows = data.get("value")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise OutlookSyncError("Microsoft returned incomplete news data; the cached news was kept.")
        yield rows
        url = data.get("@odata.nextLink")
        if url is not None and not isinstance(url, str):
            raise OutlookSyncError("Microsoft returned an invalid results page; the cached news was kept.")


def _find_folder(token: str, folder_name: str) -> str:
    matches = []
    for folders in _pages(
        f"{GRAPH_ROOT}/me/mailFolders", token, {"$select": "id,displayName", "$top": "100"}
    ):
        matches.extend(
            folder["id"] for folder in folders
            if folder.get("displayName", "").casefold() == folder_name.casefold() and folder.get("id")
        )
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise OutlookSyncError("The configured Outlook news folder was not found. Create it as a top-level folder.")
    raise OutlookSyncError("More than one Outlook folder has the configured name. Use a unique top-level folder name.")


def _normalize_text(text: str) -> str:
    return "\n".join(line for raw in text.splitlines() if (line := " ".join(raw.split())))


def _clean_body(message: dict) -> str:
    body_data = message.get("body") or {}
    body = body_data.get("content") or ""
    if body_data.get("contentType", "").lower() == "html":
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup.select("script, style, head, img, noscript"):
            tag.decompose()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            label = anchor.get_text(" ", strip=True)
            if href.startswith(("https://", "http://", "mailto:")):
                anchor.replace_with(f"{label} ({href})" if label and label != href else href)
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for block in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4"]):
            block.append("\n")
        body = soup.get_text(" ")
    return _normalize_text(body) or _normalize_text(message.get("bodyPreview") or "")


def _fetch_messages(token: str, folder_id: str, lookback_days: int) -> list[dict]:
    cutoff = _now() - timedelta(days=lookback_days)
    url = f"{GRAPH_ROOT}/me/mailFolders/{quote(folder_id, safe='')}/messages"
    params = {
        "$select": "id,subject,from,receivedDateTime,bodyPreview,body,webLink",
        "$filter": f"receivedDateTime ge {cutoff.isoformat().replace('+00:00', 'Z')}",
        "$orderby": "receivedDateTime desc",
        "$top": "50",
    }
    messages = {}
    for page in _pages(url, token, params):
        for message in page:
            received_text = message.get("receivedDateTime", "")
            try:
                received = datetime.fromisoformat(received_text.replace("Z", "+00:00"))
                if received.tzinfo is None:
                    raise ValueError("Missing timezone")
            except (ValueError, TypeError, AttributeError):
                raise OutlookSyncError("A news message has an invalid received date; the cached news was kept.") from None
            if received < cutoff:
                continue
            message_id = message.get("id")
            if not isinstance(message_id, str) or not message_id:
                raise OutlookSyncError("A news message has no stable ID; the cached news was kept.")
            sender = (message.get("from") or {}).get("emailAddress") or {}
            messages[message_id] = {
                "Message ID": message_id,
                "Subject": message.get("subject") or "",
                "Sender name": sender.get("name") or "",
                "Sender email": sender.get("address") or "",
                "Received": received_text,
                "Content": _clean_body(message),
                "Outlook link": message.get("webLink") or "",
            }
    return sorted(messages.values(), key=lambda m: (m["Received"], m["Message ID"]), reverse=True)


def _write_news(messages: list[dict]) -> bool:
    fieldnames = ["Message ID", "Subject", "Sender name", "Sender email", "Received", "Content", "Outlook link"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(messages)
    text = output.getvalue()
    if NEWS_CSV.exists() and NEWS_CSV.read_text(encoding="utf-8") == text.replace("\r\n", "\n"):
        return False
    _atomic_text(NEWS_CSV, text)
    return True


def _failure(error: Exception) -> tuple[str, str]:
    if isinstance(error, OutlookSyncError):
        return error.status, str(error)
    if isinstance(error, requests.HTTPError):
        code = error.response.status_code if error.response is not None else None
        if code == 401:
            return "needs_sign_in", "Outlook needs sign-in again: python outlook_news.py --login"
        if code == 403:
            return "error", "Microsoft denied mail access. Check Mail.Read consent with your Microsoft administrator."
        if code == 429:
            return "error", "Microsoft temporarily limited requests. The next scheduled refresh will retry."
    if isinstance(error, requests.RequestException):
        return "error", "Outlook could not reach Microsoft. Cached news remains available."
    if isinstance(error, OSError):
        return "error", "Outlook could not read or save local files. Check project file permissions."
    return "error", "Outlook refresh failed. Check .env and use python outlook_news.py --login to renew sign-in."


def sync_outlook_news(interactive: bool = False, force: bool = False) -> bool:
    """Refresh only the selected folder; preserve cached news on every failure."""
    try:
        settings = _settings()
        if not _configured(settings):
            _record_status("config_missing", "Outlook is not configured. Follow OUTLOOK_SETUP.md.")
            return False
        if not force and not interactive and _news_cache_is_fresh(int(settings["refresh_hours"])):
            return False
        token = _get_access_token(interactive=interactive)
        if not token:
            _record_status("needs_sign_in", "Outlook needs sign-in: python outlook_news.py --login")
            return False
        folder_id = _find_folder(token, str(settings["folder"]))
        messages = _fetch_messages(token, folder_id, int(settings["lookback_days"]))
        changed = _write_news(messages)
        _record_status("ready", f"Outlook news refreshed ({len(messages)} messages).", success=True)
        return changed
    except Exception as error:
        status, message = _failure(error)
        _record_status(status, message)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import school news from Outlook.")
    parser.add_argument("--login", action="store_true", help="sign in interactively")
    parser.add_argument("--status", action="store_true", help="show local sync status without signing in")
    args = parser.parse_args()
    if not args.status:
        sync_outlook_news(interactive=args.login, force=True)
    state = outlook_status()
    print(state["message"])
    if state["last_success"]:
        print(f"Last successful refresh: {state['last_success']}")
    if not args.status and state["status"] != "ready":
        raise SystemExit(1)
