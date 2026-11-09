import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document

import main


class ChatTests(unittest.TestCase):
    def test_calendar_skips_models_and_retriever(self):
        with patch.object(main, "calendar_answer_for_question", return_value="Girls varsity soccer at 4 PM."), \
             patch("Vector.get_retriever") as retrieve, patch.object(main, "build_chain") as build, \
             redirect_stdout(io.StringIO()) as output:
            main.answer_question("When is the next girls varsity soccer game?")
        retrieve.assert_not_called()
        build.assert_not_called()
        self.assertIn("4 PM", output.getvalue())

    def test_general_answer_streams_numbered_sources(self):
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
        with patch.object(main, "calendar_answer_for_question", return_value=None), \
             patch("Vector.get_retriever", return_value=retriever), redirect_stdout(io.StringIO()) as output:
            main.answer_question("What laptop is required?", chain)
        result = output.getvalue()
        self.assertIn("Windows 11 is required. [1]", result)
        self.assertIn("https://www.maldencatholic.org/admissions/mc-faq", result)
        self.assertIn("source verified: 2026-08-23", result)
        self.assertIn("[1] Source: database/Q&A.csv", chain.stream.call_args.args[0]["data"])

    def test_record_budget_keeps_source_numbers_aligned(self):
        docs = [Document(page_content="a" * 7000, metadata={"source": "database/A.csv"}),
                Document(page_content="b" * 7000, metadata={"source": "database/B.csv"})]
        context, references = main.format_records(docs)
        self.assertIn("[1]", context)
        self.assertNotIn("[2]", context)
        self.assertNotIn("B.csv", references)

    def test_cancelled_answer_returns_to_prompt(self):
        with patch("sys.argv", ["main.py", "--no-sync"]), \
             patch.object(main, "print_status"), \
             patch("builtins.input", side_effect=["Question", "q"]), \
             patch.object(main, "answer_question", side_effect=KeyboardInterrupt), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main.main(), 0)
        self.assertIn("Answer cancelled", output.getvalue())

    def test_model_failure_returns_to_prompt(self):
        with patch("sys.argv", ["main.py", "--no-sync"]), \
             patch.object(main, "print_status"), \
             patch("builtins.input", side_effect=["Question", "q"]), \
             patch.object(main, "answer_question", side_effect=ConnectionError), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main.main(), 0)
        self.assertIn("Check that Ollama is running", output.getvalue())


if __name__ == "__main__":
    unittest.main()
