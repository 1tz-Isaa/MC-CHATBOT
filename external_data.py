"""Download and query the school's public athletics calendar without an LLM."""

import calendar
import csv
import json
import os
import re
import ssl
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import certifi
from bs4 import BeautifulSoup


PROJECT_DIR = Path(__file__).resolve().parent
SPORTS_CSV = PROJECT_DIR / "database" / "Sports Calendar.csv"
SPORTS_STATUS = PROJECT_DIR / ".private" / "sports_sync.json"
SPORTS_PAGE = "https://www.maldencatholic.org/athletics/athletics-calendar"
SPORTS_ELEMENT_URL = "https://www.maldencatholic.org/fs/elements/26503"
SPORTS_CACHE_HOURS = 6
SPORTS_MONTHS_AHEAD = 6
SCHOOL_TIMEZONE = ZoneInfo("America/New_York")
SPORT_CODES = {
    "BKB": "Basketball", "FB": "Football", "FHY": "Field Hockey",
    "SOC": "Soccer", "VOB": "Volleyball",
}
SPORT_NAMES = (
    "field hockey", "ice hockey", "cross country", "indoor track", "outdoor track",
    "basketball", "football", "soccer", "volleyball", "baseball", "softball",
    "lacrosse", "wrestling", "swimming", "tennis", "golf", "rugby", "track", "cheer", "hockey",
)
FIELDNAMES = [
    "Event ID", "Event", "Sport", "Team", "Home/Away", "Opponent", "Date",
    "Time", "Start", "End", "Status", "Date status", "Source",
]


def _now(value: datetime | None = None) -> datetime:
    value = value or datetime.now(SCHOOL_TIMEZONE)
    return value.replace(tzinfo=SCHOOL_TIMEZONE) if value.tzinfo is None else value.astimezone(SCHOOL_TIMEZONE)


