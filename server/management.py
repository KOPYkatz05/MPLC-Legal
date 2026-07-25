"""Typed server-management operations for the local Windows management pipe.

This module intentionally contains no transport or UI code.  The named-pipe
server gives it an already authenticated request, and this layer applies a
second strict command/argument allowlist before touching server state.
"""

from __future__ import annotations

import ctypes
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from database.runtime import get_app_data_dir
from server.configuration import load_server_configuration
from server.networking import discover_lan_ipv4_addresses, preferred_server_url
from server.security import DeviceCredentialStore, PairingCodeStore
from services.database_backup_service import DatabaseBackupService
from services.pairing_package import PairingPackageError, encode_pairing_package
from version import API_VERSION, APP_VERSION, SCHEMA_VERSION


SERVICE_NAME = "MissionLegalServer"
DEVICE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
COMMAND_ARGUMENTS = {
    "get_status": frozenset(),
    "create_pairing_code": frozenset(),
    "list_devices": frozenset(),
    "revoke_device": frozenset({"device_id"}),
    "create_verified_backup": frozenset(),
    "restart_server": frozenset(),
    "get_support_summary": frozenset(),
}
ALLOWED_COMMANDS = frozenset(COMMAND_ARGUMENTS)
METRIC_FIELDS = (
    "server_process_cpu_percent",
    "server_process_memory_bytes",
    "system_cpu_percent",
    "system_memory_used_bytes",
    "system_memory_total_bytes",
)
API_RUNTIME_STATES = frozenset(
    {"starting", "running", "restarting", "stopping", "unavailable"}
)


