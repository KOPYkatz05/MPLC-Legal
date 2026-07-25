"""Aggregated read models used by responsive remote-client pages.

Each method intentionally returns one complete page snapshot.
Remote clients therefore pay for one authenticated request instead of several
sequential RPC requests while the authoritative server remains the only process
that reads SQLite.
"""

from services.appointment_service import AppointmentService
from services.document_service import DocumentService
from services.missionary_group_service import MissionaryGroupService
from services.missionary_service import MissionaryService
from services.process_automation_service import ProcessAutomationService
from services.remote_service import RemoteServiceMixin
from services.residency_service import ResidencyService
from services.secretary_work_service import SecretaryWorkService
from services.workflow_service import WorkflowService


class ClientViewService(RemoteServiceMixin):
    REMOTE_SERVICE = "client-views"
    REMOTE_METHODS = frozenset(
        {
            "get_missionaries_snapshot",
            "get_calendar_snapshot",
            "get_office_work_snapshot",
            "get_missionary_detail_snapshot",
        }
    )

    def get_missionaries_snapshot(self):
        missionary_service = MissionaryService()
        return {
            "active": missionary_service.get_all_missionaries(),
            "archived": missionary_service.get_archived_missionaries(),
            "groups": MissionaryGroupService().list_groups(),
        }

    def get_calendar_snapshot(self):
        appointment_service = AppointmentService()
        return {
            "scheduled": appointment_service.list_scheduled_appointments(),
            "history": appointment_service.list_history_appointments(),
            "tasks": SecretaryWorkService().list_calendar_tasks(),
        }

    def get_office_work_snapshot(
        self,
        *,
        task_filters=None,
        project_filters=None,
        include_projects=False,
        run_automation=True,
    ):
        automation = (
            ProcessAutomationService().run()
            if run_automation
            else None
        )
        service = SecretaryWorkService()
        snapshot = {
            "automation": automation,
            "grouped_tasks": service.grouped_tasks(**(task_filters or {})),
            "project_options": service.project_options(),
            "missionary_options": service.missionary_options(),
        }
        if include_projects:
            snapshot["projects"] = service.list_projects(
                **(project_filters or {})
            )
        return snapshot

    def get_missionary_detail_snapshot(self, missionary_id):
        missionary = MissionaryService().get_missionary(missionary_id)
        if missionary is None:
            return None

        workflow_service = WorkflowService()
        return {
            "missionary": missionary,
            "workflows": workflow_service.get_workflows(missionary_id),
            "documents": DocumentService().get_documents(missionary_id),
            "tasks": SecretaryWorkService().list_tasks(
                missionary_id=missionary_id
            ),
            "residency_timeline": ResidencyService().get_residency_timeline(
                missionary_id
            ),
            "stage_history": workflow_service.get_stage_history(missionary_id),
        }
