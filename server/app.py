import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

# Importing this module means the process is the authoritative server. Business
# services invoked by API routes must never proxy back into the API recursively,
# even if the interactive Windows profile has client settings configured.
os.environ["MISSION_LEGAL_SERVER_PROCESS"] = "1"

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from sqlalchemy import text

from database.db import engine, init_db
from database.runtime import get_app_data_dir, get_database_path
from database.schema import get_schema_version
from server.security import DeviceCredentialStore, PairingCodeStore
from server.serialization import model_snapshot, serialize_result
from services.remote_service import decode_remote_value
from services.database_backup_service import DatabaseBackupService
from version import (
    API_VERSION,
    APP_VERSION,
    MAX_SUPPORTED_SERVER_API_VERSION,
    MIN_SUPPORTED_CLIENT_VERSION,
    MIN_SUPPORTED_SERVER_API_VERSION,
)


logger = logging.getLogger(__name__)


def _compatibility_payload():
    return {
        "api_version": API_VERSION,
        "minimum_server_api_version": MIN_SUPPORTED_SERVER_API_VERSION,
        "maximum_server_api_version": MAX_SUPPORTED_SERVER_API_VERSION,
        "minimum_client_version": MIN_SUPPORTED_CLIENT_VERSION,
    }


class PairingRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    device_name: str = Field(min_length=1, max_length=100)
    deferred_confirmation: bool = False


class MissionaryCreateRequest(BaseModel):
    full_name: str
    missionary_code: str
    preferred_name: str | None = None
    nationality: str | None = None
    passport_number: str | None = None
    arrival_date: date | None = None
    visa_expiration: date | None = None


class MissionaryUpdateRequest(BaseModel):
    fields: dict


class OcrUpdatesRequest(BaseModel):
    document_type: str
    confirmed_data: dict = Field(default_factory=dict)
    auto_update_fields: list | None = None


class ArchiveRequest(BaseModel):
    reason: str | None = None


class ArchiveGroupRequest(BaseModel):
    missionary_ids: list[int]
    group_name: str


class RpcRequest(BaseModel):
    args: list = Field(default_factory=list)
    kwargs: dict = Field(default_factory=dict)


def _rpc_services():
    from services.alert_service import AlertService
    from services.appointment_service import AppointmentService
    from services.dashboard_service import DashboardService
    from services.daily_digest_service import DailyDigestService
    from services.document_service import DocumentService
    from services.missionary_group_service import MissionaryGroupService
    from services.notification_feed_service import NotificationFeedService
    from services.process_automation_service import ProcessAutomationService
    from services.residency_service import ResidencyService
    from services.reports_data_service import ReportsDataService
    from services.secretary_work_service import SecretaryWorkService
    from services.workflow_service import WorkflowService
    from services.workflow_validator import WorkflowValidator

    return {
        "alerts": (AlertService, AlertService.REMOTE_METHODS),
        "appointments": (AppointmentService, AppointmentService.REMOTE_METHODS),
        "dashboard": (DashboardService, DashboardService.REMOTE_METHODS),
        "daily-digest": (DailyDigestService, DailyDigestService.REMOTE_METHODS),
        "documents": (DocumentService, DocumentService.REMOTE_METHODS),
        "missionary-groups": (MissionaryGroupService, MissionaryGroupService.REMOTE_METHODS),
        "notifications": (NotificationFeedService, NotificationFeedService.REMOTE_METHODS),
        "automation": (ProcessAutomationService, ProcessAutomationService.REMOTE_METHODS),
        "residency": (ResidencyService, ResidencyService.REMOTE_METHODS),
        "reports": (ReportsDataService, ReportsDataService.REMOTE_METHODS),
        "secretary-work": (SecretaryWorkService, SecretaryWorkService.REMOTE_METHODS),
        "workflows": (WorkflowService, WorkflowService.REMOTE_METHODS),
        "workflow-validation": (WorkflowValidator, WorkflowValidator.REMOTE_METHODS),
    }


MISSIONARY_DATE_FIELDS = {
    "arrival_date",
    "visa_expiration",
    "residency_expiration",
    "prorroga_expiration",
    "carnet_issue_date",
    "cancelacion_date",
    "date_of_birth",
    "passport_expiration",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
}


