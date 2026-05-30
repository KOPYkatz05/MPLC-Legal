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
    ):
        session = SessionLocal()

        try:
            source_path = Path(
                source_file
            )

            destination_folder = (
                Path(missionary.folder_path)
                / workflow_stage
            )

            destination_folder.mkdir(
                exist_ok=True
            )

            file_extension = (
                source_path.suffix
            )

            new_file_name = (
                f"{document_type}"
                f"{file_extension}"
            )

            destination_path = (
                destination_folder
                / new_file_name
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

            document = Document(
                missionary_id=missionary.id,
                document_type=document_type,
                workflow_stage=workflow_stage,
                file_name=new_file_name,
                file_path=str(destination_path),
            )

            session.add(document)

            session.commit()

            logger.info(
                f"Successfully uploaded "
                f"{new_file_name} "
                f"for missionary "
                f"{missionary.full_name}"
            )

            # =====================================
            # Run workflow validation
            # =====================================

            self.workflow_validator.validate_workflows(
                missionary.id
            )

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

    def get_documents(
        self,
        missionary_id
    ):
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