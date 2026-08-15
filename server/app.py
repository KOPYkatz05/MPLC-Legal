import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

# Importing this module means the process is the authoritative server. Business
# services invoked by API routes must never proxy back into the API recursively,
# even if the interactive Windows profile has client settings configured.
os.environ["MISSION_LEGAL_SERVER_PROCESS"] = "1"

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from packaging.version import InvalidVersion, Version
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import text

from database.db import engine, init_db
from database.runtime import get_app_data_dir, get_database_path
from database.schema import get_schema_version
from server.security import DeviceCredentialStore, PairingCodeStore
from server.serialization import model_snapshot, serialize_result
from services.lan_discovery import certificate_sha256
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


DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _canonical_upload_id(value):
    try:
        return str(uuid.UUID(str(value).strip()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_upload_id"},
        ) from exc


def _maximum_upload_bytes():
    try:
        configured = int(
            os.environ.get(
                "MISSION_LEGAL_MAX_UPLOAD_BYTES",
                str(DEFAULT_MAX_UPLOAD_BYTES),
            )
        )
    except (TypeError, ValueError):
        configured = DEFAULT_MAX_UPLOAD_BYTES
    return configured if configured > 0 else DEFAULT_MAX_UPLOAD_BYTES


def _validate_upload_request(
    *,
    document_type,
    workflow_stage,
    filename,
    upload_id,
    content_sha256,
    file_size,
    supersedes_document_id,
):
    from utils.constants import DOCUMENTS, WORKFLOW_STAGES
    from utils.document_files import SUPPORTED_DOCUMENT_EXTENSIONS

    if document_type not in DOCUMENTS:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_document_type"},
        )
    allowed_stages = {"GENERAL", "DNI", *WORKFLOW_STAGES}
    if workflow_stage not in allowed_stages:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_workflow_stage"},
        )
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail={"code": "unsupported_document_extension"},
        )
    if upload_id in (None, ""):
        raise HTTPException(
            status_code=422,
            detail={"code": "missing_upload_id"},
        )
    normalized_upload_id = _canonical_upload_id(upload_id)
    if content_sha256 in (None, ""):
        raise HTTPException(
            status_code=422,
            detail={"code": "missing_content_sha256"},
        )
    normalized_sha256 = str(content_sha256).strip().lower()
    if len(normalized_sha256) != 64 or any(
        character not in "0123456789abcdef"
        for character in normalized_sha256
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_content_sha256"},
        )
    if file_size is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "missing_file_size"},
        )
    if file_size < 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_file_size"},
        )
    if supersedes_document_id is not None and supersedes_document_id <= 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_replacement_target"},
        )
    return normalized_upload_id, normalized_sha256


def _stream_upload_to_path(source, destination_path, maximum_size):
    size = 0
    digest = hashlib.sha256()
    source.seek(0)
    with Path(destination_path).open("xb") as destination:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > maximum_size:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "upload_too_large"},
                )
            digest.update(chunk)
            destination.write(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    return size, digest.hexdigest()


def _document_storage_http_error(error):
    from services.document_storage_service import (
        AMBIGUOUS,
        CLOUD_UNAVAILABLE,
        MISSING,
        UNREADABLE,
    )

    status_code = {
        MISSING: 404,
        AMBIGUOUS: 409,
        CLOUD_UNAVAILABLE: 503,
        UNREADABLE: 503,
    }.get(error.code, 422)
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "document_id": error.document_id},
    )


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


class MissionaryRowColorRequest(BaseModel):
    color: str


class ServerConfigurationUpdateRequest(BaseModel):
    interpol_area_office_address: str = ""
    interpol_secretary_phone: str = ""


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
    from services.client_view_service import ClientViewService
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
        "client-views": (ClientViewService, ClientViewService.REMOTE_METHODS),
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
    "release_date",
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


