"""Authenticated local named-pipe transport for Mission Legal Server Manager."""

from __future__ import annotations

import ctypes
import json
import math
import re
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from server.management import (
    ManagementCommandError,
    MissionLegalManagement,
    validate_command_arguments,
)


PIPE_NAME = r"\\.\pipe\MissionLegal.ServerManager.v1"
SERVICE_NAME = "MissionLegalServer"
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024
SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
FILE_READ_DATA = 0x00000001
FILE_WRITE_DATA = 0x00000002
FILE_APPEND_DATA = 0x00000004
FILE_READ_EA = 0x00000008
FILE_READ_ATTRIBUTES = 0x00000080
READ_CONTROL = 0x00020000
SYNCHRONIZE = 0x00100000
# Synchronous named-pipe opens require the expanded FILE_GENERIC_READ support
# rights. Enumerate every bit so the write side remains only FILE_WRITE_DATA;
# GENERIC_WRITE would also map FILE_APPEND_DATA to FILE_CREATE_PIPE_INSTANCE.
PIPE_CLIENT_DATA_ACCESS = (
    FILE_READ_DATA
    | FILE_WRITE_DATA
    | FILE_READ_EA
    | FILE_READ_ATTRIBUTES
    | READ_CONTROL
    | SYNCHRONIZE
)
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
ACCEPT_BACKOFF_INITIAL_SECONDS = 0.05
ACCEPT_BACKOFF_MAX_SECONDS = 2.0
_REQUEST_FIELDS = frozenset({"protocol", "request_id", "command", "arguments"})
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SID_PATTERN = re.compile(r"^S-1-\d+(?:-\d+)+$")
_ERROR_PIPE_CONNECTED = 535
_ERROR_BROKEN_PIPE = 109
_ERROR_NO_DATA = 232
_SE_GROUP_ENABLED = 0x00000004
_SE_GROUP_USE_FOR_DENY_ONLY = 0x00000010


class ManagementProtocolError(RuntimeError):
    """The peer sent malformed, oversized, or inconsistent protocol data."""


class ManagementTransportError(RuntimeError):
    """The trusted local management pipe could not be reached or verified."""


class _PipeAcceptError(ManagementTransportError):
    """Creating or accepting the trusted pipe instance failed."""


