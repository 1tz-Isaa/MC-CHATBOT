from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ingest import create_manual_news_submission, save_raw_submission


def prompt_multiline(prompt: str) -> str:
    print(prompt)
    print("Paste the body below. Type END on its own line when finished.")
    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a manual daily-news entry to the local catalog.")
    parser.add_argument("--title", help="News title, such as 'Daily Announcements 3.24.26'")
    parser.add_argument("--body", help="Body text for the announcement")
    parser.add_argument("--publish-date", help="Publish date in YYYY-MM-DD format")
    parser.add_argument("--audience", default="school community")
    parser.add_argument("--category", default="daily announcements")
    parser.add_argument("--source-url")
    parser.add_argument("--owner", default="Manual News Intake")
    args = parser.parse_args()

    title = args.title or input("Title: ").strip()
    body = args.body or prompt_multiline("Announcement body:")

    if not title:
        raise SystemExit("A title is required.")
    if not body:
        raise SystemExit("A body is required.")

    submission = create_manual_news_submission(
        title=title,
        body=body,
        publish_date=args.publish_date,
        audience=args.audience,
        category=args.category,
        source_url=args.source_url,
        owner=args.owner,
    )
    saved = save_raw_submission(submission)
    print(json.dumps(saved, indent=2))


if __name__ == "__main__":
    main()
