"""Original-PDF preservation -- the system of record.

docs/07_non_functional_requirements.md requires uploaded source PDFs to
be kept as-is, separate from the parsed database rows. Files are stored
content-addressed (`<UPLOAD_DIR>/<sha256[:2]>/<sha256>.pdf`), so
re-uploading an identical file reuses the existing copy and row instead
of piling up duplicates, and a stored file is never overwritten or
deleted by the app (retention is indefinite, per the same doc).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import SourceDocument


def upload_dir() -> Path:
    # Read per call, not at import, so tests can point it at a temp dir.
    return Path(os.environ.get("UPLOAD_DIR", "data/uploads"))


def save_source_document(db: Session, filename: str | None, data: bytes) -> SourceDocument:
    """Write `data` to disk (if not already there) and return its
    SourceDocument row, flushed but not committed -- the caller commits
    it together with the ingestion it belongs to.

    If that transaction later rolls back, the file stays on disk with no
    row pointing at it. That's harmless (content-addressed, so the next
    successful upload of the same bytes just reuses it) and preferable
    to ever losing an original.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    relative_path = f"{sha256[:2]}/{sha256}.pdf"

    path = upload_dir() / relative_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic: no half-written file under the final name

    document = db.query(SourceDocument).filter_by(sha256=sha256).one_or_none()
    if document is None:
        document = SourceDocument(
            original_filename=filename,
            sha256=sha256,
            stored_path=relative_path,
            size_bytes=len(data),
        )
        db.add(document)
        db.flush()
    return document


def source_document_path(document: SourceDocument) -> Path:
    return upload_dir() / document.stored_path
