from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ingest import create_manual_event_submission, save_raw_submission


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a manual school event to the local catalog.")
    parser.add_argument("--title", help="Event title")
    parser.add_argument("--summary", help="Short event summary")
    parser.add_argument("--event-date", help="Event date in YYYY-MM-DD format")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--location")
    parser.add_argument("--audience", default="school community")
    parser.add_argument("--category", default="school event")
    parser.add_argument("--details")
    parser.add_argument("--source-url")
    parser.add_argument("--owner", default="Manual Event Intake")
    args = parser.parse_args()

    title = args.title or input("Event title: ").strip()
    summary = args.summary or input("Short summary: ").strip()

    if not title:
        raise SystemExit("An event title is required.")
    if not summary:
        raise SystemExit("A short summary is required.")

    submission = create_manual_event_submission(
        title=title,
        summary=summary,
        event_date=args.event_date,
        start_time=args.start_time,
        end_time=args.end_time,
        location=args.location,
        audience=args.audience,
        category=args.category,
        details=args.details,
        source_url=args.source_url,
        owner=args.owner,
    )
    saved = save_raw_submission(submission)
    print(json.dumps(saved, indent=2))


if __name__ == "__main__":
    main()