def create_app(
    device_store=None,
    pairing_store=None,
    manage_lifecycle=True,
    network_trust_provider=None,
):
    devices = device_store or DeviceCredentialStore()
    pairing = pairing_store or PairingCodeStore()
    if network_trust_provider is None:
        if manage_lifecycle:
            from server.trusted_networks import TrustedNetworkStore

            network_trust_provider = TrustedNetworkStore().is_current_trusted
        else:
            # Explicit lifecycle-free apps are test/in-process instances.
            network_trust_provider = lambda: True

    @asynccontextmanager
    async def lifespan(_app):
        if not manage_lifecycle:
            yield
            return
        from database.migrations.runner import migration_required

        database_needs_migration = False
        if get_database_path().exists():
            database_needs_migration = await asyncio.to_thread(
                migration_required,
                engine,
            )
        if database_needs_migration:
            # A verified local backup is mandatory before either applying a
            # migration or adopting an existing database into the ledger. The
            # daily OneDrive mirror remains an independent best-effort task.
            await asyncio.to_thread(_backup, "pre-migration", False)
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
        x_client_version: str = Header(default=""),
    ):
        device = devices.authenticate(x_device_id, x_device_credential)
        if not device:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked device credentials",
            )
        try:
            client_version = Version(str(x_client_version).strip())
            minimum_version = Version(MIN_SUPPORTED_CLIENT_VERSION)
        except InvalidVersion as exc:
            raise HTTPException(
                status_code=status.HTTP_426_UPGRADE_REQUIRED,
                detail={
                    "code": "client_update_required",
                    "minimum_client_version": MIN_SUPPORTED_CLIENT_VERSION,
                },
            ) from exc
        if client_version < minimum_version:
            raise HTTPException(
                status_code=status.HTTP_426_UPGRADE_REQUIRED,
                detail={
                    "code": "client_update_required",
                    "minimum_client_version": MIN_SUPPORTED_CLIENT_VERSION,
                },
            )
        return device

    def pairing_network_allowed(request: Request):
        client_host = str(request.client.host if request.client else "").strip()
        try:
            client_address = ipaddress.ip_address(client_host)
        except ValueError:
            client_address = None
        if client_address is not None and client_address.is_loopback:
            return True
        try:
            trusted = bool(network_trust_provider())
        except Exception:
            trusted = False
        if not trusted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "New-device pairing is disabled until the server trusts "
                    "its current network"
                ),
            )
        return True

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

    @app.get("/pair/bootstrap")
    def pairing_bootstrap():
        """Publish only the public CA used by trusted-LAN discovery."""

        public_ca = (
            get_app_data_dir() / "Public" / "mission-legal-ca.pem"
        )
        if not public_ca.is_file():
            from server.tls import default_tls_paths

            public_ca = default_tls_paths()["ca_cert"]
        try:
            certificate = public_ca.read_text(encoding="ascii")
            fingerprint = certificate_sha256(certificate)
        except (OSError, UnicodeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Pairing certificate unavailable",
            ) from exc
        return {
            "server_id": fingerprint,
            "ca_sha256": fingerprint,
            "ca_certificate_pem": certificate,
        }

    @app.post("/pair", status_code=status.HTTP_201_CREATED)
    def pair(
        request: PairingRequest,
        _network_allowed=Depends(pairing_network_allowed),
    ):
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
            "interpol_area_office_address": saved.get(
                "interpol_area_office_address", ""
            ),
            "interpol_secretary_phone": saved.get(
                "interpol_secretary_phone", ""
            ),
        }

    @app.patch("/v1/server/configuration")
    def update_server_configuration(
        request: ServerConfigurationUpdateRequest,
        _device=Depends(authenticated_device),
    ):
        from server.configuration import (
            load_server_configuration,
            save_server_configuration,
        )

        saved = load_server_configuration()
        saved["interpol_area_office_address"] = (
            request.interpol_area_office_address.strip()
        )
        saved["interpol_secretary_phone"] = (
            request.interpol_secretary_phone.strip()
        )
        save_server_configuration(saved)
        return {
            "interpol_area_office_address": saved[
                "interpol_area_office_address"
            ],
            "interpol_secretary_phone": saved["interpol_secretary_phone"],
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

    @app.post("/v1/dynamics-roster/preview")
    async def dynamics_roster_preview(file: UploadFile = File(...), _device=Depends(authenticated_device)):
        from services.dynamics_roster_service import DynamicsRosterError, DynamicsRosterService
        try:
            return DynamicsRosterService().preview(await file.read(), file.filename or "")
        except DynamicsRosterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/dynamics-roster/apply")
    async def dynamics_roster_apply(
        file: UploadFile = File(...),
        preview_id: str = Form(...),
        resolutions: str = Form("{}"),
        device=Depends(authenticated_device),
    ):
        from services.dynamics_roster_service import DynamicsRosterError, DynamicsRosterService
        try:
            resolution_map = json.loads(resolutions)
            if not isinstance(resolution_map, dict):
                raise ValueError
            return DynamicsRosterService().apply(
                await file.read(),
                file.filename or "",
                preview_id,
                resolution_map,
                applying_device=device.get("device_id"),
            )
        except (DynamicsRosterError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/dynamics-roster/last")
    def dynamics_roster_last(_device=Depends(authenticated_device)):
        from services.dynamics_roster_service import DynamicsRosterService

        return {"item": DynamicsRosterService().last_import()}

    @app.patch("/v1/missionaries/{missionary_id}/row-color")
    def set_missionary_row_color(
        missionary_id: int,
        request: MissionaryRowColorRequest,
        _device=Depends(authenticated_device),
    ):
        from services.missionary_service import MissionaryService

        try:
            missionary = MissionaryService().set_missionary_row_color(
                missionary_id, request.color
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if missionary is None:
            raise HTTPException(status_code=404, detail="Missionary not found")
        return model_snapshot(missionary)

    @app.delete("/v1/missionaries/{missionary_id}/row-color")
    def clear_missionary_row_color(missionary_id: int, _device=Depends(authenticated_device)):
        from services.missionary_service import MissionaryService

        missionary = MissionaryService().clear_missionary_row_color(missionary_id)
        if missionary is None:
            raise HTTPException(status_code=404, detail="Missionary not found")
        return model_snapshot(missionary)

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

    @app.get("/v1/document-uploads/{upload_id}")
    async def document_by_upload_id(
        upload_id: str,
        _device=Depends(authenticated_device),
    ):
        from services.document_service import DocumentService
        from services.document_storage_service import (
            DocumentStorageError,
            UNREADABLE,
            resolve_document_path,
        )
        from utils.document_files import sha256_file

        normalized_upload_id = _canonical_upload_id(upload_id)
        service = DocumentService()
        row = await run_in_threadpool(
            service.get_document_by_upload_id,
            normalized_upload_id,
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "upload_not_found",
                    "upload_id": normalized_upload_id,
                },
            )
        try:
            resolved_path = await run_in_threadpool(resolve_document_path, row.id)
            actual_size = await run_in_threadpool(
                lambda: Path(resolved_path).stat().st_size
            )
            if row.file_size is not None and actual_size != int(row.file_size):
                raise DocumentStorageError(UNREADABLE, row.id)
            if row.content_sha256:
                actual_sha256 = await run_in_threadpool(
                    sha256_file,
                    resolved_path,
                )
                if actual_sha256 != str(row.content_sha256).lower():
                    raise DocumentStorageError(UNREADABLE, row.id)
        except DocumentStorageError as error:
            raise _document_storage_http_error(error) from error
        if getattr(row, "post_processing_status", None) in {
            "PENDING",
            "RETRY_REQUIRED",
        }:
            # Reconciliation can repair the narrow crash window after a commit,
            # but only after the exact committed bytes have been verified.
            row = await run_in_threadpool(
                service._run_post_processing_best_effort,
                row,
            )
        payload = model_snapshot(row)
        payload["file_path"] = str(resolved_path)
        return payload

    @app.get("/v1/documents/{document_id}")
    def document(document_id: int, _device=Depends(authenticated_device)):
        from services.document_service import DocumentService

        row = DocumentService().get_document_by_id(document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return model_snapshot(row)

    @app.get("/v1/documents/{document_id}/content")
    def document_content(document_id: int, _device=Depends(authenticated_device)):
        from services.document_storage_service import (
            DocumentStorageError,
            resolve_document_path,
        )

        try:
            path = resolve_document_path(document_id)
        except DocumentStorageError as error:
            raise _document_storage_http_error(error) from error
        return FileResponse(path, filename=path.name)

    @app.get("/v1/documents/{document_id}/thumbnail")
    def document_thumbnail(document_id: int, _device=Depends(authenticated_device)):
        from services.document_thumbnail_service import DocumentThumbnailService
        from services.document_storage_service import (
            DocumentStorageError,
            UNREADABLE,
            resolve_document_path,
        )
        from services.document_service import DocumentService

        try:
            path = resolve_document_path(document_id)
            row = DocumentService().get_document_by_id(document_id)
            row.file_path = str(path)
            thumbnail = DocumentThumbnailService().get_thumbnail(row)
            if thumbnail is None:
                raise DocumentStorageError(UNREADABLE, document_id)
        except DocumentStorageError as error:
            raise _document_storage_http_error(error) from error
        except Exception as error:
            logger.exception("Document thumbnail rendering failed for %s", document_id)
            raise _document_storage_http_error(
                DocumentStorageError(UNREADABLE, document_id)
            ) from error
        return FileResponse(thumbnail, media_type="image/jpeg")

    @app.post("/v1/documents/upload", status_code=status.HTTP_201_CREATED)
    async def upload_document(
        missionary_id: int = Form(),
        document_type: str = Form(),
        workflow_stage: str = Form(),
        ocr_raw_data: str = Form(default=""),
        ocr_confirmed_data: str = Form(default=""),
        notes: str = Form(default=""),
        upload_id: str | None = Form(default=None),
        content_sha256: str | None = Form(default=None),
        file_size: int | None = Form(default=None),
        supersedes_document_id: int | None = Form(default=None),
        file: UploadFile = File(),
        _device=Depends(authenticated_device),
    ):
        from services.document_service import (
            DocumentService,
            DocumentReplacementError,
            DocumentUploadConflictError,
        )
        from services.missionary_service import MissionaryService

        upload_id, content_sha256 = _validate_upload_request(
            document_type=document_type,
            workflow_stage=workflow_stage,
            filename=file.filename,
            upload_id=upload_id,
            content_sha256=content_sha256,
            file_size=file_size,
            supersedes_document_id=supersedes_document_id,
        )
        missionary = await run_in_threadpool(
            MissionaryService().get_missionary,
            missionary_id,
        )
        if missionary is None:
            raise HTTPException(status_code=404, detail="Missionary not found")
        incoming = get_app_data_dir() / "Incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        file_extension = Path(file.filename or "").suffix.lower()
        temporary = incoming / f"{secrets.token_hex(12)}{file_extension}"
        try:
            size, actual_sha256 = await run_in_threadpool(
                _stream_upload_to_path,
                file.file,
                temporary,
                _maximum_upload_bytes(),
            )
            if size <= 0:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "empty_upload"},
                )
            if file_size is not None and file_size != size:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "file_size_mismatch",
                        "expected": file_size,
                        "actual": size,
                    },
                )
            if content_sha256 is not None and content_sha256 != actual_sha256:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "content_sha256_mismatch"},
                )
            try:
                row = await run_in_threadpool(
                    DocumentService().upload_document,
                    missionary,
                    temporary,
                    document_type,
                    workflow_stage,
                    ocr_raw_data=ocr_raw_data or None,
                    ocr_confirmed_data=ocr_confirmed_data or None,
                    notes=notes or None,
                    upload_id=upload_id,
                    content_sha256=actual_sha256,
                    file_size=size,
                    supersedes_document_id=supersedes_document_id,
                )
            except DocumentUploadConflictError as error:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "upload_conflict", "message": str(error)},
                ) from error
            except DocumentReplacementError as error:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "replacement_conflict",
                        "message": str(error),
                    },
                ) from error
            except ValueError as error:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "invalid_document_file",
                        "message": str(error),
                    },
                ) from error
            return model_snapshot(row)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not remove temporary incoming upload %s",
                    temporary,
                    exc_info=True,
                )
            try:
                await file.close()
            except Exception:
                logger.warning(
                    "Could not close incoming upload %s",
                    temporary,
                    exc_info=True,
                )

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
        if request.document_type != document.document_type:
            raise HTTPException(
                status_code=409,
                detail={"code": "document_type_mismatch"},
            )
        fields = apply_missionary_updates(
            document.missionary_id,
            document.document_type,
            document_id,
            request.confirmed_data,
            auto_update_fields=request.auto_update_fields,
        )
        return {"updated_fields": fields}

    @app.post("/v1/documents/{document_id}/retry-post-processing")
    async def retry_document_post_processing(
        document_id: int,
        _device=Depends(authenticated_device),
    ):
        from services.document_service import DocumentService
        from services.document_storage_service import DocumentStorageError

        service = DocumentService()
        document = await run_in_threadpool(
            service.get_document_by_id,
            document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        try:
            await run_in_threadpool(
                service._verify_committed_upload_file,
                document,
            )
        except DocumentStorageError as error:
            raise _document_storage_http_error(error) from error
        # The service deliberately returns the committed record with
        # RETRY_REQUIRED/PENDING when follow-up fails. Upload durability is not
        # converted into an HTTP failure by ancillary database work.
        document = await run_in_threadpool(
            service._run_post_processing_best_effort,
            document,
        )
        return model_snapshot(document)

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
        try:
            result = getattr(service, method_name)(*args, **kwargs)
        except Exception as exc:
            from services.secretary_work_service import (
                SecretaryWorkError,
                TaskBoardCompatibilityError,
            )
            if method_name == "save_task_board_orders" and isinstance(
                exc, TaskBoardCompatibilityError
            ):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if method_name == "save_task_board_orders" and isinstance(
                exc, SecretaryWorkError
            ):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise
        return {"result": serialize_result(result)}

    return app


app = create_app()
