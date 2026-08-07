"""Authoritative document-file availability and folder relocation helpers."""

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess

from database.db import SessionLocal
from database.models.document import Document
from database.models.missionary import Missionary
from utils.logger import logger


MISSING = "missing"
CLOUD_UNAVAILABLE = "cloud_unavailable"
UNREADABLE = "unreadable"
AMBIGUOUS = "ambiguous"


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


def resolve_document_path(document_id, *, session_factory=None):
    """Return a readable path, repairing one uniquely relocated file if possible."""
    session = (session_factory or SessionLocal)()
    try:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentStorageError(MISSING, document_id)

        current = Path(document.file_path or "")
        current_error = verify_readable(current)
        if current_error is None:
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
                matches = [
                    candidate
                    for candidate in root.rglob(safe_file_name)
                    if _is_within(candidate, root)
                    and candidate.is_file()
                    and verify_readable(candidate) is None
                ]
            except OSError as error:
                logger.warning(
                    "Document recovery search failed for %s: %s", document_id, error
                )
                if _storage_error_code(error) == CLOUD_UNAVAILABLE:
                    raise DocumentStorageError(CLOUD_UNAVAILABLE, document_id) from error

        if len(matches) == 1:
            document.file_path = str(matches[0])
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
