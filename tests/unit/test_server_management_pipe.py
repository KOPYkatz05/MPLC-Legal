import json
import struct
from unittest.mock import patch

import pytest

from server.management import ManagementCommandError
from server.management_pipe import (
    ADMINISTRATORS_SID,
    FILE_APPEND_DATA,
    FILE_FLAG_FIRST_PIPE_INSTANCE,
    MAX_MESSAGE_BYTES,
    PIPE_NAME,
    PIPE_CLIENT_DATA_ACCESS,
    PIPE_REJECT_REMOTE_CLIENTS,
    PROTOCOL_VERSION,
    SYSTEM_SID,
    ManagementProtocolError,
    ManagementTransportError,
    MissionLegalManagementClient,
    MissionLegalManagementPipeServer,
    PipeClientIdentity,
    RemoteManagementCommandError,
    _WindowsPipeClientApi,
    _WindowsPipeServerApi,
    _create_pipe_security_attributes,
    _is_authorized_client,
    encode_json_frame,
    process_request,
    query_mission_legal_service_pid,
    read_json_frame,
)


OPERATOR_SID = "S-1-5-21-100-200-300-1001"


class StubManagement:
    def __init__(self, result=None, error=None):
        self.result = {"answer": 42} if result is None else result
        self.error = error
        self.calls = []

    def execute(self, command, arguments):
        self.calls.append((command, arguments))
        if self.error is not None:
            raise self.error
        return self.result


def _request(**changes):
    payload = {
        "protocol": PROTOCOL_VERSION,
        "request_id": "request-1",
        "command": "get_status",
        "arguments": {},
    }
    payload.update(changes)
    return payload


def _chunk_reader(data, chunk_size=3):
    remaining = bytearray(data)

    def read(length):
        amount = min(length, chunk_size, len(remaining))
        result = bytes(remaining[:amount])
        del remaining[:amount]
        return result

    return read


def test_pipe_name_and_framing_are_fixed_and_big_endian():
    assert PIPE_NAME == r"\\.\pipe\MissionLegal.ServerManager.v1"
    frame = encode_json_frame({"message": "Perú"})
    length = struct.unpack(">I", frame[:4])[0]

    assert length == len(frame) - 4
    assert read_json_frame(_chunk_reader(frame)) == {"message": "Perú"}


def test_frame_rejects_zero_oversized_duplicate_and_invalid_utf8_payloads():
    with pytest.raises(ManagementProtocolError):
        read_json_frame(_chunk_reader(struct.pack(">I", 0)))
    with pytest.raises(ManagementProtocolError):
        read_json_frame(_chunk_reader(struct.pack(">I", MAX_MESSAGE_BYTES + 1)))

    duplicate = b'{"protocol":1,"protocol":1}'
    with pytest.raises(ManagementProtocolError):
        read_json_frame(
            _chunk_reader(struct.pack(">I", len(duplicate)) + duplicate)
        )

    invalid_utf8 = b"\xff"
    with pytest.raises(ManagementProtocolError):
        read_json_frame(
            _chunk_reader(struct.pack(">I", len(invalid_utf8)) + invalid_utf8)
        )


def test_process_request_accepts_only_exact_protocol_fields_and_arguments():
    management = StubManagement()

    success = process_request(_request(), management)
    extra_field = process_request(_request(path=r"C:\Windows"), management)
    shell_argument = process_request(
        _request(command="restart_server", arguments={"shell": "cmd /c whoami"}),
        management,
    )
    bad_device = process_request(
        _request(command="revoke_device", arguments={"device_id": "../bad"}),
        management,
    )

    assert success == {
        "protocol": 1,
        "request_id": "request-1",
        "ok": True,
        "result": {"answer": 42},
    }
    assert extra_field["error"]["code"] == "invalid_request"
    assert shell_argument["error"]["code"] == "invalid_request"
    assert bad_device["error"]["code"] == "invalid_request"
    assert management.calls == [("get_status", {})]


