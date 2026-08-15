from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from database.base import Base
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.residency_event import ResidencyEvent
from services import upload_pipeline
from services import workflow_validator as workflow_validator_module
from services.residency_service import (
    INITIAL_RESIDENCY,
    ResidencyService,
)
from services.workflow_validator import WorkflowValidator


@pytest.fixture(autouse=True)
def disable_workflow_validator_remote_dispatch(monkeypatch):
    monkeypatch.setattr(
        "services.remote_service.MissionLegalApiClient.from_environment",
        lambda: None,
    )


@pytest.fixture()
def pipeline_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    monkeypatch.setattr(upload_pipeline, "SessionLocal", sessions)
    monkeypatch.setattr(
        upload_pipeline.MissionLegalApiClient,
        "from_environment",
        lambda: None,
    )
    try:
        yield sessions
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _missionary_and_document(sessions, document_type="DNI"):
    session = sessions()
    try:
        missionary = Missionary(
            missionary_code="post-process-test",
            full_name="Post Processing Test",
            status="ACTIVE",
        )
        session.add(missionary)
        session.flush()
        document = Document(
            missionary_id=missionary.id,
            document_type=document_type,
            workflow_stage="GENERAL",
            file_name="scan.pdf",
            file_path="C:/documents/scan.pdf",
        )
        session.add(document)
        session.commit()
        return missionary.id, document.id
    finally:
        session.close()


def test_finalize_keeps_durable_upload_when_all_post_processing_fails(
    monkeypatch,
):
    captured = {}
    saved_document = SimpleNamespace(id=321)

    class DocumentServiceStub:
        def upload_document(self, **kwargs):
            captured.update(kwargs)
            return saved_document

    def fail_updates(*_args, **_kwargs):
        raise RuntimeError("field update unavailable")

    def fail_workflow(*_args, **_kwargs):
        raise RuntimeError("workflow unavailable")

    monkeypatch.setattr(
        upload_pipeline,
        "apply_missionary_updates",
        fail_updates,
    )
    monkeypatch.setattr(
        "services.workflow_validator.WorkflowValidator.validate_workflows",
        fail_workflow,
    )
    monkeypatch.setattr(
        upload_pipeline,
        "_get_current_stage",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("stage unavailable")
        ),
    )
    monkeypatch.setattr(
        upload_pipeline,
        "get_missing_for_missionary",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("missing list unavailable")
        ),
    )

    result = upload_pipeline.finalize_ocr_ingestion(
        missionary=SimpleNamespace(id=7, current_stage="GENERAL"),
        source_file="carne-front.jpg",
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        document_service=DocumentServiceStub(),
        upload_id="stable-upload-id",
        supersedes_document_id=88,
    )

    assert result.document is saved_document
    assert result.status == "saved_with_warnings"
    assert result.saved_with_warnings is True
    assert len(result.warnings) == 4
    assert result.updated_fields == []
    assert result.missing_documents == []
    assert captured["upload_id"] == "stable-upload-id"
    assert captured["supersedes_document_id"] == 88


def test_finalize_reports_plain_saved_when_post_processing_succeeds(
    monkeypatch,
):
    saved_document = SimpleNamespace(id=654)
    service = SimpleNamespace(
        upload_document=lambda **_kwargs: saved_document
    )
    monkeypatch.setattr(
        upload_pipeline,
        "apply_missionary_updates",
        lambda *_args, **_kwargs: ["carnet_number"],
    )
    monkeypatch.setattr(
        "services.workflow_validator.WorkflowValidator.validate_workflows",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        upload_pipeline,
        "_get_current_stage",
        lambda *_args: "CARNET DE EXTRANJERIA",
    )
    monkeypatch.setattr(
        upload_pipeline,
        "get_missing_for_missionary",
        lambda *_args: ["CITA_RECOJO"],
    )

    result = upload_pipeline.finalize_ocr_ingestion(
        missionary=SimpleNamespace(id=7, current_stage=None),
        source_file="carne.jpg",
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        document_service=service,
    )

    assert result.document is saved_document
    assert result.status == "saved"
    assert result.saved_with_warnings is False
    assert result.warnings == []
    assert result.updated_fields == ["carnet_number"]
    assert result.missing_documents == ["CITA_RECOJO"]


