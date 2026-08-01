from datetime import date

from database.db import SessionLocal
from services.remote_service import RemoteServiceMixin
from services.api_client import MissionLegalApiClient

from database.models.workflow import (
    WorkflowStage,
)

from database.models.missionary import (
    Missionary,
)
from database.models.stage_history import StageHistory

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


class WorkflowService(RemoteServiceMixin):
    REMOTE_SERVICE = "workflows"
    REMOTE_METHODS = frozenset({
        "initialize_workflows",
        "get_workflows",
        "get_earliest_incomplete_stage",
        "update_workflow_status",
        "update_missionary_stage",
        "check_for_archive",
        "get_stage_history",
        "advance_missionary",
        "advance_missionaries",
    })
    def __init__(self):
        if MissionLegalApiClient.from_environment() is not None:
            self.onedrive_service = None
            return
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

    def get_stage_history(self, missionary_id):
        session = SessionLocal()
        try:
            return (
                session.query(StageHistory)
                .filter_by(missionary_id=missionary_id)
                .order_by(StageHistory.created_at.desc(), StageHistory.id.desc())
                .all()
            )
        finally:
            session.close()

    def advance_missionary(self, missionary_id):
        session = SessionLocal()
        try:
            missionary = session.query(Missionary).filter_by(id=missionary_id).first()
            if missionary is None:
                return False
            if (missionary.tracking_profile or "LEGAL") == "PERUVIAN_DNI":
                return False
            workflows = (
                session.query(WorkflowStage)
                .filter_by(missionary_id=missionary_id)
                .all()
            )
            workflow_by_stage = {row.stage_name: row for row in workflows}
            current_stage = self.get_earliest_incomplete_stage(
                missionary_id, session=session
            ) or missionary.current_stage
            if current_stage not in WORKFLOW_STAGES:
                return False
            index = WORKFLOW_STAGES.index(current_stage)
            next_stage = (
                WORKFLOW_STAGES[index + 1]
                if index + 1 < len(WORKFLOW_STAGES)
                else None
            )
            current_workflow = workflow_by_stage.get(current_stage)
            if current_workflow:
                current_workflow.status = "COMPLETED"
            apply_stage_completion_expiration(missionary, current_stage)
            if next_stage:
                missionary.current_stage = next_stage
                next_workflow = workflow_by_stage.get(next_stage)
                if next_workflow:
                    next_workflow.status = "IN PROGRESS"
                destination = next_stage
            else:
                missionary.status = "ARCHIVED"
                if missionary.folder_path:
                    new_folder = self.onedrive_service.archive_missionary_folder(
                        missionary.folder_path
                    )
                    missionary.folder_path = str(new_folder)
                destination = "ARCHIVED"
            session.add(
                StageHistory(
                    missionary_id=missionary.id,
                    from_stage=current_stage,
                    to_stage=destination,
                )
            )
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("Failed to advance missionary %s", missionary_id)
            raise
        finally:
            session.close()

    def advance_missionaries(self, missionary_ids):
        results = {}
        for missionary_id in dict.fromkeys(missionary_ids or []):
            results[missionary_id] = self.advance_missionary(missionary_id)
        return results

    @staticmethod
    def get_earliest_incomplete_stage(missionary_id, session=None):
        """Return the first unfinished workflow stage in the defined order."""
        owns_session = session is None
        session = session or SessionLocal()

        try:
            workflows = (
                session.query(WorkflowStage)
                .filter_by(missionary_id=missionary_id)
                .all()
            )
            statuses = {
                workflow.stage_name: workflow.status
                for workflow in workflows
            }
            return next(
                (
                    stage_name
                    for stage_name in WORKFLOW_STAGES
                    if statuses.get(stage_name) != "COMPLETED"
                ),
                None,
            )
        finally:
            if owns_session:
                session.close()

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

            current_stage = (
                self.get_earliest_incomplete_stage(
                    missionary_id,
                    session=session,
                )
                or "NEW"
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
