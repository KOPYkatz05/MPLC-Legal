import threading
from unittest.mock import patch

import windows_service


def test_service_disables_uvicorn_color_detection():
    captured = {}

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, config):
            self.should_exit = False

        def run(self):
            return None

    service = object.__new__(windows_service.MissionLegalWindowsService)
    service.server = None

    with (
        patch("windows_service._configure_service_runtime_environment"),
        patch("server.tls.generate_local_tls", return_value={
            "server_cert": "server.crt",
            "server_key": "server.key",
        }),
        patch("server.configuration.load_server_configuration", return_value={}),
        patch.object(
            windows_service.MissionLegalWindowsService,
            "_start_management_broker",
        ),
        patch("uvicorn.Config", FakeConfig),
        patch("uvicorn.Server", FakeServer),
        patch("servicemanager.LogInfoMsg"),
        patch("servicemanager.LogErrorMsg"),
    ):
        service.SvcDoRun()

    assert captured["use_colors"] is False


def test_service_resolves_installer_enrolled_manager_account_to_exact_sid():
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeRegistry:
        HKEY_LOCAL_MACHINE = object()
        KEY_READ = 1
        KEY_WOW64_64KEY = 2
        REG_SZ = 1
        REG_EXPAND_SZ = 2

        @staticmethod
        def OpenKey(root, path, reserved, access):
            assert root is FakeRegistry.HKEY_LOCAL_MACHINE
            assert path == r"SOFTWARE\MissionLegal\Server"
            assert access == 3
            return FakeKey()

        @staticmethod
        def QueryValueEx(key, name):
            assert name == "ManagerOperatorAccount"
            return (r"MISSION\server.operator", FakeRegistry.REG_SZ)

    class FakeSecurity:
        SidTypeUser = 1

        @staticmethod
        def LookupAccountName(system, account):
            assert system is None
            assert account == r"MISSION\server.operator"
            return ("sid-object", "MISSION", 1)

        @staticmethod
        def ConvertSidToStringSid(sid):
            assert sid == "sid-object"
            return "S-1-5-21-100-200-300-1001"

    assert windows_service._resolve_manager_operator_sid(
        frozen=True,
        environment={},
        registry_module=FakeRegistry,
        security_module=FakeSecurity,
        api_module=object(),
    ) == "S-1-5-21-100-200-300-1001"


def test_service_rejects_group_as_installer_enrolled_manager_account():
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeRegistry:
        HKEY_LOCAL_MACHINE = object()
        KEY_READ = 1
        KEY_WOW64_64KEY = 2
        REG_SZ = 1
        REG_EXPAND_SZ = 2

        @staticmethod
        def OpenKey(*_args):
            return FakeKey()

        @staticmethod
        def QueryValueEx(_key, _name):
            return (r"MISSION\Server Operators", FakeRegistry.REG_SZ)

    class FakeSecurity:
        SidTypeUser = 1
        SidTypeGroup = 2

        @staticmethod
        def LookupAccountName(_system, _account):
            return ("group-sid", "MISSION", FakeSecurity.SidTypeGroup)

        @staticmethod
        def ConvertSidToStringSid(_sid):
            return "S-1-5-21-100-200-300-2001"

    try:
        windows_service._resolve_manager_operator_sid(
            frozen=True,
            environment={},
            registry_module=FakeRegistry,
            security_module=FakeSecurity,
            api_module=object(),
        )
    except RuntimeError as exc:
        assert "one Windows user account" in str(exc)
    else:
        raise AssertionError("A group principal must not be enrolled as operator.")


def test_service_restart_callback_recycles_api_without_stopping_service():
    service = object.__new__(windows_service.MissionLegalWindowsService)
    service.restart_requested = threading.Event()
    service.stopping = threading.Event()

    class Server:
        should_exit = False
        started = True

    service.server = Server()
    service._request_api_restart()

    assert service.restart_requested.is_set()
    assert service.server.should_exit is True


def test_service_api_runtime_state_tracks_uvicorn_readiness_and_restart():
    service = object.__new__(windows_service.MissionLegalWindowsService)
    service.restart_requested = threading.Event()
    service.stopping = threading.Event()
    service.server = None

    assert service._api_runtime_state() == "starting"

    class Server:
        should_exit = False
        started = False

    service.server = Server()
    assert service._api_runtime_state() == "starting"

    service.server.started = True
    assert service._api_runtime_state() == "running"

    service.restart_requested.set()
    assert service._api_runtime_state() == "restarting"

    service.restart_requested.clear()
    service.stopping.set()
    assert service._api_runtime_state() == "stopping"


def test_service_rejects_restart_until_api_runtime_is_ready():
    service = object.__new__(windows_service.MissionLegalWindowsService)
    service.restart_requested = threading.Event()
    service.stopping = threading.Event()

    class Server:
        should_exit = False
        started = False

    service.server = Server()

    try:
        service._request_api_restart()
    except RuntimeError as exc:
        assert "not ready" in str(exc)
    else:
        raise AssertionError("A starting API runtime must not accept restart.")

    assert not service.restart_requested.is_set()
    assert service.server.should_exit is False


def test_management_broker_uses_live_api_runtime_state_provider():
    service = object.__new__(windows_service.MissionLegalWindowsService)
    service.server = None
    service.management_broker = None
    service.management_thread = None
    service.restart_requested = threading.Event()
    service.stopping = threading.Event()

    with (
        patch(
            "windows_service._resolve_manager_operator_sid",
            return_value="S-1-5-21-100-200-300-1001",
        ),
        patch("server.management.MissionLegalManagement") as management_class,
        patch(
            "server.management_pipe.MissionLegalManagementPipeServer"
        ) as broker_class,
        patch("servicemanager.LogInfoMsg"),
    ):
        service._start_management_broker()
        service.management_thread.join(timeout=2)

    kwargs = management_class.call_args.kwargs
    assert kwargs["restart_callback"] == service._request_api_restart
    assert kwargs["state_provider"] == service._api_runtime_state
    broker_class.assert_called_once_with(
        management_class.return_value,
        operator_sid="S-1-5-21-100-200-300-1001",
    )