class ManagementCommandError(RuntimeError):
    """A safe, user-presentable error returned across the management pipe."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _published_ca_certificate_pem() -> str:
    path = get_app_data_dir() / "Public" / "mission-legal-ca.pem"
    try:
        content = path.read_text(encoding="ascii")
    except OSError as exc:
        raise ManagementCommandError(
            "pairing_material_unavailable",
            "The public pairing certificate is not available yet.",
        ) from exc
    return content


class _WindowsMetricsProvider:
    """Sample current-process and system metrics using only Windows APIs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_process_time = None
        self._last_system_total = None
        self._last_system_idle = None

    @staticmethod
    def _filetime_value(value) -> int:
        return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

    @staticmethod
    def _memory_metrics() -> tuple[int | None, int | None, int | None]:
        if os.name != "nt" or not hasattr(ctypes, "windll"):
            return None, None, None

        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
        kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE

        memory = MemoryStatus()
        memory.dwLength = ctypes.sizeof(memory)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ctypes.WinError(ctypes.get_last_error())

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        current_process = kernel32.GetCurrentProcess()
        get_process_memory = getattr(
            kernel32, "K32GetProcessMemoryInfo", None
        )
        if get_process_memory is None:
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            get_process_memory = psapi.GetProcessMemoryInfo
        get_process_memory.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_process_memory.restype = wintypes.BOOL
        if not get_process_memory(
            current_process, ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        total = int(memory.ullTotalPhys)
        available = int(memory.ullAvailPhys)
        return int(counters.WorkingSetSize), max(0, total - available), total

    @classmethod
    def _cpu_times(cls) -> tuple[int, int, int]:
        if os.name != "nt" or not hasattr(ctypes, "windll"):
            raise OSError("Windows performance counters are unavailable")

        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetSystemTimes.argtypes = [
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetSystemTimes.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL

        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        process_kernel = wintypes.FILETIME()
        process_user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            kernel32.GetCurrentProcess(),
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(process_kernel),
            ctypes.byref(process_user),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        system_idle = cls._filetime_value(idle)
        system_total = cls._filetime_value(kernel) + cls._filetime_value(user)
        process_total = cls._filetime_value(process_kernel) + cls._filetime_value(
            process_user
        )
        return system_idle, system_total, process_total

    def __call__(self) -> dict[str, int | float | None]:
        result = {key: None for key in METRIC_FIELDS}
        if os.name != "nt":
            return result

        try:
            process_memory, system_used, system_total_memory = (
                self._memory_metrics()
            )
            result["server_process_memory_bytes"] = process_memory
            result["system_memory_used_bytes"] = system_used
            result["system_memory_total_bytes"] = system_total_memory
        except Exception:
            pass

        try:
            idle, total, process = self._cpu_times()
            with self._lock:
                if (
                    self._last_system_total is not None
                    and total > self._last_system_total
                ):
                    total_delta = total - self._last_system_total
                    idle_delta = max(0, idle - self._last_system_idle)
                    process_delta = max(0, process - self._last_process_time)
                    result["system_cpu_percent"] = max(
                        0.0,
                        min(100.0, 100.0 * (total_delta - idle_delta) / total_delta),
                    )
                    result["server_process_cpu_percent"] = max(
                        0.0,
                        min(100.0, 100.0 * process_delta / total_delta),
                    )
                self._last_system_idle = idle
                self._last_system_total = total
                self._last_process_time = process
        except Exception:
            pass
        return result


def _safe_metrics(provider: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    empty = {key: None for key in METRIC_FIELDS}
    try:
        supplied = provider()
    except Exception:
        return empty
    if not isinstance(supplied, Mapping):
        return empty

    result = dict(empty)
    for key in ("server_process_cpu_percent", "system_cpu_percent"):
        try:
            value = supplied.get(key)
            if (
                type(value) in {int, float}
                and math.isfinite(value)
                and value >= 0
            ):
                result[key] = min(100.0, float(value))
        except Exception:
            pass
    for key in (
        "server_process_memory_bytes",
        "system_memory_used_bytes",
        "system_memory_total_bytes",
    ):
        try:
            value = supplied.get(key)
            if type(value) is int and value >= 0:
                result[key] = value
        except Exception:
            pass
    return result


def validate_command_arguments(command: Any, arguments: Any) -> dict[str, Any]:
    """Validate a management command without accepting extensible arguments."""

    if not isinstance(command, str) or command not in COMMAND_ARGUMENTS:
        raise ManagementCommandError(
            "unknown_command", "That server-management command is not supported."
        )
    if type(arguments) is not dict:
        raise ManagementCommandError(
            "invalid_arguments", "Command arguments must be a JSON object."
        )

    expected = COMMAND_ARGUMENTS[command]
    actual = frozenset(arguments)
    if actual != expected or any(type(key) is not str for key in arguments):
        raise ManagementCommandError(
            "invalid_arguments",
            "That command contains missing or unsupported arguments.",
        )

    validated = dict(arguments)
    if command == "revoke_device":
        device_id = validated["device_id"]
        if type(device_id) is not str or not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise ManagementCommandError(
                "invalid_device_id",
                "The device identifier must contain exactly 32 hexadecimal characters.",
            )
        validated["device_id"] = device_id.lower()
    return validated


class MissionLegalManagement:
    """Execute the small, fixed set of privileged Server Manager operations."""

    def __init__(
        self,
        *,
        pairing_store: PairingCodeStore | None = None,
        device_store: DeviceCredentialStore | None = None,
        backup_service: DatabaseBackupService | None = None,
        configuration_provider: Callable[[], Mapping[str, Any]] | None = None,
        restart_callback: Callable[[], Any] | None = None,
        state_provider: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        pid_provider: Callable[[], int] | None = None,
        hostname_provider: Callable[[], str] | None = None,
        lan_address_provider: Callable[[], Iterable[str]] | None = None,
        ca_certificate_provider: Callable[[], str] | None = None,
        metrics_provider: Callable[[], Mapping[str, Any]] | None = None,
    ):
        self.pairing_store = (
            PairingCodeStore() if pairing_store is None else pairing_store
        )
        self.device_store = (
            DeviceCredentialStore() if device_store is None else device_store
        )
        self.backup_service = (
            DatabaseBackupService() if backup_service is None else backup_service
        )
        self.configuration_provider = (
            load_server_configuration
            if configuration_provider is None
            else configuration_provider
        )
        self.restart_callback = restart_callback
        self.state_provider = (
            (lambda: "running") if state_provider is None else state_provider
        )
        self.clock = _utcnow if clock is None else clock
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.pid_provider = os.getpid if pid_provider is None else pid_provider
        self.hostname_provider = (
            socket.gethostname if hostname_provider is None else hostname_provider
        )
        self.lan_address_provider = (
            discover_lan_ipv4_addresses
            if lan_address_provider is None
            else lan_address_provider
        )
        self.ca_certificate_provider = (
            _published_ca_certificate_pem
            if ca_certificate_provider is None
            else ca_certificate_provider
        )
        self.metrics_provider = (
            _WindowsMetricsProvider() if metrics_provider is None else metrics_provider
        )
        self._started_at = self.clock()
        self._started_monotonic = self.monotonic()

    def _server_address(self, port: int, hostname: str | None = None) -> str:
        hostname = str(hostname or self.hostname_provider()).strip()
        try:
            addresses = tuple(self.lan_address_provider())
        except Exception:
            addresses = ()
        return preferred_server_url(
            port,
            hostname=hostname,
            addresses=addresses,
        )

    def execute(self, command: str, arguments: Mapping[str, Any] | None = None) -> Any:
        """Validate and execute one allowlisted command."""

        validated = validate_command_arguments(
            command, {} if arguments is None else arguments
        )
        handler = getattr(self, f"_command_{command}")
        return handler(**validated)

    def _configuration(self) -> dict[str, Any]:
        try:
            payload = self.configuration_provider()
        except Exception:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _configured_port(self) -> int:
        try:
            port = int(self._configuration().get("port", 8765))
        except (TypeError, ValueError):
            return 8765
        return port if 1 <= port <= 65535 else 8765

    def _api_runtime_state(self) -> str:
        try:
            state = self.state_provider()
        except Exception:
            return "unavailable"
        if type(state) is not str:
            return "unavailable"
        normalized = state.strip().lower()
        return (
            normalized
            if normalized in API_RUNTIME_STATES
            else "unavailable"
        )

    def _command_get_status(self) -> dict[str, Any]:
        configuration = self._configuration()
        try:
            port = int(configuration.get("port", 8765))
        except (TypeError, ValueError):
            port = 8765
        if not 1 <= port <= 65535:
            port = 8765
        database_path = getattr(self.backup_service, "database_path", None)
        database_file_present = bool(
            database_path and Path(database_path).is_file()
        )
        hostname = str(self.hostname_provider())
        status = {
            "state": self._api_runtime_state(),
            "service_name": SERVICE_NAME,
            "pid": int(self.pid_provider()),
            "hostname": hostname,
            "app_version": APP_VERSION,
            "api_version": API_VERSION,
            "schema_version": SCHEMA_VERSION,
            "started_at": _isoformat_utc(self._started_at),
            "uptime_seconds": max(
                0, int(self.monotonic() - self._started_monotonic)
            ),
            "host": str(configuration.get("host") or "0.0.0.0"),
            "port": port,
            "server_address": self._server_address(port, hostname),
            "database_file_present": database_file_present,
        }
        status.update(_safe_metrics(self.metrics_provider))
        return status

    def _command_create_pairing_code(self) -> dict[str, Any]:
        pairing = self.pairing_store.create()
        code = pairing.get("code")
        expires_at = pairing.get("expires_at")
        if (
            type(code) is not str
            or not re.fullmatch(r"\d{6}", code)
            or not isinstance(expires_at, datetime)
        ):
            raise ManagementCommandError(
                "pairing_failed", "The server could not create a pairing code."
            )
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        comparable_expiry = expires_at
        if comparable_expiry.tzinfo is None:
            comparable_expiry = comparable_expiry.replace(tzinfo=timezone.utc)
        lifetime_seconds = max(
            0,
            int((comparable_expiry - now).total_seconds()),
        )
        expires_at_text = _isoformat_utc(expires_at)
        port = self._configured_port()
        server_address = self._server_address(port)
        try:
            setup_code = encode_pairing_package(
                server_url=server_address,
                ca_certificate_pem=self.ca_certificate_provider(),
                pairing_code=code,
                expires_at=expires_at_text,
            )
        except (OSError, PairingPackageError, TypeError, ValueError) as exc:
            raise ManagementCommandError(
                "pairing_material_unavailable",
                "The server could not prepare the automatic client setup code.",
            ) from exc
        return {
            "code": code,
            "setup_code": setup_code,
            "server_address": server_address,
            "expires_at": expires_at_text,
            "lifetime_seconds": lifetime_seconds,
        }

    def _device_payload(self) -> list[dict[str, Any]]:
        devices = []
        for item in self.device_store.list_devices():
            if not isinstance(item, Mapping):
                continue
            device_id = item.get("device_id")
            if type(device_id) is not str or not DEVICE_ID_PATTERN.fullmatch(device_id):
                continue
            pending = bool(item.get("pending_confirmation"))
            revoked_at = item.get("revoked_at")
            state = "revoked" if revoked_at else "pending" if pending else "active"
            devices.append(
                {
                    "device_id": device_id.lower(),
                    "device_name": str(item.get("device_name") or "Unnamed computer"),
                    "created_at": item.get("created_at"),
                    "revoked_at": revoked_at,
                    "pending_confirmation": pending,
                    "state": state,
                }
            )
        devices.sort(
            key=lambda item: (
                {"active": 0, "pending": 1, "revoked": 2}[item["state"]],
                item["device_name"].casefold(),
                item["device_id"],
            )
        )
        return devices

    def _command_list_devices(self) -> dict[str, Any]:
        return {"devices": self._device_payload()}

    def _command_revoke_device(self, device_id: str) -> dict[str, Any]:
        if not self.device_store.revoke(device_id):
            raise ManagementCommandError(
                "device_not_found",
                "That device was not found or had already been revoked.",
            )
        return {"device_id": device_id, "revoked": True}

    def _command_create_verified_backup(self) -> dict[str, Any]:
        try:
            snapshot = self.backup_service.create_snapshot(
                reason="server-manager-manual", mirror=True
            )
            path = Path(snapshot["path"])
            self.backup_service.verify(path)
            metadata = snapshot.get("metadata") or {}
            size_bytes = int(metadata.get("size", path.stat().st_size))
        except ManagementCommandError:
            raise
        except Exception as exc:
            raise ManagementCommandError(
                "backup_failed",
                "The server could not create and verify a database backup.",
            ) from exc

        return {
            "created_at": str(metadata.get("created_at") or ""),
            "filename": path.name,
            "size_bytes": size_bytes,
            "sha256": str(metadata.get("sha256") or ""),
            "mirrored": bool(snapshot.get("mirrored_path")),
        }

    def _command_restart_server(self) -> dict[str, Any]:
        if self.restart_callback is None:
            raise ManagementCommandError(
                "restart_unavailable",
                "Server restart is not available in this runtime.",
            )
        try:
            self.restart_callback()
        except ManagementCommandError:
            raise
        except Exception as exc:
            raise ManagementCommandError(
                "restart_failed", "The server could not schedule a restart."
            ) from exc
        return {"accepted": True}

    def _latest_backup(self) -> dict[str, Any] | None:
        backup_dir = getattr(self.backup_service, "local_backup_dir", None)
        if backup_dir is None:
            return None
        try:
            candidates = sorted(
                Path(backup_dir).glob("mission-legal_*.db"),
                key=lambda path: path.name,
                reverse=True,
            )
            if not candidates:
                return None
            path = candidates[0]
            created_at = ""
            metadata_path = path.with_suffix(".json")
            if metadata_path.is_file():
                import json

                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    created_at = str(payload.get("created_at") or "")
            return {
                "filename": path.name,
                "created_at": created_at,
                "size_bytes": path.stat().st_size,
            }
        except Exception:
            return None

    def _command_get_support_summary(self) -> dict[str, Any]:
        devices = self._device_payload()
        counts = {"active": 0, "pending": 0, "revoked": 0, "total": len(devices)}
        for device in devices:
            counts[device["state"]] += 1
        return {
            "generated_at": _isoformat_utc(self.clock()),
            "status": self._command_get_status(),
            "device_counts": counts,
            "latest_backup": self._latest_backup(),
        }
