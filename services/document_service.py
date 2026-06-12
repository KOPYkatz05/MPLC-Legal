import json
import shutil

from pathlib import Path

from database.db import SessionLocal

from database.models.document import (
    Document,
)

from utils.logger import logger

from services.workflow_validator import (
    WorkflowValidator,
)


class DocumentService:
    def __init__(self):
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
    ):
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

            raw_json = None
            confirmed_json = None
            if ocr_raw_data is not None:
                raw_json = json.dumps(ocr_raw_data, default=str)
            if ocr_confirmed_data is not None:
                confirmed_json = json.dumps(
                    ocr_confirmed_data, default=str
                )

            document = Document(
                missionary_id=missionary.id,
                document_type=document_type,
                workflow_stage=workflow_stage,
                status="ACTIVE",
                file_name=new_file_name,
                file_path=str(destination_path),
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
