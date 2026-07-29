import json
import hashlib
import shutil
import time

from pathlib import Path
from database.runtime import get_client_data_dir

from database.db import SessionLocal
from services.api_client import ApiUnavailableError, MissionLegalApiClient
from services.remote_service import RemoteServiceMixin

from database.models.document import (
    Document,
)

from utils.logger import logger

from services.workflow_validator import (
    WorkflowValidator,
)


class DocumentFileUnavailableError(FileNotFoundError):
    """The document record exists but its file is unavailable on the server."""

    def __init__(self, document_id):
        super().__init__(f"Document file {document_id} is unavailable on the server.")
        self.document_id = document_id


class DocumentService(RemoteServiceMixin):
    REMOTE_SERVICE = "documents"
    REMOTE_METHODS = frozenset({
        "document_type_exists",
        "delete_document_by_type",
        "delete_document_by_id",
        "update_document_notes",
    })
    def __init__(self):
        self.api_client = MissionLegalApiClient.from_environment()
        if self.api_client is not None:
            self.onedrive_service = None
            return
        self.workflow_validator = (
            WorkflowValidator()
        )

    def upload_document(
        self,
        missionary,
        source_file,
        document_type,
        workflow_stage,
        ocr_raw_data=None,
        ocr_confirmed_data=None,
        notes=None,
    ):
        if self.api_client is not None:
            payload = self.api_client.upload(
                "/v1/documents/upload",
                file_path=source_file,
                data={
                    "missionary_id": str(missionary.id),
                    "document_type": document_type,
                    "workflow_stage": workflow_stage or "GENERAL",
                    "ocr_raw_data": self._serialize_json_field(ocr_raw_data) or "",
                    "ocr_confirmed_data": (
                        self._serialize_json_field(ocr_confirmed_data) or ""
                    ),
                    "notes": notes or "",
                },
            )
            from services.api_client import RemoteRecord

            return RemoteRecord(payload)
        if not document_type:
            raise ValueError("document_type is required")

        session = SessionLocal()

        try:
            source_path = Path(source_file)

            destination_folder = (
                Path(missionary.folder_path)
                / (workflow_stage or "GENERAL")
            )

            destination_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination_path, new_file_name = (
                self._build_destination_path(
                    destination_folder,
                    document_type,
                    source_path.suffix,
                )
            )

            logger.info(
                f"Uploading document "
                f"{new_file_name} "
                f"for missionary "
                f"{missionary.full_name}"
            )

            shutil.copy2(
                source_path,
                destination_path,
            )

            raw_json = self._serialize_json_field(ocr_raw_data)
            confirmed_json = self._serialize_json_field(ocr_confirmed_data)

            document = Document(
                missionary_id=missionary.id,
                document_type=document_type,
                workflow_stage=workflow_stage,
                status="ACTIVE",
                file_name=new_file_name,
                file_path=str(destination_path),
                notes=notes or None,
                ocr_raw_data=raw_json,
                ocr_confirmed_data=confirmed_json,
            )

            session.add(document)

            session.commit()

            session.refresh(document)

            logger.info(
                f"Successfully uploaded "
                f"{new_file_name} "
                f"for missionary "
                f"{missionary.full_name}"
            )

            self.workflow_validator.validate_workflows(
                missionary.id
            )

            return document

        except Exception:
            session.rollback()

            logger.exception(
                f"Failed to upload "
                f"document for "
                f"{missionary.full_name}"
            )

            raise

        finally:
            session.close()

    @staticmethod
    def _serialize_json_field(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, default=str)

    @staticmethod
    def _build_destination_path(
        destination_folder,
        document_type,
        file_extension,
    ):
        destination_folder = Path(destination_folder)
        new_file_name = f"{document_type}{file_extension}"
        destination_path = destination_folder / new_file_name

        counter = 1
        while destination_path.exists():
            new_file_name = (
                f"{document_type}_{counter}"
                f"{file_extension}"
            )
            destination_path = destination_folder / new_file_name
            counter += 1

        return destination_path, new_file_name

    def get_documents(self, missionary_id):
        if self.api_client is not None:
            started_at = time.monotonic()
            payload = self.api_client.get(
                "/v1/rpc/documents/get_documents",
                params={"missionary_id": missionary_id},
            )
            from services.api_client import RemoteRecord

            documents = [RemoteRecord(item) for item in payload["items"]]
            logger.info(
                "Loaded %s document metadata record(s) for missionary %s in %.2fs",
                len(documents),
                missionary_id,
                time.monotonic() - started_at,
            )
            return documents
        session = SessionLocal()

        try:
            logger.info(
                f"Loading documents "
                f"for missionary ID "
                f"{missionary_id}"
            )

            documents = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id
                )
                .all()
            )

            logger.info(
                f"Loaded "
                f"{len(documents)} "
                f"documents for missionary "
                f"ID {missionary_id}"
            )

            return documents

        except Exception:
            logger.exception(
                "Failed to load documents"
            )

            return []

        finally:
            session.close()

    def ensure_local_copy(self, document):
        """Download one remote document only when its local file is needed."""
        source_path = Path(getattr(document, "file_path", "") or "")
        if self.api_client is None:
            if not source_path.is_file():
                raise DocumentFileUnavailableError(document.id)
            return source_path

        cache_root = get_client_data_dir() / "DocumentCache" / str(document.missionary_id)
        suffix = source_path.suffix or ".bin"
        destination = cache_root / f"{document.id}{suffix}"
        if destination.is_file() and destination.stat().st_size > 0:
            logger.info("Document cache hit for document %s", document.id)
            document.file_path = str(destination)
            return destination

        started_at = time.monotonic()
        try:
            self.api_client.download(
                f"/v1/documents/{document.id}/content",
                destination,
            )
        except ApiUnavailableError as error:
            if "404" in str(error):
                raise DocumentFileUnavailableError(document.id) from error
            raise
        logger.info(
            "Downloaded document %s to client cache in %.2fs",
            document.id,
            time.monotonic() - started_at,
        )
        document.file_path = str(destination)
        return destination

    def ensure_local_thumbnail(self, document):
        """Download one lightweight thumbnail without downloading the document."""
        source_path = Path(getattr(document, "file_path", "") or "")
        version = f"{getattr(document, 'file_name', '')}|{getattr(document, 'uploaded_at', '')}"
        version_key = hashlib.sha256(version.encode("utf-8")).hexdigest()[:16]
        cache_root = get_client_data_dir() / "DocumentCache" / str(document.missionary_id) / "thumbnails"
        destination = cache_root / f"{document.id}-{version_key}.jpg"
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        if self.api_client is None:
            raise DocumentFileUnavailableError(document.id)
        self.api_client.download(
            f"/v1/documents/{document.id}/thumbnail",
            destination,
        )
        return destination

    def _materialize(self, document):
        """Compatibility wrapper for callers that still need an eager copy."""
        self.ensure_local_copy(document)
        return document

    def document_type_exists(
        self,
        missionary_id,
        document_type,
    ):
        session = SessionLocal()

        try:
            existing = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id,
                    document_type=document_type,
                    status="ACTIVE",
                )
                .first()
            )

            return existing is not None

        except Exception:
            logger.exception(
                "Failed to check document type"
            )

            return False

        finally:
            session.close()

    def delete_document_by_type(
        self,
        missionary_id,
        document_type,
    ):
        session = SessionLocal()

        try:
            existing = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id,
                    document_type=document_type,
                    status="ACTIVE",
                )
                .first()
            )

            if not existing:
                return

            self._delete_document_record(
                session,
                existing,
                log_label=(
                    f"{document_type} "
                    f"for missionary {missionary_id}"
                ),
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to delete document by type"
            )

        finally:
            session.close()

    def delete_document_by_id(self, document_id):
        session = SessionLocal()

        try:
            existing = (
                session.query(Document)
                .filter_by(id=document_id)
                .first()
            )

            if not existing:
                return False

            self._delete_document_record(
                session,
                existing,
                log_label=(
                    f"document ID {document_id}"
                ),
            )

            return True

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to delete document by ID"
            )

            return False

        finally:
            session.close()

    def update_document_notes(
        self,
        document_id,
        notes,
    ):
        session = SessionLocal()

        try:
            doc = (
                session.query(Document)
                .filter_by(id=document_id)
                .first()
            )

            if not doc:
                return

            doc.notes = notes

            session.commit()

            logger.info(
                f"Updated notes for document "
                f"{document_id}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to update document notes"
            )

        finally:
            session.close()

    def get_document_by_id(
        self,
        document_id,
    ):
        if self.api_client is not None:
            payload = self.api_client.get(f"/v1/documents/{document_id}")
            from services.api_client import RemoteRecord

            return RemoteRecord(payload)
        session = SessionLocal()

        try:
            return (
                session.query(Document)
                .filter_by(id=document_id)
                .first()
            )

        except Exception:
            return None

        finally:
            session.close()

    def _delete_document_record(
        self,
        session,
        document,
        log_label,
    ):
        try:
            old_path = Path(document.file_path)

            if old_path.exists():
                old_path.unlink()

        except Exception:
            logger.warning(
                f"Could not delete file: "
                f"{document.file_path}"
            )

        missionary_id = document.missionary_id
        document_id = document.id

        try:
            from database.models.residency_event import ResidencyEvent

            (
                session.query(ResidencyEvent)
                .filter_by(document_id=document_id)
                .update({"document_id": None})
            )
        except Exception:
            logger.warning(
                "Could not clear residency event document references "
                f"for document ID {document_id}"
            )

        session.delete(document)
        session.commit()

        logger.info(
            f"Deleted {log_label}"
        )

        try:
            self.workflow_validator.validate_workflows(
                missionary_id
            )
        except Exception:
            logger.warning(
                "Deleted document, but workflow "
                "recalculation failed"
            )