def _month_start(year: int, month: int, offset: int) -> datetime:
    month_index = year * 12 + month - 1 + offset
    return datetime(month_index // 12, month_index % 12 + 1, 1, tzinfo=SCHOOL_TIMEZONE)


def _fetch_month(month: datetime) -> str:
    request = Request(
        f"{SPORTS_ELEMENT_URL}?cal_date={month:%Y-%m-%d}",
        headers={"User-Agent": "MC-Chatbot/1.0"},
    )
    with urlopen(request, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_events(html: str, expected_month: datetime | None = None) -> list[dict[str, str]]:
    """Reject error pages and incomplete grids instead of wiping the last cache."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(".fsCalendar")
    picker = soup.select_one(".fsCalendarGridShowMonthPickerButton")
    grid = soup.select_one(".fsCalendarEventGrid")
    if container is None or picker is None or grid is None:
        raise ValueError("The school response did not contain a valid athletics calendar.")
    try:
        year, month = int(picker["data-year"]), int(picker["data-month"])
        date(year, month, 1)
    except (KeyError, ValueError) as error:
        raise ValueError("The athletics calendar month could not be verified.") from error
    if expected_month and (year, month) != (expected_month.year, expected_month.month):
        raise ValueError("The school returned a different month than requested.")
    days = grid.select(f'.fsCalendarDate[data-year="{year}"][data-month="{month - 1}"]')
    if {int(day.get("data-day", "0")) for day in days} != set(range(1, calendar.monthrange(year, month)[1] + 1)):
        raise ValueError("The athletics calendar grid is incomplete.")

    events = []
    for item in grid.select(".fsCalendarInfo"):
        title_element = item.select_one(".fsCalendarEventTitle")
        start_element = item.select_one("time.fsStartTime")
        end_element = item.select_one("time.fsEndTime")
        if title_element is None or start_element is None:
            raise ValueError("An athletics event is missing its title or start date.")
        original = str(title_element.get("title") or title_element.get_text(" ", strip=True))
        title = re.sub(r"^Time:\s*(?:TBA|TBD)\s*-\s*", "", original, flags=re.I).strip()
        is_tba = bool(re.search(r"\b(?:TBA|TBD)\b", original, re.I))
        start = str(start_element.get("datetime", ""))
        end = str(end_element.get("datetime", "")) if end_element else ""
        start_dt = _now(datetime.fromisoformat(start))
        if (start_dt.year, start_dt.month) != (year, month):
            continue  # Adjacent-month grid cells are fetched with their own month.
        match = re.match(
            r"^Malden Catholic (?P<sport>\S+) (?P<gender>[GB]) "
            r"(?P<level>JV|V|FR|JH) (?P<home_away>Home|Away) (?P<opponent>.+)$", title,
        )
        fields = {key: "" for key in ("Sport", "Team", "Home/Away", "Opponent")}
        if match:
            gender = {"G": "Girls", "B": "Boys"}[match["gender"]]
            level = {"V": "Varsity", "JV": "Junior Varsity", "FR": "Freshman", "JH": "Middle School"}[match["level"]]
            fields.update({
                "Sport": SPORT_CODES.get(match["sport"], match["sport"]),
                "Team": f"{gender} {level}", "Home/Away": match["home_away"],
                "Opponent": match["opponent"],
            })
        event_status = "Cancelled" if re.search(r"\bcancel[le]+d\b", title, re.I) else "Postponed" if re.search(r"\bpostponed\b", title, re.I) else "Scheduled"
        date_unconfirmed = bool(re.search(r"need to find.*date|date.*(?:TBA|TBD|to be determined)", title, re.I))
        events.append({
            "Event ID": str(title_element.get("data-occur-id", "")), "Event": title,
            **fields, "Date": start_dt.date().isoformat(),
            "Time": "TBA" if is_tba else start_dt.strftime("%I:%M %p %Z").lstrip("0"),
            "Start": start, "End": end, "Status": event_status,
            "Date status": "Unconfirmed" if date_unconfirmed else "Published",
            "Source": SPORTS_PAGE,
        })
    return events


def sports_sync_status() -> dict:
    try:
        status = json.loads(SPORTS_STATUS.read_text(encoding="utf-8"))
        if not isinstance(status, dict):
            status = {}
    except (OSError, ValueError):
        status = {}
    if SPORTS_CSV.exists() and not status.get("last_success"):
        status["last_success"] = datetime.fromtimestamp(SPORTS_CSV.stat().st_mtime, SCHOOL_TIMEZONE).isoformat()
    status.setdefault("last_success", None)
    if status.get("state") == "error":
        status.update(status="error", message="Calendar refresh failed; saved data is retained." if SPORTS_CSV.exists() else "Calendar refresh failed; no saved calendar is available.")
    elif not SPORTS_CSV.exists():
        status.update(status="unavailable", message="No saved athletics calendar is available.")
    elif _cache_is_fresh():
        status.update(status="ready", message="Saved athletics calendar is current.")
    else:
        status.update(status="stale", message="Saved athletics calendar needs a refresh.")
    return status


def _atomic_write(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            write(handle)
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _cache_is_fresh() -> bool:
    if not SPORTS_CSV.exists():
        return False
    return _now().timestamp() - SPORTS_CSV.stat().st_mtime < SPORTS_CACHE_HOURS * 3600


def sync_sports_calendar(force: bool = False) -> bool:
    """Validate every requested month, then atomically replace the saved calendar."""
    if not force and _cache_is_fresh():
        return False
    now = _now()
    status = sports_sync_status()
    months = [_month_start(now.year, now.month, offset) for offset in range(SPORTS_MONTHS_AHEAD + 1)]
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            pages = list(executor.map(_fetch_month, months))
        events = [event for month, page in zip(months, pages) for event in _parse_events(page, month)]
        unique = {event["Event ID"] or f'{event["Start"]}:{event["Event"]}': event for event in events}
        events = sorted(unique.values(), key=lambda event: (event["Start"], event["Event"]))

        def write_csv(handle):
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(events)

        _atomic_write(SPORTS_CSV, write_csv)
        status.update({
            "state": "ok", "last_attempt": now.isoformat(), "last_success": now.isoformat(),
            "coverage_start": months[0].date().isoformat(),
            "coverage_end": (_month_start(now.year, now.month, SPORTS_MONTHS_AHEAD + 1).date() - timedelta(days=1)).isoformat(),
            "event_count": len(events), "error": "",
        })
        _atomic_write(SPORTS_STATUS, lambda handle: json.dump(status, handle, indent=2))
        return True
    except Exception as error:
        status.update({"state": "error", "last_attempt": now.isoformat(), "error": str(error)})
        try:
            _atomic_write(SPORTS_STATUS, lambda handle: json.dump(status, handle, indent=2))
        except OSError:
            pass
        print(f"Warning: athletics refresh failed; {'retaining saved calendar' if SPORTS_CSV.exists() else 'no saved calendar available'} ({error})")
        return False


def _date_range(query: str, today: date) -> tuple[date | None, date | None, str | None]:
    """Parse explicit date/range requests; unsupported dates must not widen a query."""
    def single_date(target: date, position: int):
        prefix = query[:position]
        if re.search(r"\b(?:on or after|from|since)\s*$", prefix):
            return target, None, None
        if re.search(r"\b(?:on or before|until|through)\s*$", prefix):
            return None, target, None
        if re.search(r"\bafter\s*$", prefix):
            if target == date.max:
                return None, None, "That date is beyond the supported calendar range."
            return target + timedelta(days=1), None, None
        if re.search(r"\bbefore\s*$", prefix):
            if target == date.min:
                return None, None, "That date is beyond the supported calendar range."
            return None, target - timedelta(days=1), None
        return target, target, None

    monday = today - timedelta(days=today.weekday())
    if re.search(r"\b(?:this|next)\s+weekend\b|\bweekend\b", query):
        start = monday + timedelta(days=5 + (7 if "next weekend" in query else 0))
        return start, start + timedelta(days=1), None
    if re.search(r"\b(?:this|next)\s+week\b", query):
        start = monday + timedelta(days=7 if "next week" in query else 0)
        return start, start + timedelta(days=6), None
    if re.search(r"\b(?:this|next)\s+month\b", query):
        start = _month_start(today.year, today.month, 1 if "next month" in query else 0).date()
        return start, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]), None
    for word, offset in (("tomorrow", 1), ("yesterday", -1), ("today", 0), ("tonight", 0)):
        match = re.search(rf"\b{word}\b", query)
        if match:
            target = today + timedelta(days=offset)
            return single_date(target, match.start())
    months = {name.casefold(): n for n in range(1, 13) for name in (calendar.month_name[n], calendar.month_abbr[n])}
    months["sept"] = 9
    values = []
    patterns = [
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
        (r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", lambda m: date(int(m[3] or today.year), int(m[1]), int(m[2]))),
        (r"\b(" + "|".join(months) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
         lambda m: date(int(m[3] or today.year), months[m[1]], int(m[2]))),
    ]
    for pattern, convert in patterns:
        for match in re.finditer(pattern, query):
            try:
                values.append((match.start(), convert(match)))
            except ValueError:
                return None, None, "That date is not valid. Please use a date such as November 15, 2026."
    values.sort()
    if values:
        if len(values) > 2 or (len(values) == 2 and values[1][1] < values[0][1]):
            return None, None, "Please give one date or a date range in start-to-end order."
        if len(values) == 1:
            return single_date(values[0][1], values[0][0])
        return values[0][1], values[-1][1], None
    for weekday, name in enumerate(calendar.day_name):
        match = re.search(rf"\b(?:(this|next)\s+)?{name.casefold()}\b", query)
        if match:
            target = monday + timedelta(days=weekday + (7 if match[1] == "next" else 0))
            if not match[1] and target < today:
                target += timedelta(days=7)
            return single_date(target, match.start())
    if re.search(r"\b(?:on|between|from|until|through|after|before|during|last|in)\b|\b\d{1,2}[-/]\d{1,2}\b", query):
        return None, None, "Please specify the schedule date as YYYY-MM-DD, a month and day, a weekday, or this/next week."
    return None, None, None


def _calendar_request(query: str) -> bool:
    if re.search(r"\b(?:coach(?:es|ing)?|tryouts?|register|registration|requirements?|eligib\w*|transportation|uniform|rules?|join)\b|\b(?:can|may|allowed to)\s+(?:i|we|students?)\s+play\b", query):
        return False
    sport = any(re.search(rf"\b{re.escape(name)}\b", query) for name in SPORT_NAMES)
    sports = sport or bool(re.search(r"\b(?:sports?|athletics?|teams?)\b", query))
    games = bool(re.search(r"\b(?:games?|matches|match|fixtures?)\b", query))
    time_words = bool(re.search(r"\b(?:when|time|today|tomorrow|tonight|next|upcoming|week|weekend|schedule|calendar)\b|\d{4}-\d{2}-\d{2}", query))
    return games or (sports and time_words) or bool(re.search(r"\bwhen\b.*\bplay\b", query))


def _select_events(question: str, limit: int, now: datetime | None):
    query = question.casefold().replace("’", "'")
    if not _calendar_request(query):
        return None
    current = _now(now)
    start_date, end_date, error = _date_range(query, current.date())
    if error:
        return {"message": error, "events": []}
    if not SPORTS_CSV.exists():
        return {"message": "The athletics calendar is unavailable because it has not been downloaded successfully yet.", "events": []}
    try:
        with SPORTS_CSV.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"Event", "Date", "Start", "Sport", "Team"}.issubset(reader.fieldnames or []):
                raise ValueError("missing calendar columns")
            events = list(reader)
    except (OSError, ValueError, csv.Error):
        return {"message": "The saved athletics calendar could not be read. A successful refresh is needed.", "events": []}

    requested_sport = next((name for name in SPORT_NAMES if re.search(rf"\b{re.escape(name)}\b", query)), None)
    sport_names = {
        "hockey": {"field hockey", "ice hockey", "hockey"},
        "track": {"indoor track", "outdoor track", "track", "track and field"},
    }.get(requested_sport, {requested_sport})
    gender = "Girls" if re.search(r"\bgirls?\b", query) else "Boys" if re.search(r"\bboys?\b", query) else None
    level = next((value for pattern, value in (
        (r"\b(?:junior\s+varsity|jv)\b", "Junior Varsity"), (r"\bvarsity\b", "Varsity"),
        (r"\b(?:freshman|freshmen|fr)\b", "Freshman"), (r"\b(?:middle\s+school|jh)\b", "Middle School"),
    ) if re.search(pattern, query)), None)
    venue = "Home" if re.search(r"\bhome\b", query) else "Away" if re.search(r"\baway\b", query) else None
    opponent_match = re.search(r"\b(?:against|versus|vs\.?)\s+(.+?)(?=\s+(?:on|today|tomorrow|next|this|at|in|between|from|are|is|will)\b|[?!]|$)", query)
    opponent = opponent_match[1].strip() if opponent_match else None
    matched = []
    uncertain = 0
    for event in events:
        team = event.get("Team", "")
        if requested_sport and event.get("Sport", "").casefold() not in sport_names:
            continue
        if gender and not team.startswith(gender + " "):
            continue
        if level and team.removeprefix("Girls ").removeprefix("Boys ") != level:
            continue
        if venue and event.get("Home/Away") != venue:
            continue
        if opponent and opponent not in event.get("Opponent", "").casefold():
            continue
        if event.get("Status", "").casefold() in {"cancelled", "canceled", "postponed"}:
            continue
        if event.get("Date status") == "Unconfirmed" or re.search(r"need to find.*date", event["Event"], re.I):
            uncertain += 1
            continue
        try:
            event_date = date.fromisoformat(event["Date"])
            event_start = _now(datetime.fromisoformat(event["Start"]))
        except (ValueError, KeyError):
            uncertain += 1
            continue
        time_unknown = event.get("Time", "").upper() in {"TBA", "TBD", ""}
        if start_date or end_date:
            if (start_date and event_date < start_date) or (end_date and event_date > end_date):
                continue
        elif time_unknown:
            if event_date < current.date():
                continue
            uncertain += 1
            continue  # A placeholder midnight cannot identify the next timed game.
        elif event_start < current:
            continue
        matched.append(event)
    matched.sort(key=lambda event: (event["Start"], event["Event"]))
    number_match = re.search(r"\bnext\s+(\d+)\s+(?:games?|matches|events?)\b", query)
    if number_match:
        limit = min(max(int(number_match[1]), 1), 100)
    elif not (start_date or end_date) and re.search(r"\bnext\b", query) and not re.search(r"\b(?:games|matches|events)\b", query):
        limit = 1
    return {
        "events": matched[:max(limit, 1)], "total": len(matched), "uncertain": uncertain,
        "date_start": start_date, "date_end": end_date, "message": "",
    }


def _freshness(now: datetime | None = None) -> str:
    status = sports_sync_status()
    last = status.get("last_success")
    if not last:
        return "Last successful update: unavailable."
    try:
        updated = _now(datetime.fromisoformat(last))
        label = updated.strftime("%b %d, %Y at %I:%M %p %Z")
        stale = (_now(now) - updated).total_seconds() > SPORTS_CACHE_HOURS * 3600
    except (ValueError, TypeError):
        return "Last successful update: unavailable."
    note = " Saved data may be out of date." if stale or status.get("state") == "error" else ""
    return f"Last successful update: {label}.{note}"


def calendar_answer_for_question(question: str, limit: int = 20, *, now: datetime | None = None) -> str | None:
    """Return a cited deterministic schedule answer, or None for other questions."""
    result = _select_events(question, limit, now)
    if result is None:
        return None
    lines = []
    if result.get("message"):
        lines.append(result["message"])
    elif not result["events"]:
        lines.append("No matching games are listed in the saved athletics calendar. This does not confirm that no games are scheduled.")
    else:
        for event in result["events"]:
            day = date.fromisoformat(event["Date"]).strftime("%a, %b %d, %Y")
            title = " ".join(value for value in (event.get("Team"), event.get("Sport")) if value)
            opponent = event.get("Opponent")
            detail = f"{title} vs. {opponent}" if title and opponent else event["Event"]
            home_away = f" ({event['Home/Away']})" if event.get("Home/Away") else ""
            time_text = event.get("Time", "TBA")
            lines.append(f"- {day}, {time_text}: {detail}{home_away}")
        if result["total"] > len(result["events"]):
            lines.append(f"Showing {len(result['events'])} of {result['total']} matching games; narrow the date or team to see fewer results.")
    if result.get("uncertain"):
        lines.append("Entries with an unconfirmed date/time are excluded from upcoming-game ordering; confirm those details with Athletics.")
    status = sports_sync_status()
    if status.get("coverage_start") and status.get("coverage_end"):
        lines.append(f"Saved calendar coverage: {status['coverage_start']} through {status['coverage_end']}.")
        try:
            covered_start = date.fromisoformat(status["coverage_start"])
            covered_end = date.fromisoformat(status["coverage_end"])
            if any(
                requested and not covered_start <= requested <= covered_end
                for requested in (result.get("date_start"), result.get("date_end"))
            ):
                lines.append("Requested dates extend outside the saved calendar coverage; games outside that period have not been checked.")
        except (TypeError, ValueError):
            pass
    lines.extend([_freshness(now), f"Source: [Malden Catholic athletics calendar]({SPORTS_PAGE})"])
    return "\n".join(lines)


def calendar_context_for_question(question: str, limit: int = 20, *, now: datetime | None = None) -> str:
    """Backward-compatible context API; the CLI can render the answer directly."""
    return calendar_answer_for_question(question, limit, now=now) or ""


if __name__ == "__main__":
    refreshed = sync_sports_calendar(force=True)
    print("Sports calendar refreshed." if refreshed else "Sports calendar not changed.")