def test_finalize_trusts_authoritative_retry_marker_without_duplicate_rpc(
    monkeypatch,
):
    saved_document = SimpleNamespace(
        id=655,
        post_processing_status="RETRY_REQUIRED",
        post_processing_error="RuntimeError: database unavailable",
    )
    service = SimpleNamespace(
        upload_document=lambda **_kwargs: saved_document
    )
    monkeypatch.setattr(
        upload_pipeline,
        "apply_missionary_updates",
        lambda *_args, **_kwargs: pytest.fail(
            "the paired server owns durable post-processing"
        ),
    )
    monkeypatch.setattr(
        "services.workflow_validator.WorkflowValidator.validate_workflows",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        upload_pipeline,
        "_get_current_stage",
        lambda *_args: "CARNET DE EXTRANJERIA",
    )
    monkeypatch.setattr(
        upload_pipeline,
        "get_missing_for_missionary",
        lambda *_args: [],
    )

    result = upload_pipeline.finalize_ocr_ingestion(
        missionary=SimpleNamespace(id=7, current_stage=None),
        source_file="carne.jpg",
        document_type="CARNE_DE_EXTRANJERIA",
        workflow_stage="CARNET DE EXTRANJERIA",
        document_service=service,
    )

    assert result.document is saved_document
    assert result.status == "saved_with_warnings"
    assert len(result.warnings) == 1
    assert "still need to be retried" in result.warnings[0]


def test_finalize_preserves_authoritative_updated_fields(monkeypatch):
    saved_document = SimpleNamespace(
        id=656,
        post_processing_status="COMPLETE",
        post_processing_error=None,
        post_processing_updated_fields=(
            '["interpol_appointment_date", "passport_number"]'
        ),
    )
    service = SimpleNamespace(
        upload_document=lambda **_kwargs: saved_document
    )
    monkeypatch.setattr(
        upload_pipeline,
        "apply_missionary_updates",
        lambda *_args, **_kwargs: pytest.fail(
            "completed server work must not be duplicated by the client"
        ),
    )
    monkeypatch.setattr(
        "services.workflow_validator.WorkflowValidator.validate_workflows",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        upload_pipeline,
        "_get_current_stage",
        lambda *_args: "INTERPOL",
    )
    monkeypatch.setattr(
        upload_pipeline,
        "get_missing_for_missionary",
        lambda *_args: [],
    )

    result = upload_pipeline.finalize_ocr_ingestion(
        missionary=SimpleNamespace(id=7, current_stage=None),
        source_file="passport.pdf",
        document_type="PASSPORT",
        workflow_stage="INTERPOL",
        confirmed_data={"passport_number": "A1234567"},
        document_service=service,
    )

    assert result.status == "saved"
    assert result.updated_fields == [
        "interpol_appointment_date",
        "passport_number",
    ]


class _FailingWorkflowSession:
    def __init__(self):
        self.closed = False
        self.rolled_back = False

    def query(self, *_args, **_kwargs):
        raise RuntimeError("workflow database unavailable")

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_workflow_validator_strict_mode_propagates_database_failures(
    monkeypatch,
):
    sessions = []

    def session_factory():
        session = _FailingWorkflowSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        workflow_validator_module,
        "SessionLocal",
        session_factory,
    )
    monkeypatch.setattr(
        "services.remote_service.MissionLegalApiClient.from_environment",
        lambda: None,
    )

    validator = WorkflowValidator()
    with pytest.raises(RuntimeError, match="workflow database unavailable"):
        validator.validate_workflows(7, raise_on_error=True)
    with pytest.raises(RuntimeError, match="workflow database unavailable"):
        validator.get_missing_documents(
            7,
            "INTERPOL",
            raise_on_error=True,
        )

    assert len(sessions) == 2
    assert sessions[0].rolled_back is True
    assert all(session.closed for session in sessions)


def test_workflow_validator_default_mode_keeps_legacy_fallbacks(
    monkeypatch,
):
    sessions = []

    def session_factory():
        session = _FailingWorkflowSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        workflow_validator_module,
        "SessionLocal",
        session_factory,
    )
    monkeypatch.setattr(
        "services.remote_service.MissionLegalApiClient.from_environment",
        lambda: None,
    )

    validator = WorkflowValidator()
    assert validator.validate_workflows(7) is None
    assert validator.get_missing_documents(7, "INTERPOL") == []

    assert len(sessions) == 2
    assert sessions[0].rolled_back is True
    assert all(session.closed for session in sessions)


