import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import outlook_news as news


class OutlookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = {
            "client_id": "test-client",
            "tenant_id": "organizations",
            "folder": "MC News",
            "account": "",
            "lookback_days": 90,
            "refresh_hours": 1,
        }
        patches = {
            "PRIVATE_DIR": self.root / ".private",
            "TOKEN_CACHE": self.root / ".private" / "token.json",
            "STATUS_FILE": self.root / ".private" / "status.json",
            "NEWS_CSV": self.root / "database" / "Outlook News.csv",
            "_last_status": None,
        }
        self.addCleanup(patch.stopall)
        patch.multiple(news, **patches).start()
        patch.object(news, "_settings", return_value=self.settings).start()
        patch.object(news, "_now", return_value=datetime(2026, 11, 8, 12, tzinfo=timezone.utc)).start()
        # No unit test may reach the real Microsoft endpoints.
        self.network = patch.object(news.requests, "get", side_effect=AssertionError("Unexpected network call")).start()

    def seed_news(self):
        news._write_news([{
            "Message ID": "old-id", "Subject": "Old news", "Sender name": "School",
            "Sender email": "news@example.org", "Received": "2026-11-07T12:00:00Z",
            "Content": "Keep this cached news", "Outlook link": "https://outlook.example/message",
        }])
        news._record_status("ready", "Updated", success=True)
        return news.NEWS_CSV.read_bytes(), news.outlook_status()["last_success"]

    def test_auth_network_failure_preserves_news_and_reports_failure(self):
        before, last_success = self.seed_news()
        with patch.object(news, "_get_access_token", side_effect=requests.ConnectionError("Bearer secret-value")):
            self.assertFalse(news.sync_outlook_news(force=True))
        state = news.outlook_status()
        self.assertEqual(news.NEWS_CSV.read_bytes(), before)
        self.assertEqual(state["last_success"], last_success)
        self.assertEqual(state["status"], "error")
        self.assertNotIn("secret-value", json.dumps(state))

    def test_missing_token_is_visible_and_keeps_news(self):
        before, _ = self.seed_news()
        with patch.object(news, "_get_access_token", return_value=None):
            self.assertFalse(news.sync_outlook_news(force=True))
        self.assertEqual(news.outlook_status()["status"], "needs_sign_in")
        self.assertIn("--login", news.outlook_status()["message"])
        self.assertEqual(news.NEWS_CSV.read_bytes(), before)

    def test_bad_settings_never_escape_sync(self):
        with patch.object(news, "_settings", side_effect=ValueError("invalid refresh value")):
            self.assertFalse(news.sync_outlook_news(force=True))
            self.assertEqual(news.outlook_status()["status"], "error")

    def test_unconfigured_account_does_not_start_auth(self):
        self.settings["client_id"] = ""
        with patch.object(news, "_get_access_token") as auth:
            self.assertFalse(news.sync_outlook_news(force=True))
            auth.assert_not_called()
        self.assertEqual(news.outlook_status()["status"], "config_missing")

    def test_multiple_accounts_require_explicit_selection(self):
        app = Mock()
        app.get_accounts.return_value = [{"username": "one@example.org"}, {"username": "two@example.org"}]
        with patch.object(news.msal, "PublicClientApplication", return_value=app):
            with self.assertRaises(news.OutlookSyncError) as error:
                news._get_access_token(interactive=False)
        self.assertEqual(error.exception.status, "needs_sign_in")
        app.acquire_token_silent.assert_not_called()
        app.initiate_device_flow.assert_not_called()

    def test_account_selection_uses_the_configured_account(self):
        self.settings["account"] = "two@example.org"
        app = Mock()
        accounts = [{"username": "one@example.org"}, {"username": "two@example.org"}]
        app.get_accounts.return_value = accounts
        app.acquire_token_silent.return_value = {"access_token": "token"}
        with patch.object(news.msal, "PublicClientApplication", return_value=app):
            self.assertEqual(news._get_access_token(interactive=False), "token")
        app.acquire_token_silent.assert_called_once_with(news.SCOPES, account=accounts[1])

    def test_folder_lookup_follows_all_pages(self):
        next_url = news.GRAPH_ROOT + "/me/mailFolders?$skip=100"
        with patch.object(news, "_graph_get", side_effect=[
            {"value": [{"id": "first", "displayName": "Inbox"}], "@odata.nextLink": next_url},
            {"value": [{"id": "news-folder", "displayName": "MC News"}]},
        ]) as graph:
            self.assertEqual(news._find_folder("token", "MC News"), "news-folder")
        self.assertEqual(graph.call_count, 2)
        self.assertEqual(graph.call_args.args[0], next_url)

    def test_untrusted_paging_url_is_rejected_before_auth_request(self):
        with patch.object(news, "_graph_get", return_value={"value": [], "@odata.nextLink": "https://example.org/leak"}) as graph:
            with self.assertRaises(news.OutlookSyncError):
                news._find_folder("secret-token", "MC News")
        self.assertEqual(graph.call_count, 1)
        self.network.assert_not_called()

    def test_graph_requests_use_immutable_ids_and_do_not_follow_redirects(self):
        response = Mock(status_code=200)
        response.json.return_value = {"value": []}
        with patch.object(news.requests, "get", return_value=response) as get:
            news._graph_get(news.GRAPH_ROOT + "/me/mailFolders", "token")
        self.assertIn('IdType="ImmutableId"', get.call_args.kwargs["headers"]["Prefer"])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_repeated_page_fails_instead_of_looping(self):
        url = news.GRAPH_ROOT + "/me/mailFolders"
        with patch.object(news, "_graph_get", return_value={"value": [], "@odata.nextLink": url}):
            with self.assertRaises(news.OutlookSyncError):
                list(news._pages(url, "token", {}))

    def test_html_keeps_links_and_paragraphs_but_not_tracking_images(self):
        clean = news._clean_body({"body": {"contentType": "html", "content": (
            '<p>Register <a href="https://school.example/signup">here</a>.</p>'
            '<p>Meet Monday.<br>Bring a laptop.</p>'
            '<script>hidden code</script><img src="https://tracking.example/pixel">'
        )}})
        self.assertIn("here (https://school.example/signup)", clean)
        self.assertIn("\n", clean)
        self.assertIn("Meet Monday.", clean)
        self.assertNotIn("tracking.example", clean)
        self.assertNotIn("hidden code", clean)

    def test_incomplete_payload_never_overwrites_cached_news(self):
        before, _ = self.seed_news()
        with patch.object(news, "_get_access_token", return_value="token"), patch.object(news, "_find_folder", return_value="folder"), patch.object(news, "_graph_get", return_value={}):
            self.assertFalse(news.sync_outlook_news(force=True))
        self.assertEqual(news.NEWS_CSV.read_bytes(), before)
        self.assertEqual(news.outlook_status()["status"], "error")

    def test_failed_atomic_token_replace_preserves_old_token(self):
        news._atomic_text(news.TOKEN_CACHE, "original", private=True)
        with patch.object(news.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                news._atomic_text(news.TOKEN_CACHE, "replacement", private=True)
        self.assertEqual(news.TOKEN_CACHE.read_text(), "original")
        if os.name != "nt":  # Windows has no owner-only permission bits to check
            self.assertEqual(stat.S_IMODE(news.TOKEN_CACHE.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(news.PRIVATE_DIR.stat().st_mode), 0o700)

    def test_successful_empty_folder_is_valid_and_updates_status(self):
        self.seed_news()
        with patch.object(news, "_get_access_token", return_value="token"), patch.object(news, "_find_folder", return_value="folder"), patch.object(news, "_fetch_messages", return_value=[]):
            self.assertTrue(news.sync_outlook_news(force=True))
        self.assertEqual(news.outlook_status()["status"], "ready")
        self.assertIn("0 messages", news._stored_status()["message"])
        self.assertNotIn("old-id", news.NEWS_CSV.read_text())

    def test_unchanged_refresh_reports_no_change_and_preserves_file(self):
        news._write_news([])
        modified = news.NEWS_CSV.stat().st_mtime_ns
        with patch.object(news, "_get_access_token", return_value="token"), patch.object(news, "_find_folder", return_value="folder"), patch.object(news, "_fetch_messages", return_value=[]):
            self.assertFalse(news.sync_outlook_news(force=True))
        self.assertEqual(news.NEWS_CSV.stat().st_mtime_ns, modified)
        self.assertEqual(news.outlook_status()["status"], "ready")
        self.assertEqual(news.outlook_status()["last_success"], news._now().isoformat())

    def test_status_save_failure_does_not_hide_sync_error(self):
        before, last_success = self.seed_news()
        with patch.object(news, "_atomic_text", side_effect=OSError("disk error")), patch.object(news, "_get_access_token", return_value=None):
            self.assertFalse(news.sync_outlook_news(force=True))
        self.assertEqual(news.outlook_status()["status"], "needs_sign_in")
        self.assertEqual(news.outlook_status()["last_success"], last_success)
        self.assertEqual(news.NEWS_CSV.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
