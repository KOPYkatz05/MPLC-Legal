"""Read-only inventory for detecting split or stale mission document storage."""

from dataclasses import asdict, dataclass
from pathlib import Path

from config import get_storage_root
from database.db import SessionLocal
from database.models.document import Document
from services.document_storage_service import (
    CLOUD_UNAVAILABLE,
    _matches_document,
    _unique_paths,
    portable_relative_path,
    verify_readable,
)


@dataclass(frozen=True)
class StorageAuditItem:
    document_id: int
    missionary_id: int
    status: str
    recorded_path: str
    canonical_path: str | None
    matches: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


def _candidate_paths(document, roots):
    file_name = Path(document.file_name or "").name
    if not file_name or file_name != document.file_name:
        return []
    candidates = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            candidates.extend(root.rglob(file_name))
        except OSError:
            continue
    return [
        candidate
        for candidate in _unique_paths(candidates)
        if _matches_document(candidate, document)
    ]


def audit_document_storage(*, session_factory=None, roots=None):
    """Return a read-only report; never relink, copy, move, or delete files."""
    canonical_root = Path(get_storage_root())
    search_roots = _unique_paths([canonical_root, *(roots or ())])
    session = (session_factory or SessionLocal)()
    try:
        results = []
        for document in session.query(Document).order_by(Document.id).all():
            recorded = Path(document.file_path or "")
            relative = getattr(document, "storage_relative_path", None)
            if not relative:
                inferred = portable_relative_path(recorded, canonical_root)
                relative = str(inferred) if inferred is not None else None
            canonical = canonical_root / relative if relative else None
            current_error = verify_readable(recorded)
            if current_error is None and canonical and recorded == canonical:
                status = "canonical"
                matches = (str(recorded),)
            elif current_error is None:
                status = "alternate_root"
                matches = (str(recorded),)
            else:
                candidates = _candidate_paths(document, search_roots)
                matches = tuple(str(path) for path in candidates)
                if len(candidates) == 1:
                    status = "recoverable"
                elif len(candidates) > 1:
                    status = "ambiguous"
                elif current_error == CLOUD_UNAVAILABLE:
                    status = CLOUD_UNAVAILABLE
                else:
                    status = "missing"
            results.append(
                StorageAuditItem(
                    document_id=document.id,
                    missionary_id=document.missionary_id,
                    status=status,
                    recorded_path=str(recorded),
                    canonical_path=str(canonical) if canonical else None,
                    matches=matches,
                )
            )
        return results
    finally:
        session.close()
