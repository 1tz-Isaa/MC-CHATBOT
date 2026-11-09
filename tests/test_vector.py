import csv
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import Vector


class FakeCollection:
    def __init__(self, store):
        self.store = store

    def count(self):
        return len(self.store.documents)

    def update(self, ids, metadatas):
        self.store.metadata_updates.extend(ids)
        for document_id, metadata in zip(ids, metadatas):
            self.store.documents[document_id].metadata = metadata.copy()


class FakeStore:
    def __init__(self):
        self.documents = {}
        self.added = []
        self.deleted = []
        self.metadata_updates = []
        self.fail_add = False
        self.operations = []
        self._collection = FakeCollection(self)

    def get(self, include=None):
        return {
            "ids": list(self.documents),
            "metadatas": [document.metadata.copy() for document in self.documents.values()],
        }

    def add_documents(self, documents, ids):
        if self.fail_add:
            raise ConnectionError("Ollama is unavailable")
        self.operations.append("add")
        self.added.extend(ids)
        for document_id, document in zip(ids, documents):
            self.documents[document_id] = document.model_copy(deep=True)

    def delete(self, ids):
        self.operations.append("delete")
        self.deleted.extend(ids)
        for document_id in ids:
            self.documents.pop(document_id, None)

    def similarity_search(self, question, k):
        return list(self.documents.values())[:k]


class VectorSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "database"
        self.database.mkdir()
        self.index = self.root / "index"
        self.store = FakeStore()
        self.patches = patch.multiple(Vector, PROJECT_DIR=self.root, DATABASE_DIR=self.database,
                                     CHROMA_DIR=self.index, _store=self.store, _last_error="")
        self.patches.start()
        self.addCleanup(self.patches.stop)

    def write_csv(self, name, rows):
        with (self.database / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_prepend_email_does_not_reembed_older_messages(self):
        old = [{"Message ID": "a", "Subject": "A", "Content": "Existing announcement A"},
               {"Message ID": "b", "Subject": "B", "Content": "Existing announcement B"}]
        self.write_csv("Outlook News.csv", old)
        self.assertTrue(Vector.sync_vector_store())
        original_ids = set(self.store.documents)
        self.store.added.clear()
        self.write_csv("Outlook News.csv", [
            {"Message ID": "c", "Subject": "C", "Content": "New announcement"}, *old
        ])
        self.assertTrue(Vector.sync_vector_store())
        self.assertEqual(len(self.store.added), 1)
        self.assertTrue(original_ids.issubset(self.store.documents))
        self.assertEqual(self.store.deleted, [])
        rows = {document.metadata["record_id"]: document.metadata["row"]
                for document in self.store.documents.values()}
        self.assertEqual(rows, {"a": 3, "b": 4, "c": 2})

    def test_failed_embeddings_retain_old_records_and_manifest(self):
        self.write_csv("People.csv", [{"Name": "A", "Role": "Teacher"}])
        self.assertTrue(Vector.sync_vector_store())
        original_ids = set(self.store.documents)
        manifest_before = (self.index / "sync_manifest.json").read_text()
        self.write_csv("People.csv", [{"Name": "A", "Role": "Department chair"}])
        self.store.fail_add = True
        with patch("builtins.print"):
            self.assertFalse(Vector.sync_vector_store())
            retriever = Vector.get_retriever()
        self.assertEqual(set(self.store.documents), original_ids)
        self.assertEqual(self.store.deleted, [])
        self.assertEqual((self.index / "sync_manifest.json").read_text(), manifest_before)
        self.assertTrue(retriever.invoke("Who is A?"))

    def test_missing_folder_or_malformed_csv_never_deletes_saved_records(self):
        self.write_csv("People.csv", [{"Name": "A", "Role": "Teacher"}])
        self.assertTrue(Vector.sync_vector_store())
        original_ids = set(self.store.documents)
        manifest_before = (self.index / "sync_manifest.json").read_text()
        with patch.object(Vector, "DATABASE_DIR", self.root / "missing"), patch("builtins.print"):
            self.assertFalse(Vector.sync_vector_store())
        (self.database / "People.csv").write_text('Name,Role\n"unfinished quote', encoding="utf-8")
        with patch("builtins.print"):
            self.assertFalse(Vector.sync_vector_store())
        self.assertEqual(set(self.store.documents), original_ids)
        self.assertEqual(self.store.deleted, [])
        self.assertEqual((self.index / "sync_manifest.json").read_text(), manifest_before)

    def test_unchanged_fingerprint_skips_document_conversion(self):
        self.write_csv("People.csv", [{"Name": "A", "Role": "Teacher"}])
        self.assertTrue(Vector.sync_vector_store())
        with patch.object(Vector, "load_csv_documents", side_effect=AssertionError("unneeded parse")):
            self.assertTrue(Vector.sync_vector_store())

    def test_long_newsletter_preserves_late_text_and_source_context(self):
        content = ("First announcement. " * 200) + "UNIQUE_FINAL_ANNOUNCEMENT"
        self.write_csv("Outlook News.csv", [{
            "Message ID": "mail-a", "Subject": "Daily bulletin", "Received": "2026-11-08T12:00:00Z",
            "Content": content, "Outlook link": "https://outlook.office.com/mail/deeplink/read/test",
        }])
        documents, ids = Vector.load_csv_documents()
        self.assertGreater(len(documents), 1)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(any("UNIQUE_FINAL_ANNOUNCEMENT" in d.page_content for d in documents))
        for document in documents:
            self.assertIn("Subject: Daily bulletin", document.page_content)
            self.assertLessEqual(len(document.page_content), Vector.CHUNK_SIZE + 350)
            self.assertEqual(document.metadata["received_at"], "2026-11-08T12:00:00Z")
            self.assertTrue(document.metadata["source_url"].startswith("https://outlook.office.com/"))

    def test_reordering_general_records_preserves_ids(self):
        rows = [{"Name": "A", "Role": "Teacher"}, {"Name": "B", "Role": "Teacher"}]
        self.write_csv("People.csv", rows)
        _, before = Vector.load_csv_documents()
        self.write_csv("People.csv", rows[::-1])
        _, after = Vector.load_csv_documents()
        self.assertEqual(set(before), set(after))

    def test_deleted_records_removed_after_successful_update(self):
        self.write_csv("People.csv", [{"Name": "A"}, {"Name": "B"}])
        self.assertTrue(Vector.sync_vector_store())
        self.write_csv("People.csv", [{"Name": "B"}, {"Name": "C"}])
        self.assertTrue(Vector.sync_vector_store())
        self.assertEqual(len(self.store.documents), 2)
        self.assertEqual(len(self.store.deleted), 1)
        self.assertFalse(any("Name: A" in d.page_content for d in self.store.documents.values()))

    def test_edit_adds_replacement_before_deleting_old_passage(self):
        self.write_csv("Course Data.csv", [{"Course record ID": "C-1", "Room": "10",
                                           "Verification & source note": "Verified 2026-11-08"}])
        self.assertTrue(Vector.sync_vector_store())
        original_ids = set(self.store.documents)
        self.store.operations.clear()
        self.write_csv("Course Data.csv", [{"Course record ID": "C-1", "Room": "20",
                                           "Verification & source note": "Verified 2026-11-08"}])
        self.assertTrue(Vector.sync_vector_store())
        self.assertEqual(self.store.operations, ["add", "delete"])
        self.assertFalse(original_ids & set(self.store.documents))
        updated = next(iter(self.store.documents.values()))
        self.assertIn("Room: 20", updated.page_content)
        self.assertEqual(updated.metadata["verified_at"], "2026-11-08")


class ImportSafetyTests(unittest.TestCase):
    def test_import_does_not_open_chroma_or_contact_ollama(self):
        with patch("langchain_chroma.Chroma", side_effect=AssertionError("opened Chroma")), \
             patch("langchain_ollama.OllamaEmbeddings", side_effect=AssertionError("opened Ollama")):
            importlib.reload(Vector)
            self.assertIsNone(Vector._store)


if __name__ == "__main__":
    unittest.main()