class RemoteManagementCommandError(RuntimeError):
    """The server safely rejected or failed an allowlisted management command."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PipeClientIdentity:
    user_sid: str
    enabled_group_sids: frozenset[str] = frozenset()


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManagementProtocolError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ManagementProtocolError(f"Invalid JSON constant: {value}")


def _strict_json_loads(payload: bytes) -> Any:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ManagementProtocolError("Management messages must be valid UTF-8.") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ManagementProtocolError:
        raise
    except json.JSONDecodeError as exc:
        raise ManagementProtocolError("Management message contains invalid JSON.") from exc


def encode_json_frame(payload: Any) -> bytes:
    try:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManagementProtocolError(
            "Management response is not valid JSON."
        ) from exc
    if not body or len(body) > MAX_MESSAGE_BYTES:
        raise ManagementProtocolError(
            f"Management message exceeds the {MAX_MESSAGE_BYTES}-byte limit."
        )
    return struct.pack(">I", len(body)) + body


def _read_exact(read: Callable[[int], bytes], length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining:
        chunk = read(remaining)
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise ManagementProtocolError("Pipe reader returned invalid data.")
        chunk = bytes(chunk)
        if not chunk:
            raise ManagementProtocolError("The management pipe closed unexpectedly.")
        if len(chunk) > remaining:
            raise ManagementProtocolError("Pipe reader returned too much data.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_json_frame(read: Callable[[int], bytes]) -> Any:
    length = struct.unpack(">I", _read_exact(read, 4))[0]
    if length < 1 or length > MAX_MESSAGE_BYTES:
        raise ManagementProtocolError(
            f"Management message length must be between 1 and {MAX_MESSAGE_BYTES} bytes."
        )
    return _strict_json_loads(_read_exact(read, length))


def _validate_request(payload: Any) -> tuple[str, str, dict[str, Any]]:
    if type(payload) is not dict or frozenset(payload) != _REQUEST_FIELDS:
        raise ManagementProtocolError(
            "Management requests must contain only protocol, request_id, command, and arguments."
        )
    if type(payload["protocol"]) is not int or payload["protocol"] != PROTOCOL_VERSION:
        raise ManagementProtocolError("Unsupported management protocol version.")
    request_id = payload["request_id"]
    if type(request_id) is not str or not _REQUEST_ID_PATTERN.fullmatch(request_id):
        raise ManagementProtocolError("Management request_id is invalid.")
    command = payload["command"]
    try:
        arguments = validate_command_arguments(command, payload["arguments"])
    except ManagementCommandError as exc:
        raise ManagementProtocolError(exc.message) from exc
    return request_id, command, arguments


def _safe_request_id(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    request_id = payload.get("request_id")
    if type(request_id) is str and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return None


def process_request(payload: Any, management: MissionLegalManagement) -> dict[str, Any]:
    """Validate and execute one decoded request, always returning a safe response."""

    request_id = _safe_request_id(payload)
    try:
        request_id, command, arguments = _validate_request(payload)
        result = management.execute(command, arguments)
    except ManagementProtocolError as exc:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "error": {"code": "invalid_request", "message": str(exc)},
        }
    except ManagementCommandError as exc:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "error": {"code": exc.code, "message": exc.message},
        }
    except Exception:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "error": {
                "code": "command_failed",
                "message": "The server could not complete that management command.",
            },
        }
    return {
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
        "ok": True,
        "result": result,
    }


def _is_authorized_client(
    identity: PipeClientIdentity, operator_sid: str
) -> bool:
    if identity.user_sid in {SYSTEM_SID, operator_sid}:
        return True
    return ADMINISTRATORS_SID in identity.enabled_group_sids


def _validate_operator_sid(operator_sid: Any) -> str:
    if (
        type(operator_sid) is not str
        or len(operator_sid) > 184
        or not _SID_PATTERN.fullmatch(operator_sid)
    ):
        raise ValueError("operator_sid must be a valid Windows SID string")
    return operator_sid


def _load_pywin32():
    try:
        import pywintypes
        import win32api
        import win32con
        import win32file
        import win32pipe
        import win32security
        import win32service
    except ImportError as exc:
        raise ManagementTransportError(
            "Mission Legal Server Manager requires pywin32 on Windows."
        ) from exc
    return (
        pywintypes,
        win32api,
        win32con,
        win32file,
        win32pipe,
        win32security,
        win32service,
    )


def _winerror(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if isinstance(value, int):
        return value
    if getattr(exc, "args", None) and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def _create_pipe_security_attributes(
    operator_sid: str,
    *,
    pywintypes,
    win32con,
    win32security,
):
    """Build a non-inheriting DACL for SYSTEM, Administrators, and one operator."""

    operator_sid = _validate_operator_sid(operator_sid)
    sid_objects = {}
    for sid_string in dict.fromkeys((SYSTEM_SID, ADMINISTRATORS_SID, operator_sid)):
        sid = win32security.ConvertStringSidToSid(sid_string)
        validator = getattr(win32security, "IsValidSid", None)
        is_valid = validator(sid) if validator is not None else sid.IsValid()
        if not is_valid:
            raise ValueError(f"Invalid Windows SID: {sid_string}")
        sid_objects[sid_string] = sid

    dacl = win32security.ACL()
    privileged_access = win32con.GENERIC_READ | win32con.GENERIC_WRITE
    for sid_string in (SYSTEM_SID, ADMINISTRATORS_SID):
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            privileged_access,
            sid_objects[sid_string],
        )
    if operator_sid not in {SYSTEM_SID, ADMINISTRATORS_SID}:
        # FILE_APPEND_DATA is FILE_CREATE_PIPE_INSTANCE for named pipes. The
        # enrolled operator may exchange data but must never create a competing
        # instance in the trusted pipe namespace.
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            PIPE_CLIENT_DATA_ACCESS,
            sid_objects[operator_sid],
        )
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.bInheritHandle = False
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


class _WindowsPipeServerApi:
    def __init__(self, operator_sid: str):
        (
            self.pywintypes,
            self.win32api,
            self.win32con,
            self.win32file,
            self.win32pipe,
            self.win32security,
            _win32service,
        ) = _load_pywin32()
        self.operator_sid = _validate_operator_sid(operator_sid)

    def create(self):
        security_attributes = _create_pipe_security_attributes(
            self.operator_sid,
            pywintypes=self.pywintypes,
            win32con=self.win32con,
            win32security=self.win32security,
        )
        pipe_mode = (
            self.win32pipe.PIPE_TYPE_BYTE
            | self.win32pipe.PIPE_READMODE_BYTE
            | self.win32pipe.PIPE_WAIT
            | PIPE_REJECT_REMOTE_CLIENTS
        )
        return self.win32pipe.CreateNamedPipe(
            PIPE_NAME,
            self.win32pipe.PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
            pipe_mode,
            self.win32pipe.PIPE_UNLIMITED_INSTANCES,
            MAX_MESSAGE_BYTES + 4,
            MAX_MESSAGE_BYTES + 4,
            5000,
            security_attributes,
        )

    def connect(self, handle):
        try:
            self.win32pipe.ConnectNamedPipe(handle, None)
        except self.pywintypes.error as exc:
            if _winerror(exc) != _ERROR_PIPE_CONNECTED:
                raise

    def client_identity(self, handle) -> PipeClientIdentity:
        self.win32security.ImpersonateNamedPipeClient(handle)
        token = None
        try:
            token = self.win32security.OpenThreadToken(
                self.win32api.GetCurrentThread(),
                self.win32con.TOKEN_QUERY,
                True,
            )
            user_sid = self.win32security.GetTokenInformation(
                token, self.win32security.TokenUser
            )[0]
            user_sid_string = self.win32security.ConvertSidToStringSid(user_sid)
            enabled_groups = set()
            for group_sid, attributes in self.win32security.GetTokenInformation(
                token, self.win32security.TokenGroups
            ):
                if (
                    attributes & _SE_GROUP_ENABLED
                    and not attributes & _SE_GROUP_USE_FOR_DENY_ONLY
                ):
                    enabled_groups.add(
                        self.win32security.ConvertSidToStringSid(group_sid)
                    )
            return PipeClientIdentity(
                user_sid=user_sid_string,
                enabled_group_sids=frozenset(enabled_groups),
            )
        finally:
            if token is not None:
                self.win32api.CloseHandle(token)
            self.win32security.RevertToSelf()

    def read(self, handle, length: int) -> bytes:
        try:
            _status, data = self.win32file.ReadFile(handle, length)
        except self.pywintypes.error as exc:
            if _winerror(exc) in {_ERROR_BROKEN_PIPE, _ERROR_NO_DATA}:
                return b""
            raise
        return bytes(data)

    def write(self, handle, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            _status, written = self.win32file.WriteFile(handle, remaining.tobytes())
            if not isinstance(written, int) or written <= 0:
                raise ManagementTransportError(
                    "The management pipe could not write its response."
                )
            remaining = remaining[written:]

    def finish(self, handle) -> None:
        try:
            self.win32file.FlushFileBuffers(handle)
        except self.pywintypes.error:
            pass
        try:
            self.win32pipe.DisconnectNamedPipe(handle)
        except self.pywintypes.error:
            pass

    def close(self, handle) -> None:
        self.win32file.CloseHandle(handle)


class MissionLegalManagementPipeServer:
    """Serve authenticated management requests from the Windows service process."""

    def __init__(
        self,
        management: MissionLegalManagement,
        *,
        operator_sid: str,
        pipe_api=None,
        accept_backoff_initial_seconds: float = ACCEPT_BACKOFF_INITIAL_SECONDS,
        accept_backoff_max_seconds: float = ACCEPT_BACKOFF_MAX_SECONDS,
    ):
        if (
            type(accept_backoff_initial_seconds) not in {int, float}
            or type(accept_backoff_max_seconds) not in {int, float}
            or not math.isfinite(accept_backoff_initial_seconds)
            or not math.isfinite(accept_backoff_max_seconds)
            or accept_backoff_initial_seconds <= 0
            or accept_backoff_max_seconds < accept_backoff_initial_seconds
            or accept_backoff_max_seconds > 30
        ):
            raise ValueError("Management pipe accept backoff bounds are invalid.")
        self.management = management
        self.operator_sid = _validate_operator_sid(operator_sid)
        self._api = (
            _WindowsPipeServerApi(self.operator_sid) if pipe_api is None else pipe_api
        )
        self._stop_event = threading.Event()
        self._accept_backoff_initial_seconds = float(
            accept_backoff_initial_seconds
        )
        self._accept_backoff_max_seconds = float(accept_backoff_max_seconds)

    def stop(self) -> None:
        self._stop_event.set()

    def serve_once(self) -> None:
        try:
            handle = self._api.create()
        except Exception as exc:
            raise _PipeAcceptError(
                "The management pipe instance could not be created."
            ) from exc
        connected = False
        try:
            try:
                self._api.connect(handle)
            except Exception as exc:
                raise _PipeAcceptError(
                    "The management pipe could not accept a local client."
                ) from exc
            connected = True
            identity = self._api.client_identity(handle)
            if not _is_authorized_client(identity, self.operator_sid):
                raise ManagementTransportError(
                    "The management pipe rejected an unauthorized local client."
                )
            try:
                payload = read_json_frame(
                    lambda length: self._api.read(handle, length)
                )
                response = process_request(payload, self.management)
            except ManagementProtocolError as exc:
                response = {
                    "protocol": PROTOCOL_VERSION,
                    "request_id": None,
                    "ok": False,
                    "error": {"code": "invalid_request", "message": str(exc)},
                }
            try:
                frame = encode_json_frame(response)
            except ManagementProtocolError:
                frame = encode_json_frame(
                    {
                        "protocol": PROTOCOL_VERSION,
                        "request_id": response.get("request_id"),
                        "ok": False,
                        "error": {
                            "code": "response_too_large",
                            "message": "The management response was too large.",
                        },
                    }
                )
            self._api.write(handle, frame)
        finally:
            if connected:
                self._api.finish(handle)
            self._api.close(handle)

    def serve_forever(
        self,
        *,
        error_callback: Callable[[BaseException], Any] | None = None,
    ) -> None:
        accept_backoff = self._accept_backoff_initial_seconds
        while not self._stop_event.is_set():
            try:
                self.serve_once()
                accept_backoff = self._accept_backoff_initial_seconds
            except _PipeAcceptError as exc:
                if error_callback is not None:
                    error_callback(exc)
                if self._stop_event.wait(accept_backoff):
                    break
                accept_backoff = min(
                    self._accept_backoff_max_seconds,
                    accept_backoff * 2,
                )
            except Exception as exc:
                if error_callback is not None:
                    error_callback(exc)


def _named_pipe_server_pid(handle, win32pipe) -> int:
    getter = getattr(win32pipe, "GetNamedPipeServerProcessId", None)
    if getter is not None:
        return int(getter(handle))

    process_id = ctypes.c_ulong()
    function = ctypes.windll.kernel32.GetNamedPipeServerProcessId
    function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    function.restype = ctypes.c_int
    if not function(ctypes.c_void_p(int(handle)), ctypes.byref(process_id)):
        raise ctypes.WinError()
    return int(process_id.value)


def query_mission_legal_service_pid() -> int:
    """Return the running MissionLegalServer SCM process id."""

    (
        _pywintypes,
        _win32api,
        _win32con,
        _win32file,
        _win32pipe,
        _win32security,
        win32service,
    ) = _load_pywin32()
    manager = service = None
    try:
        manager = win32service.OpenSCManager(
            None, None, win32service.SC_MANAGER_CONNECT
        )
        service = win32service.OpenService(
            manager, SERVICE_NAME, win32service.SERVICE_QUERY_STATUS
        )
        status = win32service.QueryServiceStatusEx(service)
        process_id = int(status.get("ProcessId", 0))
        if (
            status.get("CurrentState") != win32service.SERVICE_RUNNING
            or process_id <= 0
        ):
            raise ManagementTransportError("Mission Legal Server is not running.")
        return process_id
    except ManagementTransportError:
        raise
    except Exception as exc:
        raise ManagementTransportError(
            "Mission Legal Server status could not be verified."
        ) from exc
    finally:
        if service is not None:
            win32service.CloseServiceHandle(service)
        if manager is not None:
            win32service.CloseServiceHandle(manager)


class _WindowsPipeClientApi:
    def __init__(self):
        (
            self.pywintypes,
            _win32api,
            self.win32con,
            self.win32file,
            self.win32pipe,
            _win32security,
            _win32service,
        ) = _load_pywin32()

    def connect(self, timeout_ms: int):
        deadline = time.monotonic() + (timeout_ms / 1000)
        while True:
            try:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                self.win32pipe.WaitNamedPipe(PIPE_NAME, remaining_ms)
                return self.win32file.CreateFile(
                    PIPE_NAME,
                    PIPE_CLIENT_DATA_ACCESS,
                    0,
                    None,
                    self.win32con.OPEN_EXISTING,
                    0x00100000 | 0x00010000,  # SQOS_PRESENT | IDENTIFICATION
                    None,
                )
            except self.pywintypes.error as exc:
                if _winerror(exc) == 2 and time.monotonic() < deadline:
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                    continue
                raise ManagementTransportError(
                    "Mission Legal Server Manager could not connect to the server."
                ) from exc

    def server_process_id(self, handle) -> int:
        try:
            return _named_pipe_server_pid(handle, self.win32pipe)
        except Exception as exc:
            raise ManagementTransportError(
                "The management pipe server identity could not be verified."
            ) from exc

    def read(self, handle, length: int) -> bytes:
        try:
            _status, data = self.win32file.ReadFile(handle, length)
        except self.pywintypes.error as exc:
            if _winerror(exc) in {_ERROR_BROKEN_PIPE, _ERROR_NO_DATA}:
                return b""
            raise ManagementTransportError(
                "Mission Legal Server Manager could not read the server response."
            ) from exc
        return bytes(data)

    def write(self, handle, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            try:
                _status, written = self.win32file.WriteFile(
                    handle, remaining.tobytes()
                )
            except self.pywintypes.error as exc:
                raise ManagementTransportError(
                    "Mission Legal Server Manager could not send its request."
                ) from exc
            if not isinstance(written, int) or written <= 0:
                raise ManagementTransportError(
                    "Mission Legal Server Manager could not send its request."
                )
            remaining = remaining[written:]

    def close(self, handle) -> None:
        self.win32file.CloseHandle(handle)


def _validate_response(payload: Any, request_id: str) -> Any:
    if type(payload) is not dict:
        raise ManagementProtocolError("Management response must be a JSON object.")
    if payload.get("protocol") != PROTOCOL_VERSION:
        raise ManagementProtocolError("Management response protocol does not match.")
    if payload.get("request_id") != request_id:
        raise ManagementProtocolError("Management response request_id does not match.")
    if type(payload.get("ok")) is not bool:
        raise ManagementProtocolError("Management response has an invalid result flag.")
    if payload["ok"]:
        if frozenset(payload) != frozenset(
            {"protocol", "request_id", "ok", "result"}
        ):
            raise ManagementProtocolError("Management success response is malformed.")
        return payload["result"]
    if frozenset(payload) != frozenset({"protocol", "request_id", "ok", "error"}):
        raise ManagementProtocolError("Management error response is malformed.")
    error = payload["error"]
    if (
        type(error) is not dict
        or frozenset(error) != frozenset({"code", "message"})
        or type(error.get("code")) is not str
        or type(error.get("message")) is not str
    ):
        raise ManagementProtocolError("Management error response is malformed.")
    raise RemoteManagementCommandError(error["code"], error["message"])


class MissionLegalManagementClient:
    """Standard-user client with pipe-to-SCM process identity pinning."""

    protocol_version = PROTOCOL_VERSION

    def __init__(
        self,
        *,
        timeout_ms: int = 5000,
        pipe_api=None,
        service_pid_provider: Callable[[], int] | None = None,
        request_id_provider: Callable[[], str] | None = None,
    ):
        if type(timeout_ms) is not int or timeout_ms < 1 or timeout_ms > 60_000:
            raise ValueError("timeout_ms must be between 1 and 60000")
        self.timeout_ms = timeout_ms
        self._api = _WindowsPipeClientApi() if pipe_api is None else pipe_api
        self._service_pid_provider = (
            query_mission_legal_service_pid
            if service_pid_provider is None
            else service_pid_provider
        )
        self._request_id_provider = (
            (lambda: uuid.uuid4().hex)
            if request_id_provider is None
            else request_id_provider
        )

    def request(
        self, command: str, arguments: Mapping[str, Any] | None = None
    ) -> Any:
        validated_arguments = validate_command_arguments(
            command, {} if arguments is None else arguments
        )
        request_id = self._request_id_provider()
        if type(request_id) is not str or not _REQUEST_ID_PATTERN.fullmatch(request_id):
            raise ManagementProtocolError("Generated management request_id is invalid.")
        request = {
            "protocol": PROTOCOL_VERSION,
            "request_id": request_id,
            "command": command,
            "arguments": validated_arguments,
        }
        frame = encode_json_frame(request)
        handle = self._api.connect(self.timeout_ms)
        try:
            pipe_server_pid = int(self._api.server_process_id(handle))
            service_pid = int(self._service_pid_provider())
            if service_pid <= 0 or pipe_server_pid != service_pid:
                raise ManagementTransportError(
                    "The management pipe is not owned by Mission Legal Server."
                )
            self._api.write(handle, frame)
            response = read_json_frame(
                lambda length: self._api.read(handle, length)
            )
            return _validate_response(response, request_id)
        finally:
            self._api.close(handle)
