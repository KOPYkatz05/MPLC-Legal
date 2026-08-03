from types import SimpleNamespace

from services import client_view_service as view_module
from services.client_view_service import ClientViewService
from server.app import _rpc_services


class _Missionaries:
    def get_all_missionaries(self):
        return ["active"]

    def get_archived_missionaries(self):
        return ["archived"]

    def get_missionary(self, missionary_id):
        if missionary_id == 404:
            return None
        return SimpleNamespace(id=missionary_id, full_name="Test Missionary")


class _Groups:
    def list_groups(self):
        return [{"id": 7, "name": "Group"}]


class _Appointments:
    def list_scheduled_appointments(self):
        return ["scheduled"]

    def list_history_appointments(self):
        return ["history"]


class _SecretaryWork:
    def list_calendar_tasks(self):
        return ["calendar-task"]

    def grouped_tasks(self, **filters):
        return {"filters": filters}

    def project_options(self):
        return [{"id": 1, "title": "Project"}]

    def missionary_options(self):
        return [{"id": 2, "name": "Missionary"}]

    def list_projects(self, **filters):
        return [{"filters": filters}]

    def list_tasks(self, **filters):
        return [{"filters": filters}]


class _Automation:
    def run(self):
        return {"created": 1}


class _Workflows:
    def get_workflows(self, missionary_id):
        return [f"workflow-{missionary_id}"]

    def get_stage_history(self, missionary_id):
        return [f"history-{missionary_id}"]


class _Documents:
    def get_documents(self, missionary_id):
        return [f"document-{missionary_id}"]


class _Residency:
    def get_residency_timeline(self, missionary_id):
        return [{"missionary_id": missionary_id}]


class _ActivityFeed:
    def get_missionary_activity(self, missionary_id):
        return {
            "events": [{"missionary_id": missionary_id}],
            "upcoming": [],
        }


def _install_fakes(monkeypatch):
    monkeypatch.setattr(view_module, "MissionaryService", _Missionaries)
    monkeypatch.setattr(view_module, "MissionaryGroupService", _Groups)
    monkeypatch.setattr(view_module, "AppointmentService", _Appointments)
    monkeypatch.setattr(view_module, "SecretaryWorkService", _SecretaryWork)
    monkeypatch.setattr(view_module, "ProcessAutomationService", _Automation)
    monkeypatch.setattr(view_module, "WorkflowService", _Workflows)
    monkeypatch.setattr(view_module, "DocumentService", _Documents)
    monkeypatch.setattr(view_module, "ResidencyService", _Residency)
    monkeypatch.setattr(view_module, "ActivityFeedService", _ActivityFeed)


def test_missionaries_and_calendar_snapshots_are_aggregated(monkeypatch):
    _install_fakes(monkeypatch)
    service = ClientViewService()

    assert service.get_missionaries_snapshot() == {
        "active": ["active"],
        "archived": ["archived"],
        "groups": [{"id": 7, "name": "Group"}],
    }
    assert service.get_calendar_snapshot() == {
        "scheduled": ["scheduled"],
        "history": ["history"],
        "tasks": ["calendar-task"],
    }


def test_client_view_service_is_registered_for_server_rpc():
    service_type, allowed_methods = _rpc_services()["client-views"]

    assert service_type is ClientViewService
    assert allowed_methods == ClientViewService.REMOTE_METHODS


def test_office_work_snapshot_respects_filters_and_optional_projects(monkeypatch):
    _install_fakes(monkeypatch)

    snapshot = ClientViewService().get_office_work_snapshot(
        task_filters={"status": "OPEN"},
        project_filters={"priority": "HIGH"},
        include_projects=True,
    )

    assert snapshot["grouped_tasks"] == {"filters": {"status": "OPEN"}}
    assert snapshot["automation"] == {"created": 1}
    assert snapshot["projects"] == [{"filters": {"priority": "HIGH"}}]
    assert snapshot["project_options"] == [{"id": 1, "title": "Project"}]
    assert snapshot["missionary_options"] == [{"id": 2, "name": "Missionary"}]

    without_automation = ClientViewService().get_office_work_snapshot(
        run_automation=False
    )
    assert without_automation["automation"] is None


def test_detail_snapshot_returns_all_sections_or_none(monkeypatch):
    _install_fakes(monkeypatch)
    service = ClientViewService()

    assert service.get_missionary_detail_snapshot(404) is None

    snapshot = service.get_missionary_detail_snapshot(9)
    assert snapshot["missionary"].id == 9
    assert snapshot["workflows"] == ["workflow-9"]
    assert snapshot["documents"] == ["document-9"]
    assert snapshot["tasks"] == [{"filters": {"missionary_id": 9}}]
    assert snapshot["residency_timeline"] == [{"missionary_id": 9}]
    assert snapshot["stage_history"] == ["history-9"]
    assert snapshot["activity_feed"] == {
        "events": [{"missionary_id": 9}],
        "upcoming": [],
    }


def test_detail_activity_is_an_explicit_server_rpc(monkeypatch):
    _install_fakes(monkeypatch)

    assert "get_missionary_activity" in ClientViewService.REMOTE_METHODS
    assert ClientViewService().get_missionary_activity(12) == {
        "events": [{"missionary_id": 12}],
        "upcoming": [],
    }
