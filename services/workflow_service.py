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
from services.document_storage_service import (
    commit_with_folder_rollback,
    move_folder_and_rewrite_paths,
    rollback_folder_move,
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
        folder_move = None
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
                    folder_move = move_folder_and_rewrite_paths(
                        session,
                        missionary,
                        self.onedrive_service.archive_missionary_folder,
                    )
                destination = "ARCHIVED"
            session.add(
                StageHistory(
                    missionary_id=missionary.id,
                    from_stage=current_stage,
                    to_stage=destination,
                )
            )
            commit_with_folder_rollback(session, folder_move)
            return True
        except Exception:
            session.rollback()
            rollback_folder_move(folder_move)
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
        folder_move = None

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

                return None

            workflow.status = new_status

            missionary = (
                session.query(Missionary)
                .filter_by(id=workflow.missionary_id)
                .first()
            )
            if missionary is None:
                raise LookupError(
                    f"Missionary {workflow.missionary_id} not found"
                )

            if (
                workflow.stage_name == "PRORROGA"
                and new_status == "COMPLETED"
            ):
                apply_stage_completion_expiration(
                    missionary,
                    workflow.stage_name,
                )

            workflows = (
                session.query(WorkflowStage)
                .filter_by(missionary_id=workflow.missionary_id)
                .all()
            )
            current_stage = self._earliest_incomplete_from_rows(workflows) or "NEW"
            missionary.current_stage = current_stage

            should_archive = (
                workflow.stage_name == "CANCELACION"
                and new_status == "COMPLETED"
                and missionary.status == "ACTIVE"
            )
            if should_archive:
                missionary.status = "ARCHIVED"
                missionary.cancelacion_date = date.today()
                if missionary.folder_path:
                    folder_move = move_folder_and_rewrite_paths(
                        session,
                        missionary,
                        self.onedrive_service.archive_missionary_folder,
                    )
                session.add(
                    StageHistory(
                        missionary_id=missionary.id,
                        from_stage=workflow.stage_name,
                        to_stage="ARCHIVED",
                    )
                )

            result = {
                "workflow_id": int(workflow.id),
                "missionary_id": int(missionary.id),
                "workflow_status": str(workflow.status),
                "current_stage": str(missionary.current_stage),
                "missionary_status": str(missionary.status),
            }
            stage_name = str(workflow.stage_name)

            commit_with_folder_rollback(session, folder_move)

        except Exception:
            session.rollback()
            rollback_folder_move(folder_move)

            logger.exception(
                "Failed to update workflow status"
            )
            raise

        finally:
            session.close()

        logger.info(
            "Updated workflow %s to %s",
            stage_name,
            new_status,
        )
        return result

    @staticmethod
    def _earliest_incomplete_from_rows(workflows):
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

    @staticmethod
    def _complete_workflow_statuses(workflows):
        counts = {stage_name: 0 for stage_name in WORKFLOW_STAGES}
        unexpected = 0
        statuses = {}
        for workflow in workflows:
            stage_name = workflow.stage_name
            if stage_name not in counts:
                unexpected += 1
                continue
            counts[stage_name] += 1
            statuses[stage_name] = workflow.status
        if unexpected or any(count != 1 for count in counts.values()):
            return None, counts, unexpected
        return statuses, counts, unexpected

    def reconcile_missionary_stages(self, missionary_ids=None):
        """Repair deterministic current-stage drift for active legal records."""
        session = SessionLocal()
        try:
            query = session.query(Missionary).filter_by(status="ACTIVE")
            if missionary_ids is not None:
                ids = list(dict.fromkeys(missionary_ids))
                if not ids:
                    return []
                query = query.filter(Missionary.id.in_(ids))

            missionaries = query.all()
            legal_missionaries = [
                missionary
                for missionary in missionaries
                if (missionary.tracking_profile or "LEGAL") == "LEGAL"
            ]
            if not legal_missionaries:
                return []

            rows = (
                session.query(WorkflowStage)
                .filter(
                    WorkflowStage.missionary_id.in_(
                        [missionary.id for missionary in legal_missionaries]
                    )
                )
                .all()
            )
            rows_by_missionary = {}
            for row in rows:
                rows_by_missionary.setdefault(row.missionary_id, []).append(row)

            repaired = []
            for missionary in legal_missionaries:
                statuses, counts, unexpected = self._complete_workflow_statuses(
                    rows_by_missionary.get(missionary.id, [])
                )
                if statuses is None:
                    logger.warning(
                        "Skipped workflow-stage reconciliation for missionary %s: "
                        "stage_counts=%s unexpected=%s",
                        missionary.id,
                        counts,
                        unexpected,
                    )
                    continue
                current_stage = next(
                    (
                        stage_name
                        for stage_name in WORKFLOW_STAGES
                        if statuses[stage_name] != "COMPLETED"
                    ),
                    "NEW",
                )
                if missionary.current_stage == current_stage:
                    continue
                old_stage = missionary.current_stage
                missionary.current_stage = current_stage
                repaired.append({
                    "missionary_id": missionary.id,
                    "old_stage": old_stage,
                    "current_stage": current_stage,
                })
                logger.warning(
                    "Reconciled workflow stage for missionary %s from %s to %s",
                    missionary.id,
                    old_stage,
                    current_stage,
                )

            if repaired:
                session.commit()
            return repaired
        except Exception:
            session.rollback()
            logger.exception("Failed to reconcile missionary workflow stages")
            raise
        finally:
            session.close()

    def update_missionary_stage(
        self,
        missionary_id
    ):
        repaired = self.reconcile_missionary_stages([missionary_id])
        return repaired[0] if repaired else None

    def check_for_archive(
        self,
        missionary_id
    ):
        session = SessionLocal()
        folder_move = None

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

            folder_move = move_folder_and_rewrite_paths(
                session,
                missionary,
                self.onedrive_service.archive_missionary_folder,
            )
            commit_with_folder_rollback(session, folder_move)

            logger.info(
                f"Archived missionary "
                f"{missionary.full_name}"
            )

        except Exception:
            session.rollback()
            rollback_folder_move(folder_move)

            logger.exception(
                "Failed to archive missionary"
            )

        finally:
            session.close()
