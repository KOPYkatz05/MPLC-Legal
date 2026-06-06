from datetime import date

from database.db import SessionLocal

from database.models.workflow import (
    WorkflowStage,
)

from database.models.missionary import (
    Missionary,
)

from utils.constants import (
    WORKFLOW_STAGES,
)

from utils.logger import logger

from services.expiration_rules import (
    apply_stage_completion_expiration,
)

from services.onedrive_service import (
    OneDriveService,
)


class WorkflowService:
    def __init__(self):
        self.onedrive_service = (
            OneDriveService()
        )

    def initialize_workflows(
        self,
        missionary_id
    ):
        session = SessionLocal()

        try:
            for stage_name in WORKFLOW_STAGES:
                workflow = WorkflowStage(
                    missionary_id=missionary_id,
                    stage_name=stage_name,
                    status="NOT STARTED",
                )

                session.add(workflow)

            session.commit()

            logger.info(
                f"Initialized workflows "
                f"for missionary ID "
                f"{missionary_id}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to initialize workflows"
            )

        finally:
            session.close()

    def get_workflows(
        self,
        missionary_id
    ):
        session = SessionLocal()

        workflows = (
            session.query(WorkflowStage)
            .filter_by(
                missionary_id=missionary_id
            )
            .all()
        )

        session.close()

        return workflows

    def update_workflow_status(
        self,
        workflow_id,
        new_status
    ):
        session = SessionLocal()

        try:
            workflow = (
                session.query(WorkflowStage)
                .filter_by(id=workflow_id)
                .first()
            )

            if not workflow:
                logger.warning(
                    f"Workflow ID "
                    f"{workflow_id} "
                    f"not found"
                )

                return

            workflow.status = new_status

            if (
                workflow.stage_name == "PRORROGA"
                and new_status == "COMPLETED"
            ):
                missionary = (
                    session.query(Missionary)
                    .filter_by(id=workflow.missionary_id)
                    .first()
                )
                if missionary:
                    apply_stage_completion_expiration(
                        missionary,
                        workflow.stage_name,
                    )

            session.commit()

            logger.info(
                f"Updated workflow "
                f"{workflow.stage_name} "
                f"to {new_status}"
            )

            self.update_missionary_stage(
                workflow.missionary_id
            )

            self.check_for_archive(
                workflow.missionary_id
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to update workflow status"
            )

        finally:
            session.close()

    def update_missionary_stage(
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

            current_stage = "NEW"

            for workflow in workflows:
                if workflow.status in [
                    "IN PROGRESS",
                    "WAITING",
                    "BLOCKED",
                ]:
                    current_stage = (
                        workflow.stage_name
                    )

                    break

            if current_stage == "NEW":
                for workflow in workflows:
                    if workflow.status == (
                        "COMPLETED"
                    ):
                        current_stage = (
                            workflow.stage_name
                        )

            missionary.current_stage = (
                current_stage
            )

            session.commit()

            logger.info(
                f"Updated current stage "
                f"for missionary "
                f"{missionary.full_name} "
                f"to {current_stage}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to update "
                "missionary stage"
            )

        finally:
            session.close()

    def check_for_archive(
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

            cancelacion_workflow = (
                session.query(WorkflowStage)
                .filter_by(
                    missionary_id=missionary_id,
                    stage_name="CANCELACION",
                )
                .first()
            )

            if not cancelacion_workflow:
                return

            if (
                cancelacion_workflow.status
                != "COMPLETED"
            ):
                return

            missionary.status = "ARCHIVED"

            missionary.cancelacion_date = (
                date.today()
            )

            new_folder = (
                self.onedrive_service
                .archive_missionary_folder(
                    missionary.folder_path
                )
            )

            missionary.folder_path = (
                str(new_folder)
            )

            session.commit()

            logger.info(
                f"Archived missionary "
                f"{missionary.full_name}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to archive missionary"
            )

        finally:
            session.close()