def test_process_request_preserves_safe_errors_and_hides_unexpected_details():
    safe = StubManagement(
        error=ManagementCommandError("backup_failed", "Backup could not be verified.")
    )
    unsafe = StubManagement(error=OSError(r"secret at C:\ProgramData\MissionLegal"))

    safe_response = process_request(_request(), safe)
    unsafe_response = process_request(_request(), unsafe)

    assert safe_response["error"] == {
        "code": "backup_failed",
        "message": "Backup could not be verified.",
    }
    assert unsafe_response["error"]["code"] == "command_failed"
    assert "ProgramData" not in json.dumps(unsafe_response)


def test_authorization_rechecks_exact_operator_system_or_enabled_admin_group():
    assert _is_authorized_client(PipeClientIdentity(OPERATOR_SID), OPERATOR_SID)
    assert _is_authorized_client(PipeClientIdentity(SYSTEM_SID), OPERATOR_SID)
    assert _is_authorized_client(
        PipeClientIdentity(
            "S-1-5-21-1-2-3-1002", frozenset({ADMINISTRATORS_SID})
        ),
        OPERATOR_SID,
    )
    assert not _is_authorized_client(
        PipeClientIdentity("S-1-5-21-1-2-3-1002"), OPERATOR_SID
    )


class FakeSecurity:
    ACL_REVISION = 2

    class ACL:
        def __init__(self):
            self.aces = []

        def AddAccessAllowedAce(self, revision, mask, sid):
            self.aces.append((revision, mask, sid))

    class SECURITY_DESCRIPTOR:
        def SetSecurityDescriptorDacl(self, present, dacl, defaulted):
            self.dacl = (present, dacl, defaulted)

    @staticmethod
    def ConvertStringSidToSid(value):
        return value

    @staticmethod
    def IsValidSid(value):
        return value.startswith("S-1-")


class FakePyWinTypes:
    class SECURITY_ATTRIBUTES:
        pass


class FakeWin32Con:
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3


def test_pipe_dacl_contains_only_system_admin_and_exact_operator_sid():
    attributes = _create_pipe_security_attributes(
        OPERATOR_SID,
        pywintypes=FakePyWinTypes,
        win32con=FakeWin32Con,
        win32security=FakeSecurity,
    )
    _present, dacl, _defaulted = attributes.SECURITY_DESCRIPTOR.dacl

    assert [ace[2] for ace in dacl.aces] == [
        SYSTEM_SID,
        ADMINISTRATORS_SID,
        OPERATOR_SID,
    ]
    masks = {ace[2]: ace[1] for ace in dacl.aces}
    privileged = FakeWin32Con.GENERIC_READ | FakeWin32Con.GENERIC_WRITE
    assert masks[SYSTEM_SID] == privileged
    assert masks[ADMINISTRATORS_SID] == privileged
    assert masks[OPERATOR_SID] == PIPE_CLIENT_DATA_ACCESS
    assert masks[OPERATOR_SID] & FILE_APPEND_DATA == 0
    assert masks[OPERATOR_SID] & FakeWin32Con.GENERIC_WRITE == 0
    assert attributes.bInheritHandle is False


def test_create_named_pipe_sets_remote_rejection_and_first_instance_flags():
    captured = {}

    class FakePipe:
        PIPE_TYPE_BYTE = 1
        PIPE_READMODE_BYTE = 2
        PIPE_WAIT = 4
        PIPE_ACCESS_DUPLEX = 3
        PIPE_UNLIMITED_INSTANCES = 255

        @staticmethod
        def CreateNamedPipe(*args):
            captured["args"] = args
            return "pipe"

    api = object.__new__(_WindowsPipeServerApi)
    api.pywintypes = FakePyWinTypes
    api.win32con = FakeWin32Con
    api.win32security = FakeSecurity
    api.win32pipe = FakePipe
    api.operator_sid = OPERATOR_SID

    assert api.create() == "pipe"
    assert captured["args"][0] == PIPE_NAME
    assert captured["args"][1] & FILE_FLAG_FIRST_PIPE_INSTANCE
    assert captured["args"][2] & PIPE_REJECT_REMOTE_CLIENTS


