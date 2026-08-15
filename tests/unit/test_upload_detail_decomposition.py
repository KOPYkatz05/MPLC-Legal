from types import SimpleNamespace

from ui.dialogs.upload_session.models import UploadSaveResult
from ui.dialogs.upload_session.orchestration import (
    UploadBatchCoordinator,
    UploadOperationState,
    UploadSaveWorkerCoordinator,
)
from ui.dialogs.upload_session.controller import UploadSessionController
from ui.dialogs.upload_session_dialog import (
    UploadSessionController as LegacyUploadSessionController,
)
from ui.pages.missionary_detail.coordinator import MissionaryDetailCoordinator
from ui.pages.missionary_detail.identity_section import IdentityDetailsSection
from ui.pages.missionary_detail.notes_section import NotesSection
from ui.pages.missionary_detail.state import MissionaryDetailState


def test_upload_batch_coordinator_owns_progress_and_result_counts():
    coordinator = UploadBatchCoordinator()

    coordinator.begin(3)
    coordinator.record(UploadSaveResult(status="saved"))
    coordinator.record(
        UploadSaveResult(status="saved", warnings=["follow-up"])
    )
    coordinator.record(UploadSaveResult(status="failed"))

    assert coordinator.state is UploadOperationState.SAVING
    assert coordinator.completed == 3
    assert coordinator.counts() == {
        "saved": 2,
        "failed": 1,
        "skipped": 0,
        "warnings": 1,
    }

    coordinator.finish()
    assert coordinator.state is UploadOperationState.IDLE
    assert coordinator.results


def test_legacy_upload_controller_is_extracted_controller():
    assert LegacyUploadSessionController is UploadSessionController


def test_save_worker_coordinator_rejects_overlapping_start(qapp):
    class FakeSignal:
        def connect(self, _callback):
            pass

    class FakeWorker:
        def __init__(self, _controller, _index):
            self.finished = FakeSignal()

        def moveToThread(self, _thread):
            pass

        def run(self):
            pass

        def deleteLater(self):
            pass

    coordinator = UploadSaveWorkerCoordinator(worker_factory=FakeWorker)
    coordinator._thread = object()

    assert coordinator.running
    assert coordinator.start(object(), 0) is False


def test_detail_coordinator_rejects_stale_request_and_expires_cache():
    now = [100.0]
    state = MissionaryDetailState(cache_ttl_seconds=15.0)
    coordinator = MissionaryDetailCoordinator(
        state,
        clock=lambda: now[0],
    )

    coordinator.begin(42)
    coordinator.store(42, {"missionary": SimpleNamespace(id=42)})

    assert coordinator.accepts(42)
    assert not coordinator.accepts(41)
    assert coordinator.cache_is_fresh(42)

    now[0] += 16.0
    assert not coordinator.cache_is_fresh(42)

    coordinator.invalidate(42)
    assert coordinator.cached(42) is None


def test_detail_state_clears_rendered_records_without_clearing_cache():
    state = MissionaryDetailState(
        workflow_records=[SimpleNamespace(id=1)],
        document_records={2: SimpleNamespace(id=2)},
        snapshot_cache={42: {"snapshot": {}}},
    )

    state.clear_rendered_records()

    assert state.workflow_records == []
    assert state.document_records == {}
    assert 42 in state.snapshot_cache


def test_identity_section_noops_without_current_missionary():
    host = SimpleNamespace()

    assert IdentityDetailsSection(host).save() is None


def test_identity_section_persists_changed_text_and_refreshes(monkeypatch):
    from ui.pages import missionary_detail_page as detail_facade

    updates = []
    refreshes = []
    host = SimpleNamespace(
        current_missionary=SimpleNamespace(
            id=42,
            passport_number="OLD",
            arrival_date=None,
            visa_expiration=None,
            field_sources=None,
        ),
        _date_edits={},
        _date_empty_on_load=set(),
        _text_edits={
            "passport_number": SimpleNamespace(text=lambda: "NEW")
        },
        missionary_service=SimpleNamespace(
            update_fields=lambda missionary_id, values: updates.append(
                (missionary_id, values)
            )
        ),
        _reload_missionary=lambda: refreshes.append("detail"),
        _refresh_missionaries_table=lambda: refreshes.append("list"),
    )
    monkeypatch.setattr(detail_facade, "show_message", lambda *_a, **_k: None)

    IdentityDetailsSection(host).save()

    assert updates == [(42, {"passport_number": "NEW"})]
    assert refreshes == ["detail", "list"]


def test_notes_section_persists_through_host_service(monkeypatch):
    from ui.pages import missionary_detail_page as detail_facade

    updates = []
    messages = []
    host = SimpleNamespace(
        current_missionary=SimpleNamespace(id=42, full_name="Test"),
        notes_text=SimpleNamespace(toPlainText=lambda: "Reviewed"),
        missionary_service=SimpleNamespace(
            update_fields=lambda missionary_id, values: updates.append(
                (missionary_id, values)
            )
        ),
    )
    monkeypatch.setattr(
        detail_facade,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )

    NotesSection(host).save()

    assert updates == [(42, {"notes": "Reviewed"})]
    assert len(messages) == 1
