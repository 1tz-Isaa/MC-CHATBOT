import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_data
from file_lock import try_lock


class SyncTests(unittest.TestCase):
    def test_one_source_failing_does_not_skip_the_other(self):
        statuses = {
            "sports": {"status": "error", "last_success": None, "message": "Fetch failed"},
            "outlook": {"status": "ready", "last_success": "2026-11-08", "message": "Ready"},
        }
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(sync_data, "PRIVATE_DIR", Path(folder)), \
             patch.object(sync_data, "sync_sports_calendar", side_effect=OSError), \
             patch.object(sync_data, "sync_outlook_news", return_value=True) as outlook, \
             patch.object(sync_data, "source_status", return_value=statuses):
            result = sync_data.run_sync()
        outlook.assert_called_once()
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["sources"]["outlook"]["changed"])

    def test_default_refresh_does_not_require_ollama(self):
        statuses = {name: {"status": "ready", "last_success": "2026-11-08", "message": "Ready"}
                    for name in ("sports", "outlook")}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(sync_data, "PRIVATE_DIR", Path(folder)), \
             patch.object(sync_data, "sync_sports_calendar", return_value=False), \
             patch.object(sync_data, "sync_outlook_news", return_value=False), \
             patch.object(sync_data, "source_status", return_value=statuses), \
             patch("Vector.sync_vector_store") as index:
            result = sync_data.run_sync()
        self.assertEqual(result["status"], "ready")
        index.assert_not_called()

    def test_overlapping_sync_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(sync_data, "PRIVATE_DIR", Path(folder)), \
             patch.object(sync_data, "sync_sports_calendar") as sports:
            with (Path(folder) / "source_sync.lock").open("a") as lock:
                try_lock(lock)
                result = sync_data.run_sync()
            self.assertEqual(result["status"], "busy")
            sports.assert_not_called()

    def test_index_failure_still_reports_source_results(self):
        statuses = {name: {"status": "ready", "last_success": "2026-11-08", "message": "Ready"}
                    for name in ("sports", "outlook")}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(sync_data, "PRIVATE_DIR", Path(folder)), \
             patch.object(sync_data, "sync_sports_calendar", return_value=True), \
             patch.object(sync_data, "sync_outlook_news", return_value=False), \
             patch.object(sync_data, "source_status", return_value=statuses), \
             patch("Vector.sync_vector_store", side_effect=ConnectionError):
            result = sync_data.run_sync(index=True)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["sources"]["sports"]["status"], "ready")
        self.assertTrue(result["sources"]["sports"]["changed"])
        self.assertEqual(result["sources"]["index"]["error"], "ConnectionError")


if __name__ == "__main__":
    unittest.main()
