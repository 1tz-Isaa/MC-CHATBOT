import calendar
import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import external_data as sports


NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 8, 18, 0, tzinfo=NY)


def event(identifier, day, team="Girls Varsity", sport="Soccer", opponent="Medford High School", hour=16):
    start = datetime(2026, 11, day, hour, 0, tzinfo=NY)
    return {
        "Event ID": identifier, "Event": f"{team} {sport} vs {opponent}",
        "Sport": sport, "Team": team, "Home/Away": "Home", "Opponent": opponent,
        "Date": start.date().isoformat(), "Time": start.strftime("%I:%M %p %Z"),
        "Start": start.isoformat(), "End": start.replace(hour=hour + 1).isoformat(),
        "Status": "Scheduled", "Date status": "Published", "Source": sports.SPORTS_PAGE,
    }


def month_html(year=2026, month=11, items=""):
    days = "".join(
        f'<div class="fsCalendarDate" data-year="{year}" data-month="{month - 1}" data-day="{day}"></div>'
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
    )
    return (
        '<div class="fsCalendar">'
        f'<span class="fsCalendarGridShowMonthPickerButton" data-year="{year}" data-month="{month}"></span>'
        f'<div class="fsCalendarEventGrid">{days}{items}</div></div>'
    )


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv = Path(self.temp.name) / "sports.csv"
        self.status = Path(self.temp.name) / "status.json"
        self.csv_patch = patch.object(sports, "SPORTS_CSV", self.csv)
        self.status_patch = patch.object(sports, "SPORTS_STATUS", self.status)
        self.csv_patch.start()
        self.status_patch.start()
        self.addCleanup(self.csv_patch.stop)
        self.addCleanup(self.status_patch.stop)
        self.rows = [
            event("past", 8, "Boys Junior Varsity", hour=10),
            event("girls-jv", 8, "Girls Junior Varsity", hour=19),
            event("girls-v", 9),
            event("boys-v", 10, "Boys Varsity"),
            event("medford", 13),
            event("somerville", 15, opponent="Somerville High School"),
            event("following-week", 16),
        ]
        self.write_rows(self.rows)

    def write_rows(self, rows):
        with self.csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=sports.FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

    def answer(self, question, **kwargs):
        return sports.calendar_answer_for_question(question, now=NOW, **kwargs)

    def test_general_questions_are_not_calendar_queries(self):
        for question in ["What transportation is available?", "Who is the soccer coach?", "Who can play soccer?", "When are football tryouts?", "What is the class schedule?"]:
            with self.subTest(question=question):
                self.assertIsNone(self.answer(question))

    def test_next_game_honors_gender_and_level(self):
        answer = self.answer("When is the next girls varsity soccer game?")
        self.assertIn("Mon, Nov 09, 2026", answer)
        self.assertIn("Girls Varsity Soccer", answer)
        self.assertNotIn("Junior Varsity", answer)
        self.assertNotIn("Boys", answer)

    def test_next_game_does_not_include_finished_today(self):
        answer = self.answer("When is the next boys soccer game?")
        self.assertIn("Nov 10", answer)
        self.assertNotIn("Nov 08", answer.split("Last successful update:")[0])

    def test_next_week_is_a_range_not_one_game(self):
        answer = self.answer("What soccer games are next week?")
        self.assertEqual(answer.count("\n- ") + answer.startswith("- "), 4)
        self.assertIn("Nov 09", answer)
        self.assertIn("Nov 15", answer)
        self.assertNotIn("Nov 16", answer)

    def test_supported_dates_do_not_widen_results(self):
        for date_text in ["2026-11-15", "Nov. 15, 2026", "November 15th", "11/15/2026", "next Sunday"]:
            with self.subTest(date=date_text):
                answer = self.answer(f"What games are on {date_text}?")
                self.assertIn("Somerville", answer)
                self.assertNotIn("Medford", answer)

    def test_invalid_and_unknown_dates_request_clarification(self):
        self.assertIn("not valid", self.answer("What games are on November 31?"))
        self.assertIn("specify", self.answer("What games are on Christmas?"))

    def test_before_and_after_are_date_boundaries(self):
        after = self.answer("What girls varsity soccer games are after November 15?")
        self.assertIn("Nov 16", after)
        self.assertNotIn("Somerville", after)
        before = self.answer("What girls varsity soccer games are before November 15?")
        self.assertIn("Nov 09", before)
        self.assertIn("Nov 13", before)
        self.assertNotIn("Nov 15", before)
        self.assertNotIn("Nov 16", before)
        inclusive = self.answer("What girls varsity soccer games are on or after November 15?")
        self.assertIn("Nov 15", inclusive)
        self.assertIn("Nov 16", inclusive)

    def test_relative_date_boundaries_and_explicit_ranges(self):
        after = self.answer("What girls varsity soccer games are after next Sunday?")
        self.assertIn("Nov 16", after)
        self.assertNotIn("Nov 15", after)
        between = self.answer("What soccer games are between November 9 and November 13?")
        self.assertIn("Nov 09", between)
        self.assertIn("Nov 13", between)
        self.assertNotIn("Nov 15", between)

    def test_opponent_and_venue_filters(self):
        answer = self.answer("What girls home soccer games against Somerville are next week?")
        self.assertIn("Somerville", answer)
        self.assertNotIn("Medford", answer)
        self.assertIn("No matching", self.answer("What away soccer games are next week?"))

    def test_hockey_filter_never_returns_other_sports(self):
        self.write_rows(self.rows + [event("hockey", 11, sport="Ice Hockey")])
        answer = self.answer("What hockey games are next week?")
        self.assertIn("Ice Hockey", answer)
        self.assertNotIn("Soccer", answer)

    def test_tba_and_unconfirmed_games_are_not_next_timed_game(self):
        tba = event("tba", 8, hour=0)
        tba["Time"] = "TBA"
        undefined = event("undefined", 9, hour=10)
        undefined["Date status"] = "Unconfirmed"
        self.write_rows([tba, undefined] + self.rows)
        answer = self.answer("When is the next girls varsity soccer game?")
        self.assertIn("Nov 09", answer)
        self.assertIn("04:00 PM", answer)
        self.assertIn("unconfirmed", answer)
        self.assertNotIn("10:00 AM", answer)
        today = self.answer("What girls varsity soccer games are today?")
        self.assertIn("TBA", today)
        self.assertNotIn("12:00 AM", today)

    def test_cancellations_do_not_appear_as_scheduled(self):
        self.rows[2]["Status"] = "Cancelled"
        self.write_rows(self.rows)
        answer = self.answer("When is the next girls varsity soccer game?")
        self.assertIn("Nov 13", answer)

    def test_source_freshness_and_truncation_are_visible(self):
        answer = self.answer("What soccer games are next week?", limit=2)
        self.assertIn("Showing 2 of 4", answer)
        self.assertIn("Last successful update:", answer)
        self.assertIn(sports.SPORTS_PAGE, answer)

    def test_dates_outside_saved_coverage_are_explicit(self):
        self.status.write_text(json.dumps({"coverage_start": "2026-11-01", "coverage_end": "2026-11-30"}))
        answer = self.answer("What soccer games are on December 1?")
        self.assertIn("outside the saved calendar coverage", answer)
        self.assertIn("does not confirm that no games are scheduled", answer)
        inside = self.answer("What soccer games are next week?")
        self.assertNotIn("outside the saved calendar coverage", inside)
        partial = self.answer("What soccer games are from November 15 to December 1?")
        self.assertIn("Nov 15", partial)
        self.assertIn("outside the saved calendar coverage", partial)

    def test_missing_cache_is_not_no_games(self):
        self.csv.unlink()
        self.assertIn("unavailable", self.answer("What games are today?"))
        status = sports.sports_sync_status()
        self.assertEqual(status["status"], "unavailable")
        self.assertIsNone(status["last_success"])
        self.assertTrue(status["message"])

    def test_valid_empty_month_is_accepted(self):
        self.assertEqual(sports._parse_events(month_html(), NOW), [])

    def test_published_event_codes_and_tba_are_parsed(self):
        for code, sport in sports.SPORT_CODES.items():
            with self.subTest(code=code):
                html = month_html(items=(
                    '<div class="fsCalendarInfo">'
                    f'<span class="fsCalendarEventTitle" data-occur-id="event-1">'
                    f'Time: TBA - Malden Catholic {code} G JV Home Medford High School</span>'
                    '<time class="fsStartTime" datetime="2026-11-15T00:00:00-05:00"></time>'
                    '</div>'
                ))
                parsed = sports._parse_events(html, NOW)[0]
                self.assertEqual(parsed["Sport"], sport)
                self.assertEqual(parsed["Team"], "Girls Junior Varsity")
                self.assertEqual(parsed["Time"], "TBA")
                self.assertEqual(parsed["Date"], "2026-11-15")

    def test_bad_response_and_wrong_month_are_rejected(self):
        for html in ["<html>Temporarily unavailable</html>", month_html(month=12), month_html().replace('data-day="15"', 'data-day="16"')]:
            with self.subTest(html=html[:30]):
                with self.assertRaises(ValueError):
                    sports._parse_events(html, NOW)

    def test_bad_response_keeps_last_good_cache(self):
        original = self.csv.read_bytes()
        with patch.object(sports, "SPORTS_MONTHS_AHEAD", 0), patch.object(sports, "_fetch_month", return_value="<html>Service unavailable</html>"):
            self.assertFalse(sports.sync_sports_calendar(force=True))
        self.assertEqual(self.csv.read_bytes(), original)
        self.assertEqual(sports.sports_sync_status()["status"], "error")

    def test_time_zone_is_school_local(self):
        from datetime import timezone
        utc_now = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)  # Nov 8, 8 PM in NY.
        answer = sports.calendar_answer_for_question("What games are today?", now=utc_now)
        self.assertIn("Nov 08", answer)
        self.assertNotIn("Nov 09", answer)


if __name__ == "__main__":
    unittest.main()