def _missionary_fields(payload):
    normalized = dict(payload)
    for field in MISSIONARY_DATE_FIELDS.intersection(normalized):
        value = normalized[field]
        if isinstance(value, str) and value:
            normalized[field] = date.fromisoformat(value)
    return normalized


def _backup(reason, mirror=None):
    service = DatabaseBackupService()
    if not get_database_path().exists():
        return None
    if mirror is None:
        mirror = reason != "hourly"
    result = service.create_snapshot(reason=reason, mirror=mirror)
    service.prune(keep=48, mirror_keep=30)
    return result


def _daily_backup_if_due():
    marker = get_app_data_dir() / "Configuration" / "last-onedrive-backup.txt"
    today = date.today().isoformat()
    try:
        if marker.read_text(encoding="utf-8").strip() == today:
            return None
    except OSError:
        pass
    result = _backup("daily", mirror=True)
    if result is None or result.get("mirrored_path") is None:
        raise RuntimeError("OneDrive backup destination is not configured")
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(today, encoding="utf-8")
    temporary.replace(marker)
    return result


async def _backup_loop(stop_event):
    interval = max(300, int(os.environ.get("MISSION_LEGAL_BACKUP_INTERVAL", "3600")))
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            try:
                await asyncio.to_thread(_backup, "hourly")
                await asyncio.to_thread(_daily_backup_if_due)
            except Exception:
                logger.exception("Scheduled database backup failed")


