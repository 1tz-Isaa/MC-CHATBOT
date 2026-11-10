import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document

import web


def ask(question: str) -> list[dict]:
    # Not used as a context manager, so the background refresh never starts.
    response = TestClient(web.app).post("/api/chat", json={"question": question})
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line]


class WebChatTests(unittest.TestCase):
    def test_calendar_skips_models_and_retriever(self):
        with patch.object(web.chatbot, "calendar_answer_for_question", return_value="Girls varsity soccer at 4 PM."), \
             patch("Vector.get_retriever") as retrieve, patch.object(web, "_get_chain") as chain:
            events = ask("When is the next girls varsity soccer game?")
        retrieve.assert_not_called()
        chain.assert_not_called()
        self.assertEqual(events, [
            {"type": "token", "text": "Girls varsity soccer at 4 PM."},
            {"type": "done"},
        ])

    def test_general_answer_streams_tokens_then_sources(self):
        docs = [Document(page_content="Windows 11 laptops are required.", metadata={
            "source": "database/Q&A.csv", "dataset": "Q&A", "row": 2,
            "source_url": "https://www.maldencatholic.org/admissions/mc-faq",
            "verified_at": "2026-08-23",
        })]
        retriever = Mock()
        retriever.invoke.return_value = docs
        chain = Mock()
        chain.stream.return_value = iter([
            SimpleNamespace(content="Windows 11"), SimpleNamespace(content=" is required. [1]"),
        ])
        with patch.object(web.chatbot, "calendar_answer_for_question", return_value=None), \
             patch("Vector.get_retriever", return_value=retriever), \
             patch.object(web, "_get_chain", return_value=chain):
            events = ask("What laptop is required?")
        answer = "".join(event["text"] for event in events if event["type"] == "token")
        self.assertEqual(answer, "Windows 11 is required. [1]")
        self.assertIn("[1] Source: database/Q&A.csv", chain.stream.call_args.args[0]["data"])
        self.assertEqual(events[-2], {"type": "sources", "sources": [{
            "number": 1, "source": "database/Q&A.csv", "row": 2,
            "url": "https://www.maldencatholic.org/admissions/mc-faq",
            "notes": ["source verified: 2026-08-23"],
        }]})
        self.assertEqual(events[-1], {"type": "done"})

    def test_local_file_paths_are_not_sent_to_the_browser(self):
        retriever = Mock()
        retriever.invoke.return_value = [Document(page_content="Room 101", metadata={"source": "database/Rooms.csv"})]
        chain = Mock()
        chain.stream.return_value = iter([SimpleNamespace(content="Room 101 [1]")])
        with patch.object(web.chatbot, "calendar_answer_for_question", return_value=None), \
             patch("Vector.get_retriever", return_value=retriever), \
             patch.object(web, "_get_chain", return_value=chain):
            events = ask("Where is room 101?")
        self.assertNotIn("path", events[-2]["sources"][0])
        self.assertNotIn(str(web.chatbot.PROJECT_DIR), json.dumps(events))

    def test_model_failure_becomes_an_error_event(self):
        with patch.object(web.chatbot, "calendar_answer_for_question", return_value=None), \
             patch("Vector.get_retriever", side_effect=ConnectionError("secret detail")):
            events = ask("Question")
        self.assertEqual([event["type"] for event in events], ["status", "error", "done"])
        self.assertIn("Check that Ollama is running", events[1]["text"])
        self.assertNotIn("secret detail", events[1]["text"])

    def test_empty_question_is_rejected(self):
        response = TestClient(web.app).post("/api/chat", json={"question": ""})
        self.assertEqual(response.status_code, 422)


class WebPageTests(unittest.TestCase):
    def test_page_and_assets_are_served(self):
        client = TestClient(web.app)
        self.assertIn("Ask MC", client.get("/").text)
        self.assertEqual(client.get("/static/app.js").status_code, 200)
        self.assertEqual(client.get("/static/styles.css").status_code, 200)

    def test_status_reports_each_source(self):
        fake = {"sports": {"status": "ready", "message": "Current.", "last_success": "2026-11-01T08:00:00-04:00",
                           "coverage_start": "2026-11-01"},
                "outlook": {"status": "config_missing", "message": "Not configured.", "last_success": None}}
        with patch.object(web, "source_status", return_value=fake):
            data = TestClient(web.app).get("/api/status").json()
        self.assertEqual(data["sports"], {
            "status": "ready", "message": "Current.", "last_success": "2026-11-01T08:00:00-04:00",
        })
        self.assertEqual(data["outlook"]["status"], "config_missing")


if __name__ == "__main__":
    unittest.main()
