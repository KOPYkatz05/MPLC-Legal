"""Authoritative document-file availability and folder relocation helpers."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import os
import shutil
import subprocess

from database.db import SessionLocal
from database.models.document import Document
from database.models.missionary import Missionary
from config import (
    ACTIVE_FOLDER_NAME,
    ARCHIVE_FOLDER_NAME,
    TRASH_FOLDER_NAME,
    get_storage_root,
)
from utils.logger import logger


MISSING = "missing"
CLOUD_UNAVAILABLE = "cloud_unavailable"
UNREADABLE = "unreadable"
AMBIGUOUS = "ambiguous"
ROOT_MISMATCH = "root_mismatch"

STORAGE_ANCHORS = {
    ACTIVE_FOLDER_NAME.casefold(),
    ARCHIVE_FOLDER_NAME.casefold(),
    TRASH_FOLDER_NAME.casefold(),
}


class DocumentStorageError(OSError):
    def __init__(self, code, document_id):
        super().__init__(f"Document {document_id} storage error: {code}")
        self.code = code
        self.document_id = document_id


@dataclass(frozen=True)
class FolderMove:
    source: Path
    destination: Path

    def rollback(self):
        if self.destination.exists() and not self.source.exists():
            self.source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self.destination), str(self.source))


def _storage_error_code(error):
    winerror = getattr(error, "winerror", None)
    text = str(error).lower()
    if winerror in {362, 395, 396, 405, 406, 407} or any(
        marker in text
        for marker in ("cloud file", "cloud provider", "onedrive", "no longer available")
    ):
        return CLOUD_UNAVAILABLE
    if isinstance(error, (FileNotFoundError, NotADirectoryError)):
        return MISSING
    return UNREADABLE


def verify_readable(path):
    path = Path(path)
    try:
        if not path.is_file():
            return MISSING
        with path.open("rb") as handle:
            handle.read(1)
        return None
    except OSError as error:
        return _storage_error_code(error)


def _is_within(candidate, root):
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def portable_relative_path(path, root=None):
    """Return a safe storage-root-relative path for canonical or legacy roots."""
    path = Path(path)
    root = Path(root or get_storage_root())
    try:
        relative = path.relative_to(root)
    except (TypeError, ValueError):
        relative = None
    if relative is None:
        parts = path.parts
        anchor_index = next(
            (index for index, part in enumerate(parts) if part.casefold() in STORAGE_ANCHORS),
            None,
        )
        if anchor_index is None:
            return None
        relative = Path(*parts[anchor_index:])
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return relative


def canonical_storage_path(relative_path, root=None):
    relative = Path(relative_path or "")
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        return None
    root = Path(root or get_storage_root())
    candidate = root / relative
    return candidate if _is_within(candidate, root) else None


def resolve_missionary_write_folder(missionary):
    """Choose the canonical folder, refusing to create a second split-root tree."""
    recorded = Path(getattr(missionary, "folder_path", "") or "")
    relative = getattr(missionary, "folder_relative_path", None)
    if not relative:
        inferred = portable_relative_path(recorded)
        relative = str(inferred) if inferred is not None else None
    canonical = canonical_storage_path(relative)
    if canonical is None:
        return recorded
    if recorded != canonical and recorded.exists() and not canonical.exists():
        raise DocumentStorageError(ROOT_MISMATCH, getattr(missionary, "id", None))
    missionary.folder_relative_path = str(relative)
    missionary.folder_path = str(canonical)
    return canonical


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches_document(candidate, document):
    if verify_readable(candidate) is not None:
        return False
    try:
        expected_size = getattr(document, "file_size", None)
        if expected_size is not None and Path(candidate).stat().st_size != int(expected_size):
            return False
        expected_hash = str(getattr(document, "content_sha256", "") or "").lower()
        return not expected_hash or _sha256(candidate) == expected_hash
    except (OSError, TypeError, ValueError):
        return False


def _unique_paths(paths):
    unique = {}
    for path in paths:
        if path is None:
            continue
        candidate = Path(path)
        unique.setdefault(os.path.normcase(str(candidate)), candidate)
    return list(unique.values())


def resolve_document_path(document_id, *, session_factory=None):
    """Return a readable path, repairing one uniquely relocated file if possible."""
    session = (session_factory or SessionLocal)()
    try:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentStorageError(MISSING, document_id)

        current = Path(document.file_path or "")
        current_error = verify_readable(current)
        relative = getattr(document, "storage_relative_path", None)
        if not relative:
            inferred = portable_relative_path(current)
            relative = str(inferred) if inferred is not None else None
        canonical = canonical_storage_path(relative)
        if canonical is not None and _matches_document(canonical, document):
            document.file_path = str(canonical)
            document.storage_relative_path = str(relative)
            session.commit()
            return canonical
        if current_error is None and _matches_document(current, document):
            if relative:
                document.storage_relative_path = str(relative)
                session.commit()
            return current

        missionary = session.get(Missionary, document.missionary_id)
        root = Path(missionary.folder_path) if missionary and missionary.folder_path else None
        matches = []
        safe_file_name = Path(document.file_name or "").name
        if (
            root
            and root.is_dir()
            and safe_file_name
            and safe_file_name == document.file_name
        ):
            try:
                matches.extend([
                    candidate
                    for candidate in root.rglob(safe_file_name)
                    if _is_within(candidate, root)
                    and candidate.is_file()
                    and verify_readable(candidate) is None
                ])
            except OSError as error:
                logger.warning(
                    "Document recovery search failed for %s: %s", document_id, error
                )
                if _storage_error_code(error) == CLOUD_UNAVAILABLE:
                    raise DocumentStorageError(CLOUD_UNAVAILABLE, document_id) from error

        canonical_root = Path(get_storage_root())
        has_immutable_identity = bool(getattr(document, "content_sha256", None))
        if canonical_root.is_dir() and safe_file_name and has_immutable_identity:
            try:
                matches.extend(canonical_root.rglob(safe_file_name))
            except OSError as error:
                logger.warning("Canonical document recovery search failed: %s", error)
        matches = [
            candidate
            for candidate in _unique_paths(matches)
            if _matches_document(candidate, document)
        ]
        if len(matches) == 1:
            document.file_path = str(matches[0])
            repaired_relative = portable_relative_path(matches[0], canonical_root)
            if repaired_relative is not None:
                document.storage_relative_path = str(repaired_relative)
            session.commit()
            logger.info("Repaired storage path for document %s", document_id)
            return matches[0]
        if len(matches) > 1:
            logger.warning("Document %s has %s ambiguous recovery matches", document_id, len(matches))
            raise DocumentStorageError(AMBIGUOUS, document_id)

        logger.warning("Document %s remains unavailable (%s)", document_id, current_error)
        raise DocumentStorageError(current_error, document_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def rewrite_document_paths(session, missionary_id, source_root, destination_root):
    source_root = Path(source_root)
    destination_root = Path(destination_root)
    changed = 0
    for document in session.query(Document).filter_by(missionary_id=missionary_id).all():
        try:
            relative = Path(document.file_path).relative_to(source_root)
        except (TypeError, ValueError):
            continue
        document.file_path = str(destination_root / relative)
        storage_relative = portable_relative_path(document.file_path)
        if storage_relative is not None:
            document.storage_relative_path = str(storage_relative)
        changed += 1
    return changed


def move_folder_and_rewrite_paths(session, missionary, move_callable):
    source = Path(missionary.folder_path)
    destination_value = move_callable(str(source))
    destination = Path(destination_value)
    folder_move = FolderMove(source, destination)
    try:
        rewrite_document_paths(session, missionary.id, source, destination)
        missionary.folder_path = str(destination_value)
        relative = portable_relative_path(destination)
        missionary.folder_relative_path = str(relative) if relative is not None else None
        return folder_move
    except Exception:
        rollback_folder_move(folder_move)
        raise


def commit_with_folder_rollback(session, folder_move=None):
    try:
        session.commit()
    except Exception:
        session.rollback()
        rollback_folder_move(folder_move)
        raise


def rollback_folder_move(folder_move):
    if folder_move is None:
        return
    try:
        folder_move.rollback()
    except Exception:
        logger.exception(
            "Database operation and compensating document-folder move both failed"
        )


def pin_onedrive_file(path):
    """Best-effort Windows request to retain a OneDrive-backed file locally."""
    path = Path(path)
    if os.name != "nt" or "onedrive" not in str(path).lower():
        return
    try:
        subprocess.run(
            ["attrib.exe", "+P", "-U", str(path)],
            check=True,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError):
        logger.warning("Could not pin uploaded document for offline availability")
