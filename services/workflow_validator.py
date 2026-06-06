from database.db import SessionLocal

from database.models.workflow import (
    WorkflowStage,
)

from database.models.document import (
    Document,
)

from database.models.missionary import (
    Missionary,
)

from utils.constants import (
    WORKFLOW_STAGES,
    required_documents_for_missionary,
)

from utils.logger import logger


class WorkflowValidator:
    def validate_workflows(
        self,
        missionary_id
    ):
        session = SessionLocal()

        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )

            if not missionary:
                return

            workflows = (
                session.query(WorkflowStage)
                .filter_by(
                    missionary_id=missionary_id
                )
                .all()
            )

            documents = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id
                )
                .all()
            )

            uploaded_types = {
                doc.document_type
                for doc in documents
            }

            workflow_map = {
                workflow.stage_name: workflow
                for workflow in workflows
            }

            for stage_name in WORKFLOW_STAGES:

                workflow = (
                    workflow_map.get(stage_name)
                )

                if not workflow:
                    continue

                required_documents = (
                    required_documents_for_missionary(
                        stage_name,
                        missionary,
                    )
                )

                all_documents_uploaded = all(
                    required_doc in uploaded_types
                    for required_doc
                    in required_documents
                )

                # ==========================
                # AUTO WAITING
                # ==========================

                if (
                    all_documents_uploaded
                    and workflow.status
                    in [
                        "NOT STARTED",
                        "IN PROGRESS",
                    ]
                ):
                    workflow.status = "WAITING"

                    missionary.current_stage = (
                        stage_name
                    )

                    logger.info(
                        f"{missionary.full_name} "
                        f"{stage_name} "
                        f"moved to WAITING"
                    )

            session.commit()

        except Exception:
            session.rollback()

            logger.exception(
                "Workflow validation failed"
            )

        finally:
            session.close()

    def get_missing_documents(
        self,
        missionary_id,
        workflow_stage
    ):
        session = SessionLocal()

        try:
            documents = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id
                )
                .all()
            )

            uploaded_types = {
                doc.document_type
                for doc in documents
            }

            required_documents = (
                required_documents_for_missionary(
                    workflow_stage,
                    (
                        session.query(Missionary)
                        .filter_by(id=missionary_id)
                        .first()
                    ),
                )
            )

            missing_documents = [
                document
                for document
                in required_documents
                if document not in uploaded_types
            ]

            return missing_documents

        except Exception:
            logger.exception(
                "Failed to calculate "
                "missing documents"
            )

            return []

        finally:
            session.close()        