def test_finalize_requests_strict_workflow_refreshes(monkeypatch):
    saved_document = SimpleNamespace(id=777)
    service = SimpleNamespace(
        upload_document=lambda **_kwargs: saved_document
    )
    strict_calls = []

    def fail_strict_validation(
        _self,
        _missionary_id,
        *,
        raise_on_error=False,
    ):
        strict_calls.append(("validate", raise_on_error))
        if raise_on_error:
            raise RuntimeError("workflow validation failed")

    def fail_strict_missing(
        _self,
        _missionary_id,
        _stage,
        *,
        raise_on_error=False,
    ):
        strict_calls.append(("missing", raise_on_error))
        if raise_on_error:
            raise RuntimeError("missing-document refresh failed")
        return []

    monkeypatch.setattr(
        "services.remote_service.MissionLegalApiClient.from_environment",
        lambda: None,
    )
    monkeypatch.setattr(
        WorkflowValidator,
        "validate_workflows",
        fail_strict_validation,
    )
    monkeypatch.setattr(
        WorkflowValidator,
        "get_missing_documents",
        fail_strict_missing,
    )
    monkeypatch.setattr(
        upload_pipeline,
        "_get_current_stage",
        lambda *_args: "INTERPOL",
    )

    result = upload_pipeline.finalize_ocr_ingestion(
        missionary=SimpleNamespace(id=7, current_stage="INTERPOL"),
        source_file="interpol.pdf",
        document_type="PAGO_INTERPOL",
        workflow_stage="INTERPOL",
        document_service=service,
    )

    assert result.document is saved_document
    assert result.status == "saved_with_warnings"
    assert len(result.warnings) == 2
    assert strict_calls == [("validate", True), ("missing", True)]


def test_apply_updates_uses_stored_type_and_intersects_safe_fields(
    pipeline_db,
):
    missionary_id, document_id = _missionary_and_document(
        pipeline_db,
        document_type="DNI",
    )

    updated = upload_pipeline.apply_missionary_updates(
        missionary_id,
        "PASSPORT",
        document_id,
        {
            "dni_number": "1234 5678",
            "passport_number": "SHOULD-NOT-BE-WRITTEN",
            "status": "RELEASED",
        },
        auto_update_fields=["dni_number", "passport_number", "status"],
    )

    session = pipeline_db()
    try:
        missionary = session.get(Missionary, missionary_id)
        assert updated == ["dni_number"]
        assert missionary.dni_number == "12345678"
        assert missionary.passport_number is None
        assert missionary.status == "ACTIVE"
    finally:
        session.close()


def test_apply_updates_propagates_commit_failure(
    pipeline_db,
    monkeypatch,
):
    missionary_id, document_id = _missionary_and_document(
        pipeline_db,
        document_type="DNI",
    )

    def fail_commit(_session):
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(Session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="database commit failed"):
        upload_pipeline.apply_missionary_updates(
            missionary_id,
            "DNI",
            document_id,
            {"dni_number": "12345678"},
        )


def test_residency_identity_collision_returns_concurrent_winner(
    monkeypatch,
):
    service = ResidencyService()
    winner = ResidencyEvent(
        id=44,
        missionary_id=9,
        event_type=INITIAL_RESIDENCY,
        sequence_number=0,
        status="APPROVED",
        document_id=22,
    )
    identity_reads = iter([None, winner])
    monkeypatch.setattr(
        service,
        "_identity_event",
        lambda *_args, **_kwargs: next(identity_reads),
    )

    class CollisionSession:
        def begin_nested(self):
            return nullcontext()

        def add(self, _event):
            return None

        def flush(self):
            raise IntegrityError(
                "INSERT INTO residency_events",
                {},
                RuntimeError("unique identity"),
            )

    result = service._get_or_create_identity_event(
        CollisionSession(),
        missionary_id=9,
        event_type=INITIAL_RESIDENCY,
        sequence_number=0,
        document_id=22,
    )

    assert result is winner