def create_app(device_store=None, pairing_store=None, manage_lifecycle=True):
    devices = device_store or DeviceCredentialStore()
    pairing = pairing_store or PairingCodeStore()

    @asynccontextmanager
    async def lifespan(_app):
        if not manage_lifecycle:
            yield
            return
        try:
            await asyncio.to_thread(_backup, "pre-migration")
        except Exception:
            logger.exception("Pre-migration database backup failed")
        init_db()
        try:
            await asyncio.to_thread(_daily_backup_if_due)
        except Exception:
            logger.exception("Daily OneDrive database backup failed")
        stop_event = asyncio.Event()
        backup_task = asyncio.create_task(_backup_loop(stop_event))
        try:
            yield
        finally:
            stop_event.set()
            await backup_task
            engine.dispose()
            try:
                await asyncio.to_thread(_backup, "server-shutdown")
            except Exception:
                logger.exception("Server shutdown database backup failed")

    app = FastAPI(
        title="Mission Legal Local API",
        version=API_VERSION,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    def authenticated_device(
        x_device_id: str = Header(default=""),
        x_device_credential: str = Header(default=""),
    ):
        device = devices.authenticate(x_device_id, x_device_credential)
        if not device:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked device credentials",
            )
        return device

    def pairing_confirmation_device(
        x_device_id: str = Header(default=""),
        x_device_credential: str = Header(default=""),
    ):
        device = devices.authenticate(
            x_device_id,
            x_device_credential,
            allow_pending=True,
        )
        if not device:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired pending device credentials",
            )
        return device

    def pending_pairing_device(device=Depends(pairing_confirmation_device)):
        if not device.get("pending_confirmation"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This device registration is already active",
            )
        return device

    @app.get("/health")
    def health():
        database_ok = False
        try:
            with engine.connect() as connection:
                database_ok = connection.execute(text("SELECT 1")).scalar_one() == 1
        except Exception:
            database_ok = False
        if not database_ok:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return {
            "status": "ok",
            "app_version": APP_VERSION,
            "schema_version": get_schema_version(engine),
            **_compatibility_payload(),
        }

    @app.post("/pair", status_code=status.HTTP_201_CREATED)
    def pair(request: PairingRequest):
        claimed, registered = pairing.consume_and_execute(
            request.code,
            lambda: devices.register(
                request.device_name,
                pending_confirmation=request.deferred_confirmation,
            ),
            rollback=lambda result: devices.remove(result["device_id"]),
        )
        if not claimed:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired pairing code",
            )
        return registered

    @app.post("/pair/confirm")
    def confirm_pairing(device=Depends(pairing_confirmation_device)):
        if device.get("pending_confirmation") and not devices.confirm(
            device["device_id"]
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The pending device registration expired",
            )
        return {"device_id": device["device_id"], "confirmed": True}

    @app.delete("/pair/pending")
    def cancel_pairing(device=Depends(pending_pairing_device)):
        removed = devices.remove_pending(device["device_id"])
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The device registration is no longer pending",
            )
        return {
            "device_id": device["device_id"],
            "removed": True,
        }

    @app.get("/v1/session")
    def session(device=Depends(authenticated_device)):
        return {
            "device": device,
            "app_version": APP_VERSION,
            "schema_version": get_schema_version(engine),
            **_compatibility_payload(),
        }

    @app.get("/v1/server/configuration")
    def server_configuration(_device=Depends(authenticated_device)):
        from server.configuration import load_server_configuration

        saved = load_server_configuration()
        return {
            "mission_storage_root": saved.get("mission_storage_root"),
            "backup_configured": bool(saved.get("onedrive_backup_dir")),
        }

    @app.get("/v1/missionaries")
    def missionaries(status_filter: str = "ACTIVE", _device=Depends(authenticated_device)):
        from services.missionary_service import MissionaryService

        service = MissionaryService()
        normalized = status_filter.upper()
        if normalized == "ACTIVE":
            rows = service.get_all_missionaries()
        elif normalized == "ARCHIVED":
            rows = service.get_archived_missionaries()
        elif normalized == "TRASH":
            rows = service.get_trashed()
        else:
            raise HTTPException(status_code=400, detail="Unsupported missionary status")
        extras = ("archive_reason",) if normalized == "ARCHIVED" else ()
        return {"items": [model_snapshot(row, extras) for row in rows]}

    @app.get("/v1/missionaries/{missionary_id}")
    def missionary(missionary_id: int, _device=Depends(authenticated_device)):
        from services.missionary_service import MissionaryService

        row = MissionaryService().get_missionary(missionary_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Missionary not found")
        return model_snapshot(row)

    @app.post("/v1/missionaries", status_code=status.HTTP_201_CREATED)
    def create_missionary(request: MissionaryCreateRequest, _device=Depends(authenticated_device)):
        from services.missionary_service import MissionaryService

        missionary = MissionaryService().create_missionary(**request.model_dump())
        return model_snapshot(missionary)

    @app.patch("/v1/missionaries/{missionary_id}")
    def update_missionary(
        missionary_id: int,
        request: MissionaryUpdateRequest,
        _device=Depends(authenticated_device),
    ):
        from services.missionary_service import MissionaryService

        updated = MissionaryService().update_fields(
            missionary_id, _missionary_fields(request.fields)
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Missionary not found")
        return {"updated": True}

    @app.post("/v1/missionaries/{missionary_id}/archive")
    def archive_missionary(
        missionary_id: int,
        request: ArchiveRequest,
        _device=Depends(authenticated_device),
    ):
        from services.missionary_service import MissionaryService

        result = MissionaryService().archive_missionary(
            missionary_id, archive_reason=request.reason
        )
        return {"archived": bool(result)}

    @app.post("/v1/missionaries/{missionary_id}/trash")
    def trash_missionary(missionary_id: int, _device=Depends(authenticated_device)):
        from services.missionary_service import MissionaryService

        return {"trashed": bool(MissionaryService().delete_missionary(missionary_id))}

    @app.post("/v1/missionaries/{missionary_id}/restore")
    def restore_missionary(missionary_id: int, _device=Depends(authenticated_device)):
        from services.missionary_service import MissionaryService

        return {"restored": bool(MissionaryService().restore_missionary(missionary_id))}

    @app.delete("/v1/missionaries/{missionary_id}")
    def hard_delete_missionary(
        missionary_id: int, _device=Depends(authenticated_device)
    ):
        from services.missionary_service import MissionaryService

        return {"deleted": bool(MissionaryService().hard_delete(missionary_id))}

    @app.post("/v1/missionaries/archive-group")
    def archive_missionary_group(
        request: ArchiveGroupRequest, _device=Depends(authenticated_device)
    ):
        from services.missionary_service import MissionaryService

        path = MissionaryService().archive_missionaries_as_group(
            request.missionary_ids, request.group_name
        )
        if path is None:
            raise HTTPException(status_code=404, detail="No missionaries found")
        return {"package_path": str(path)}

    @app.get("/v1/exports/groups/{group_id}")
    def export_group(group_id: int, _device=Depends(authenticated_device)):
        from services.group_package_export_service import GroupPackageExportService

        export_dir = get_app_data_dir() / "Outgoing"
        export_dir.mkdir(parents=True, exist_ok=True)
        output = export_dir / f"group-{group_id}-{secrets.token_hex(8)}.zip"
        GroupPackageExportService().export_group_package(group_id, output)
        if not output.is_file():
            raise HTTPException(status_code=404, detail="Group export not found")
        return FileResponse(
            output,
            filename=output.name,
            background=BackgroundTask(output.unlink, missing_ok=True),
        )

    @app.get("/v1/rpc/documents/get_documents")
    def document_list(missionary_id: int, _device=Depends(authenticated_device)):
        from services.document_service import DocumentService

        rows = DocumentService().get_documents(missionary_id)
        return {"items": [model_snapshot(row) for row in rows]}

    @app.get("/v1/documents/{document_id}")
    def document(document_id: int, _device=Depends(authenticated_device)):
        from services.document_service import DocumentService

        row = DocumentService().get_document_by_id(document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return model_snapshot(row)

    @app.get("/v1/documents/{document_id}/content")
    def document_content(document_id: int, _device=Depends(authenticated_device)):
        from services.document_service import DocumentService

        row = DocumentService().get_document_by_id(document_id)
        path = Path(row.file_path) if row and row.file_path else None
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Document file not found")
        return FileResponse(path, filename=path.name)

    @app.post("/v1/documents/upload", status_code=status.HTTP_201_CREATED)
    async def upload_document(
        missionary_id: int = Form(),
        document_type: str = Form(),
        workflow_stage: str = Form(),
        ocr_raw_data: str = Form(default=""),
        ocr_confirmed_data: str = Form(default=""),
        notes: str = Form(default=""),
        file: UploadFile = File(),
        _device=Depends(authenticated_device),
    ):
        from services.document_service import DocumentService
        from services.missionary_service import MissionaryService

        missionary = MissionaryService().get_missionary(missionary_id)
        if missionary is None:
            raise HTTPException(status_code=404, detail="Missionary not found")
        incoming = get_app_data_dir() / "Incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file.filename or "upload.bin").name
        temporary = incoming / f"{secrets.token_hex(12)}_{safe_name}"
        try:
            size = 0
            maximum_size = int(
                os.environ.get("MISSION_LEGAL_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024))
            )
            with temporary.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > maximum_size:
                        raise HTTPException(
                            status_code=413,
                            detail="Document exceeds the configured upload limit",
                        )
                    destination.write(chunk)
            row = DocumentService().upload_document(
                missionary,
                temporary,
                document_type,
                workflow_stage,
                ocr_raw_data=ocr_raw_data or None,
                ocr_confirmed_data=ocr_confirmed_data or None,
                notes=notes or None,
            )
            return model_snapshot(row)
        finally:
            temporary.unlink(missing_ok=True)

    @app.post("/v1/documents/{document_id}/apply-updates")
    def apply_document_updates(
        document_id: int,
        request: OcrUpdatesRequest,
        _device=Depends(authenticated_device),
    ):
        from services.document_service import DocumentService
        from services.upload_pipeline import apply_missionary_updates

        document = DocumentService().get_document_by_id(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        fields = apply_missionary_updates(
            document.missionary_id,
            request.document_type,
            document_id,
            request.confirmed_data,
            auto_update_fields=request.auto_update_fields,
        )
        return {"updated_fields": fields}

    @app.post("/v1/rpc/{service_name}/{method_name}")
    def service_rpc(
        service_name: str,
        method_name: str,
        request: RpcRequest,
        _device=Depends(authenticated_device),
    ):
        registration = _rpc_services().get(service_name)
        if registration is None or method_name not in registration[1]:
            raise HTTPException(status_code=404, detail="Service operation not found")
        service_type = registration[0]
        service = service_type()
        args = decode_remote_value(request.args)
        kwargs = decode_remote_value(request.kwargs)
        result = getattr(service, method_name)(*args, **kwargs)
        return {"result": serialize_result(result)}

    return app


app = create_app()