def test_client_requests_only_pipe_data_rights():
    captured = {}

    class FakeClientPipe:
        @staticmethod
        def WaitNamedPipe(path, timeout_ms):
            captured["wait"] = (path, timeout_ms)

    class FakeClientFile:
        @staticmethod
        def CreateFile(*args):
            captured["create"] = args
            return "client-handle"

    class FakeClientPyWinTypes:
        error = OSError

    api = object.__new__(_WindowsPipeClientApi)
    api.pywintypes = FakeClientPyWinTypes
    api.win32con = FakeWin32Con
    api.win32file = FakeClientFile
    api.win32pipe = FakeClientPipe

    assert api.connect(5000) == "client-handle"
    desired_access = captured["create"][1]
    assert desired_access == PIPE_CLIENT_DATA_ACCESS
    assert desired_access & FILE_APPEND_DATA == 0
    assert desired_access & FakeWin32Con.GENERIC_WRITE == 0


class FakeServerApi:
    def __init__(self, identity, framed_request=b""):
        self.identity = identity
        self.request = bytearray(framed_request)
        self.read_calls = 0
        self.written = b""
        self.finished = False
        self.closed = False

    def create(self):
        return "handle"

    def connect(self, handle):
        assert handle == "handle"

    def client_identity(self, handle):
        return self.identity

    def read(self, handle, length):
        self.read_calls += 1
        result = bytes(self.request[:length])
        del self.request[:length]
        return result

    def write(self, handle, data):
        self.written += data

    def finish(self, handle):
        self.finished = True

    def close(self, handle):
        self.closed = True


class RecordingStopEvent:
    def __init__(self, stop_after_waits):
        self.stop_after_waits = stop_after_waits
        self.waits = []
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, timeout):
        self.waits.append(timeout)
        if len(self.waits) >= self.stop_after_waits:
            self.stopped = True
        return self.stopped

    def set(self):
        self.stopped = True


class FailingAcceptApi:
    def __init__(self, failure_point):
        self.failure_point = failure_point
        self.create_calls = 0
        self.connect_calls = 0
        self.close_calls = 0

    def create(self):
        self.create_calls += 1
        if self.failure_point == "create":
            raise OSError("pipe namespace occupied")
        return f"handle-{self.create_calls}"

    def connect(self, handle):
        self.connect_calls += 1
        if self.failure_point == "connect":
            raise OSError("accept failed")

    def close(self, handle):
        self.close_calls += 1


@pytest.mark.parametrize("failure_point", ["create", "connect"])
def test_accept_failures_use_bounded_exponential_stop_interruptible_backoff(
    failure_point,
):
    api = FailingAcceptApi(failure_point)
    server = MissionLegalManagementPipeServer(
        StubManagement(),
        operator_sid=OPERATOR_SID,
        pipe_api=api,
        accept_backoff_initial_seconds=0.1,
        accept_backoff_max_seconds=0.25,
    )
    stop_event = RecordingStopEvent(stop_after_waits=5)
    server._stop_event = stop_event
    errors = []

    server.serve_forever(error_callback=errors.append)

    assert stop_event.waits == [0.1, 0.2, 0.25, 0.25, 0.25]
    assert api.create_calls == 5
    assert api.connect_calls == (5 if failure_point == "connect" else 0)
    assert api.close_calls == (5 if failure_point == "connect" else 0)
    assert len(errors) == 5
    assert all(isinstance(error, ManagementTransportError) for error in errors)


def test_pipe_server_rechecks_sid_before_reading_request():
    api = FakeServerApi(PipeClientIdentity("S-1-5-21-1-2-3-9999"))
    server = MissionLegalManagementPipeServer(
        StubManagement(), operator_sid=OPERATOR_SID, pipe_api=api
    )

    with pytest.raises(ManagementTransportError):
        server.serve_once()

    assert api.read_calls == 0
    assert api.finished is True
    assert api.closed is True


