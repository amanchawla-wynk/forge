"""Local, in-memory document storage for the dashboard's lifetime.

Uploaded PRDs are written to a private temp directory addressed by an opaque
id. Nothing here is a database: restarting the backend process forgets every
document, matching Forge's stateless design (D-014). This module owns no LLM
credentials.
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from forge.ingest.document import SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class StoredDocument:
    document_id: str
    filename: str
    path: Path


class DocumentStore:
    """Maps opaque document ids to local file paths for one process lifetime."""

    def __init__(self) -> None:
        self._root = Path(tempfile.mkdtemp(prefix="forge-dashboard-"))
        self._documents: dict[str, StoredDocument] = {}
        self._lock = Lock()

    def save(self, filename: str, content: bytes) -> StoredDocument:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(f"unsupported document type {suffix!r}; use {supported}")
        document_id = uuid.uuid4().hex
        path = self._root / f"{document_id}{suffix}"
        path.write_bytes(content)
        stored = StoredDocument(document_id=document_id, filename=filename, path=path)
        with self._lock:
            self._documents[document_id] = stored
        return stored

    def get(self, document_id: str) -> StoredDocument:
        with self._lock:
            stored = self._documents.get(document_id)
        if stored is None:
            raise KeyError(f"unknown document_id {document_id!r}")
        return stored
