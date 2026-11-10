"""Index local CSV snapshots. Importing this module does not contact any service."""

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from langchain_core.documents import Document

from file_lock import try_lock, unlock


PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_DIR = PROJECT_DIR / "database"
CHROMA_DIR = PROJECT_DIR / "chroma_langchain_db"
EMBEDDING_MODEL = "mxbai-embed-large"
COLLECTION_NAME = "malden_catholic_knowledge_base"
INDEX_VERSION = 2
BATCH_SIZE = 32
CHUNK_SIZE = 1100
CHUNK_OVERLAP = 120

_store = None
_thread_lock = threading.RLock()
_last_error = ""


def csv_files() -> list[Path]:
    if not DATABASE_DIR.is_dir():
        raise FileNotFoundError("The database folder is missing; retaining the saved index.")
    files = sorted(DATABASE_DIR.glob("*.csv"))
    legacy_admission = PROJECT_DIR / "Admission.csv"
    if legacy_admission.exists() and not (DATABASE_DIR / "Admission.csv").exists():
        files.append(legacy_admission)
    if not files:
        raise ValueError("No CSV sources were found; retaining the saved index.")
    return files


def _split_text(text: str) -> list[str]:
    """Bound embedding passages while retaining text around each boundary."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + CHUNK_SIZE // 2, end),
                           text.rfind(" ", start + CHUNK_SIZE // 2, end))
            if boundary > start:
                end = boundary
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def _source_metadata(fields: dict[str, str]) -> dict[str, str]:
    urls = []
    preferred = ("Source of truth", "Outlook link", "Source", "Related link", "Link", "Source URL",
                 "Notes", "Verification & source note", "Public-source notes")
    for key in preferred:
        for url in re.findall(r"https?://[^\s<>\"']+", fields.get(key, "")):
            url = url.rstrip(".,);]")
            if url not in urls:
                urls.append(url)
    received_at = fields.get("Received", "")
    verified_at = fields.get("Verified Date", "")
    if not verified_at:
        verification_text = " ".join(fields.get(key, "") for key in
                                     ("Notes", "Verification & source note", "Public-source notes"))
        verified = re.search(r"\bVerified\s+(\d{4}-\d{2}-\d{2})", verification_text, re.I)
        verified_at = verified.group(1) if verified else ""
    return {
        "url": urls[0] if urls else "",
        "source_url": urls[0] if urls else "",
        "source_urls": json.dumps(urls),
        "source_date": received_at or verified_at,
        "received_at": received_at,
        "verified_at": verified_at,
    }


def load_csv_documents() -> tuple[list[Document], list[str]]:
    """Create stable, source-labelled passages regardless of CSV row order."""
    documents_by_id = {}
    indexed_at = datetime.now(timezone.utc).isoformat()
    for csv_path in csv_files():
        dataframe = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        if not isinstance(dataframe.index, pd.RangeIndex):
            raise ValueError(f"Unexpected row structure in {csv_path.name}; check the CSV columns.")
        source = str(csv_path.relative_to(PROJECT_DIR))
        modified = datetime.fromtimestamp(csv_path.stat().st_mtime, timezone.utc).isoformat()
        for row_index, row in dataframe.iterrows():
            fields = {str(key): str(value).strip() for key, value in row.items() if str(value).strip()}
            if not fields:
                continue
            canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False)
            content_hash = hashlib.sha256(canonical.encode()).hexdigest()
            record_id = next((fields[key] for key in ("Message ID", "Event ID", "Course record ID")
                              if fields.get(key)), content_hash)
            heading = f"Dataset: {csv_path.stem}\n"
            # Subject/name/date remain visible when a long newsletter spans passages.
            for key in ("Subject", "Full name", "Received"):
                if fields.get(key):
                    heading += f"{key}: {fields[key][:120]}\n"
            body = "\n".join(f"{key}: {value}" for key, value in fields.items()
                             if key not in ("Message ID", "Event ID"))
            passages = _split_text(body)
            for chunk_index, passage in enumerate(passages):
                document_id = hashlib.sha256(
                    f"{source}\0{record_id}\0{content_hash}\0{chunk_index}".encode()
                ).hexdigest()
                metadata = {
                    "dataset": csv_path.stem,
                    "source": source,
                    "row": int(row_index) + 2,
                    "record_id": record_id,
                    "content_hash": content_hash,
                    "chunk": chunk_index + 1,
                    "chunks": len(passages),
                    "indexed_at": indexed_at,
                    "source_modified": modified,
                    **_source_metadata(fields),
                }
                documents_by_id[document_id] = Document(
                    id=document_id, page_content=heading + passage, metadata=metadata
                )
    if not documents_by_id:
        raise ValueError("The CSV sources contain no records; retaining the saved index.")
    return list(documents_by_id.values()), list(documents_by_id)


@contextmanager
def _index_lock():
    """Serialize this process and other local index writers."""
    if not _thread_lock.acquire(timeout=5):
        raise TimeoutError("The index is busy. Try again shortly.")
    handle = None
    try:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        handle = os.open(CHROMA_DIR / ".sync.lock", os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + 5
        while True:
            try:
                try_lock(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another process is updating the index. Try again shortly.")
                time.sleep(0.1)
        yield
    finally:
        if handle is not None:
            unlock(handle)
            os.close(handle)
        _thread_lock.release()


def _store_unlocked():
    global _store
    if _store is None:
        from langchain_chroma import Chroma
        from langchain_ollama import OllamaEmbeddings

        _store = Chroma(
            collection_name=COLLECTION_NAME,
            persist_directory=str(CHROMA_DIR),
            embedding_function=OllamaEmbeddings(
                model=EMBEDDING_MODEL, client_kwargs={"timeout": 90}
            ),
        )
    return _store


def get_vector_store():
    """Lazily open the persisted store; no external-source refresh is performed."""
    with _index_lock():
        return _store_unlocked()


def _fingerprint() -> str:
    digest = hashlib.sha256(f"{INDEX_VERSION}:{EMBEDDING_MODEL}".encode())
    for path in csv_files():
        digest.update(str(path.relative_to(PROJECT_DIR)).encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
    return digest.hexdigest()


def _read_manifest() -> dict:
    try:
        data = json.loads((CHROMA_DIR / "sync_manifest.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_manifest(data: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CHROMA_DIR,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream)
        os.replace(temporary, CHROMA_DIR / "sync_manifest.json")
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def sync_vector_store(force: bool = False) -> bool:
    """Index changed passages before removing stale ones; retain old data on failure.

    Updates may add some new passages before a later batch fails. In that case
    old passages remain and the next attempt resumes; this is not a database
    transaction spanning all batches.
    """
    global _last_error
    try:
        fingerprint = _fingerprint()
        with _index_lock():
            store = _store_unlocked()
            manifest = _read_manifest()
            if (not force and manifest.get("fingerprint") == fingerprint
                    and manifest.get("document_count") == store._collection.count()):
                _last_error = ""
                return True
            documents, ids = load_csv_documents()
            if _fingerprint() != fingerprint:
                raise RuntimeError("Source files changed during indexing; retry on the next question.")
            existing = store.get(include=["metadatas"])
            existing_ids = set(existing.get("ids", []))
            existing_metadata = dict(zip(existing.get("ids", []), existing.get("metadatas", [])))
            new_documents = [document for document in documents if document.id not in existing_ids]
            for start in range(0, len(new_documents), BATCH_SIZE):
                batch = new_documents[start:start + BATCH_SIZE]
                # A failed add leaves the existing index and manifest intact.
                store.add_documents(documents=batch, ids=[document.id for document in batch])
            metadata_changes = []
            for document in documents:
                if document.id not in existing_ids:
                    continue
                previous = existing_metadata.get(document.id) or {}
                document.metadata["indexed_at"] = previous.get("indexed_at", document.metadata["indexed_at"])
                if document.metadata != previous:
                    metadata_changes.append(document)
            for start in range(0, len(metadata_changes), BATCH_SIZE):
                batch = metadata_changes[start:start + BATCH_SIZE]
                # Chroma's metadata-only update deliberately avoids embedding
                # unchanged text just because its CSV row number moved.
                store._collection.update(ids=[document.id for document in batch],
                                         metadatas=[document.metadata for document in batch])
            stale_ids = sorted(existing_ids - set(ids))
            for start in range(0, len(stale_ids), BATCH_SIZE):
                store.delete(ids=stale_ids[start:start + BATCH_SIZE])
            _write_manifest({
                "fingerprint": fingerprint,
                "document_count": len(ids),
                "last_success": datetime.now(timezone.utc).isoformat(),
                "version": INDEX_VERSION,
            })
            _last_error = ""
            return True
    except Exception as error:
        _last_error = str(error)
        print(f"Warning: index refresh failed; retaining available saved records ({error})")
        return False


class _CachedRetriever:
    def invoke(self, question: str) -> list[Document]:
        with _index_lock():
            return _store_unlocked().similarity_search(question, k=5)


def get_retriever():
    """Ensure local snapshots are indexed, then retrieve from the available index."""
    sync_vector_store()
    with _index_lock():
        if not _store_unlocked()._collection.count():
            raise RuntimeError(_last_error or "The knowledge index is empty. Check the CSV files and Ollama.")
    return _CachedRetriever()


def refresh_knowledge_base() -> bool:
    """Compatibility entry point: update the index from already-downloaded CSVs."""
    return sync_vector_store()