def test_pipe_server_processes_authorized_framed_request():
    api = FakeServerApi(
        PipeClientIdentity(OPERATOR_SID), encode_json_frame(_request())
    )
    management = StubManagement(result={"state": "running"})
    server = MissionLegalManagementPipeServer(
        management, operator_sid=OPERATOR_SID, pipe_api=api
    )

    server.serve_once()
    response = read_json_frame(_chunk_reader(api.written))

    assert response["ok"] is True
    assert response["result"] == {"state": "running"}
    assert api.finished is True
    assert api.closed is True


class FakeClientApi:
    def __init__(self, *, server_pid, response):
        self.server_pid = server_pid
        self.response = bytearray(response)
        self.writes = []
        self.closed = False

    def connect(self, timeout_ms):
        assert timeout_ms == 5000
        return "handle"

    def server_process_id(self, handle):
        return self.server_pid

    def write(self, handle, data):
        self.writes.append(data)

    def read(self, handle, length):
        result = bytes(self.response[:length])
        del self.response[:length]
        return result

    def close(self, handle):
        self.closed = True


def _response_frame(*, request_id="fixed-id", ok=True):
    payload = {
        "protocol": 1,
        "request_id": request_id,
        "ok": ok,
    }
    if ok:
        payload["result"] = {"state": "running"}
    else:
        payload["error"] = {"code": "restart_failed", "message": "Could not restart."}
    return encode_json_frame(payload)


def test_client_verifies_pipe_pid_matches_scm_before_sending_request():
    api = FakeClientApi(server_pid=8000, response=_response_frame())
    client = MissionLegalManagementClient(
        pipe_api=api,
        service_pid_provider=lambda: 9000,
        request_id_provider=lambda: "fixed-id",
    )

    with pytest.raises(ManagementTransportError):
        client.request("get_status")

    assert api.writes == []
    assert api.closed is True


def test_client_returns_verified_response_and_uses_exact_request_shape():
    api = FakeClientApi(server_pid=9000, response=_response_frame())
    client = MissionLegalManagementClient(
        pipe_api=api,
        service_pid_provider=lambda: 9000,
        request_id_provider=lambda: "fixed-id",
    )

    result = client.request("get_status")
    written_request = read_json_frame(_chunk_reader(api.writes[0]))

    assert result == {"state": "running"}
    assert written_request == {
        "protocol": 1,
        "request_id": "fixed-id",
        "command": "get_status",
        "arguments": {},
    }
    assert api.closed is True


def test_client_raises_typed_remote_error():
    api = FakeClientApi(server_pid=9000, response=_response_frame(ok=False))
    client = MissionLegalManagementClient(
        pipe_api=api,
        service_pid_provider=lambda: 9000,
        request_id_provider=lambda: "fixed-id",
    )

    with pytest.raises(RemoteManagementCommandError) as error:
        client.request("restart_server")

    assert error.value.code == "restart_failed"


def test_service_pid_query_requires_running_service_and_closes_handles():
    closed = []

    class FakeService:
        SC_MANAGER_CONNECT = 1
        SERVICE_QUERY_STATUS = 2
        SERVICE_RUNNING = 4

        @staticmethod
        def OpenSCManager(machine, database, access):
            return "manager"

        @staticmethod
        def OpenService(manager, name, access):
            return "service"

        @staticmethod
        def QueryServiceStatusEx(service):
            return {"CurrentState": 4, "ProcessId": 31415}

        @staticmethod
        def CloseServiceHandle(handle):
            closed.append(handle)

    loaded = (None, None, None, None, None, None, FakeService)
    with patch("server.management_pipe._load_pywin32", return_value=loaded):
        assert query_mission_legal_service_pid() == 31415

    assert closed == ["service", "manager"]
