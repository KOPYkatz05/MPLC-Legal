import json
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt

import server_manager
from services.pairing_package import encode_pairing_package
from ui.server_manager_window import ServerManagerWindow


def _setup_code(code, expires_at):
    return encode_pairing_package(
        server_url="https://192.168.108.50:8765",
        ca_certificate_pem=(
            "-----BEGIN CERTIFICATE-----\n"
            "PUBLIC CA\n"
            "-----END CERTIFICATE-----\n"
        ),
        pairing_code=code,
        expires_at=expires_at,
    )


class ImmediateRunner:
    def submit(self, operation, on_success, on_error):
        try:
            result = operation()
        except Exception as exc:
            on_error(str(exc))
        else:
            on_success(result)


class DeferredRunner:
    def __init__(self):
        self.pending = []

    def submit(self, operation, on_success, on_error):
        self.pending.append(
            {
                "operation": operation,
                "on_success": on_success,
                "on_error": on_error,
            }
        )

    def succeed(self, index, result):
        self.pending[index]["on_success"](result)

    def fail(self, index, message):
        self.pending[index]["on_error"](message)


class FakeManagementClient:
    protocol_version = 7

    def __init__(self):
        self.calls = []
        self.status = {
            "state": "running",
            "service_name": "MissionLegalServer",
            "pid": 4321,
            "hostname": "MISSION-SERVER",
            "app_version": "0.1.4",
            "api_version": "1",
            "schema_version": 1,
            "uptime_seconds": 3720,
            "host": "0.0.0.0",
            "port": 8765,
            "server_address": "https://192.168.108.50:8765",
            "database_file_present": True,
            "server_process_cpu_percent": 3.5,
            "server_process_memory_bytes": 128 * 1024 * 1024,
            "network": {
                "available": True,
                "trusted": True,
                "network_id": "office123456",
                "name": "Mission Office",
                "addresses": ["192.168.108.50"],
            },
        }
        self.devices = [
            {
                "device_id": "a" * 32,
                "device_name": "Front Office",
                "created_at": "2026-07-24T12:00:00+00:00",
                "revoked_at": None,
                "pending_confirmation": False,
                "state": "active",
            }
        ]

    def request(self, command, arguments=None):
        self.calls.append((command, arguments))
        if command == "get_status":
            return dict(self.status)
        if command == "create_pairing_code":
            expires_at = (
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat()
            return {
                "code": "123456",
                "setup_code": _setup_code("123456", expires_at),
                "expires_at": expires_at,
                "lifetime_seconds": 600,
            }
        if command == "trust_current_network":
            self.status["network"]["trusted"] = True
            return {"network": dict(self.status["network"])}
        if command == "forget_current_network":
            self.status["network"]["trusted"] = False
            return {"network": dict(self.status["network"])}
        if command == "list_devices":
            return {"devices": list(self.devices)}
        if command == "revoke_device":
            return {
                "device_id": arguments["device_id"],
                "revoked": True,
            }
        if command == "restart_server":
            return {"accepted": True}
        if command == "create_verified_backup":
            return {
                "filename": "mission-legal_20260724.db",
                "sha256": "b" * 64,
            }
        if command == "get_support_summary":
            return {
                "generated_at": "2026-07-24T12:00:00+00:00",
                "status": {
                    **self.status,
                    "credential": "must-not-copy",
                    "tls_private_key": "must-not-copy",
                },
                "device_counts": {
                    "active": 1,
                    "pending": 0,
                    "revoked": 0,
                    "total": 1,
                    "device_names": ["must-not-copy"],
                },
                "latest_backup": {
                    "filename": "mission-legal_20260724.db",
                    "sha256": "b" * 64,
                    "full_path": r"C:\ProgramData\private",
                },
                "secret": "must-not-copy",
            }
        raise AssertionError(f"Unexpected command: {command}")


def make_window(qapp, **kwargs):
    _ = qapp
    client = kwargs.pop("client", FakeManagementClient())
    request_runner = kwargs.pop("request_runner", ImmediateRunner())
    window = ServerManagerWindow(
        management_client=client,
        request_runner=request_runner,
        confirm_revoke=lambda _name: True,
        confirm_restart=lambda: True,
        **kwargs,
    )
    return window, client


def test_server_manager_is_small_frameless_and_uses_expected_tabs(qapp):
    window, _client = make_window(qapp)
    qapp.processEvents()

    assert window.size() == QSize(760, 520)
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert [
        window.tabs.tabText(index)
        for index in range(window.tabs.count())
    ] == ["Pairing", "Status", "Paired Devices", "Tools", "Updates"]
    assert window.title_bar.maximize_button.isHidden()
    assert window.header_status.text() == "Running"
    assert window.status_cards["address"].value_label.text() == (
        "https://192.168.108.50:8765"
    )
    assert window.status_cards["cpu"].value_label.text() == "3.5%"
    assert window.status_cards["ram"].value_label.text() == "128.0 MB"
    assert window.status_cards["database"].value_label.text() == "Present"
    assert window.copy_address_button.isEnabled()
    assert window.devices_table.focusPolicy() == Qt.StrongFocus
    assert "background-color: #0F5F64" in window.styleSheet()

    window.deleteLater()


def test_close_hides_manager_but_explicit_exit_allows_close(qapp):
    window, _client = make_window(qapp)
    window.show()
    qapp.processEvents()

    window.close()
    qapp.processEvents()
    assert window.isVisible() is False
    assert window._allow_close is False

    window.show()
    window.request_exit()
    qapp.processEvents()
    assert window.isVisible() is False
    assert window._allow_close is True
    window.deleteLater()


def test_pairing_code_can_be_generated_copied_and_expires(qapp):
    window, client = make_window(qapp)
    window.generate_code_button.click()
    qapp.processEvents()

    assert ("create_pairing_code", None) in client.calls
    assert window.pairing_code_label.text() == "1 2 3 4 5 6"
    assert window.copy_code_button.isEnabled()

    window.copy_code_button.click()
    assert qapp.clipboard().text().startswith("MLPAIR1:")
    assert "copied" in window.pairing_feedback.text().lower()

    window._pairing_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    window._update_pairing_countdown()
    assert window.copy_code_button.isEnabled() is False
    assert "expired" in window.pairing_expiry_label.text().lower()
    window.deleteLater()


def test_current_network_trust_toggle_controls_discovery_copy(qapp):
    window, client = make_window(qapp)
    qapp.processEvents()

    assert window._network_trusted is True
    assert window.network_trust_button.text() == "Remove trust"

    window.network_trust_button.click()
    qapp.processEvents()

    assert ("forget_current_network", None) in client.calls
    assert window._network_trusted is False
    assert window.network_trust_button.text() == "Trust this network"
    assert "localhost remains available" in window.pairing_feedback.text().lower()
    window.deleteLater()


def test_pairing_generation_failure_clears_the_previous_code(
    qapp,
    monkeypatch,
):
    window, client = make_window(qapp)
    window.generate_pairing_code()
    assert window.copy_code_button.isEnabled()

    original_request = client.request

    def fail_pairing(command, arguments=None):
        if command == "create_pairing_code":
            raise RuntimeError("transport unavailable")
        return original_request(command, arguments)

    monkeypatch.setattr(client, "request", fail_pairing)
    window.generate_pairing_code()

    assert window.pairing_code_label.text() == "— — — — — —"
    assert window.copy_code_button.isEnabled() is False
    assert "could not generate" in window.pairing_feedback.text().lower()
    window.deleteLater()


def test_repeated_pairing_requests_cannot_race_or_show_a_stale_code(qapp):
    runner = DeferredRunner()
    window, _client = make_window(qapp, request_runner=runner)

    window.show_pairing(generate=True)
    window.show_pairing(generate=True)

    assert len(runner.pending) == 1
    assert window._pairing_request_pending is True
    assert window.generate_code_button.isEnabled() is False
    assert "already" in window.pairing_feedback.text().lower()

    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    ).isoformat()
    runner.succeed(
        0,
        {
            "code": "654321",
            "setup_code": _setup_code("654321", expires_at),
            "expires_at": expires_at,
        },
    )

    assert window.pairing_code_label.text() == "6 5 4 3 2 1"
    assert window._pairing_request_pending is False
    window.deleteLater()


def test_malformed_pairing_response_does_not_leave_a_copyable_code(qapp):
    window, _client = make_window(qapp)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    ).isoformat()
    window._pairing_code_created(
        {
            "code": "123456",
            "setup_code": _setup_code("123456", expires_at),
            "expires_at": expires_at,
        }
    )
    assert window.copy_code_button.isEnabled()

    window._pairing_code_created({"code": "not-a-code"})

    assert window.pairing_code_label.text() == "— — — — — —"
    assert window.copy_code_button.isEnabled() is False
    assert "incomplete" in window.pairing_feedback.text().lower()
    window.deleteLater()


def test_devices_are_listed_and_revoke_uses_typed_device_id(qapp):
    window, client = make_window(qapp)
    window.tabs.setCurrentWidget(window.devices_tab)
    qapp.processEvents()

    assert window.devices_table.rowCount() == 1
    assert window.devices_table.item(0, 0).text() == "Front Office"
    revoke_button = window.devices_table.cellWidget(0, 3)
    assert revoke_button is not None
    revoke_button.click()
    qapp.processEvents()

    assert (
        "revoke_device",
        {"device_id": "a" * 32},
    ) in client.calls
    window.deleteLater()


def test_device_refresh_removes_stale_buttons_after_multi_device_reorder(qapp):
    window, client = make_window(qapp)
    active_a = {
        "device_id": "a" * 32,
        "device_name": "Alpha",
        "created_at": "2026-07-24T12:00:00+00:00",
        "revoked_at": None,
        "pending_confirmation": False,
        "state": "active",
    }
    active_b = {
        "device_id": "b" * 32,
        "device_name": "Bravo",
        "created_at": "2026-07-24T12:05:00+00:00",
        "revoked_at": None,
        "pending_confirmation": False,
        "state": "active",
    }
    revoked_a = {
        **active_a,
        "revoked_at": "2026-07-24T12:30:00+00:00",
        "state": "revoked",
    }

    window._devices_loaded({"devices": [active_a, active_b]})
    previous_row_one_button = window.devices_table.cellWidget(1, 3)
    assert previous_row_one_button is not None

    window._devices_loaded({"devices": [active_b, revoked_a]})

    assert window.devices_table.item(0, 0).text() == "Bravo"
    assert window.devices_table.item(1, 0).text() == "Alpha"
    assert window.devices_table.item(1, 1).text() == "Revoked"
    assert window.devices_table.cellWidget(1, 3) is None

    window.devices_table.cellWidget(0, 3).click()
    assert (
        "revoke_device",
        {"device_id": "b" * 32},
    ) in client.calls
    window.deleteLater()


def test_out_of_order_device_refresh_cannot_overwrite_newer_rows(qapp):
    runner = DeferredRunner()
    window, client = make_window(qapp, request_runner=runner)
    window.status_timer.stop()
    qapp.processEvents()
    assert len(runner.pending) == 1
    runner.succeed(0, dict(client.status))

    window.refresh_devices()
    window.refresh_devices()
    assert len(runner.pending) == 3

    newer = {
        "devices": [
            {
                "device_id": "c" * 32,
                "device_name": "Current device",
                "created_at": "2026-07-24T12:10:00+00:00",
                "state": "active",
            }
        ]
    }
    older = {
        "devices": [
            {
                "device_id": "d" * 32,
                "device_name": "Stale device",
                "created_at": "2026-07-24T11:10:00+00:00",
                "state": "active",
            }
        ]
    }

    runner.succeed(2, newer)
    runner.succeed(1, older)

    assert window.devices_table.rowCount() == 1
    assert window.devices_table.item(0, 0).text() == "Current device"
    assert window.refresh_devices_button.isEnabled()
    window.deleteLater()


def test_revoke_failure_does_not_retain_a_deleted_cell_widget(qapp):
    runner = DeferredRunner()
    window, client = make_window(qapp, request_runner=runner)
    window._devices_loaded({"devices": list(client.devices)})
    old_button = window.devices_table.cellWidget(0, 3)
    assert old_button is not None

    old_button.click()
    assert len(runner.pending) == 1
    window._devices_loaded({"devices": []})

    runner.fail(0, "transport unavailable")

    assert window.devices_table.rowCount() == 0
    assert "could not revoke" in window.devices_feedback.text().lower()
    window.deleteLater()


def test_tools_use_allowlisted_actions_and_support_copy_is_sanitized(qapp):
    window, client = make_window(qapp)
    window.restart_button.click()
    window.backup_button.click()
    window.support_button.click()
    qapp.processEvents()

    commands = [command for command, _arguments in client.calls]
    assert "restart_server" in commands
    assert "create_verified_backup" in commands
    assert "get_support_summary" in commands

    copied = qapp.clipboard().text()
    payload = json.loads(copied)
    assert payload["status"]["state"] == "running"
    assert payload["device_counts"]["active"] == 1
    assert payload["latest_backup"]["filename"] == "mission-legal_20260724.db"
    assert "must-not-copy" not in copied
    assert "full_path" not in copied
    assert "credential" not in copied
    window.deleteLater()


def test_restart_waits_for_running_state_before_claiming_verification(qapp):
    window, client = make_window(qapp)
    qapp.processEvents()
    client.status["state"] = "restarting"

    window.restart_button.click()
    window.restart_poll_timer.stop()

    assert window._restart_poll_active is True
    assert window.restart_button.isEnabled() is False
    assert window.header_status.text() == "Restarting…"
    assert "verified" not in window.tools_feedback.text().casefold()

    window._poll_restart_status()
    window.restart_poll_timer.stop()

    assert window._restart_poll_active is True
    assert window.header_status.text() == "Restarting…"
    assert "verified" not in window.tools_feedback.text().casefold()

    client.status["state"] = "running"
    window._poll_restart_status()

    assert window._restart_poll_active is False
    assert window.restart_button.isEnabled()
    assert window.header_status.text() == "Running"
    assert "restart verified" in window.tools_feedback.text().casefold()
    window.deleteLater()


def test_restart_verification_has_a_bounded_timeout(qapp):
    window, _client = make_window(qapp)
    qapp.processEvents()

    window.restart_button.click()
    window.restart_poll_timer.stop()
    window._restart_deadline = 0.0
    window._poll_restart_status()

    assert window._restart_poll_active is False
    assert window.restart_button.isEnabled()
    assert "did not report running" in window.tools_feedback.text().casefold()
    assert window.tools_feedback.property("error") is True
    window.deleteLater()


def test_status_failure_clears_live_metrics_and_recovery_clears_error_tooltip(qapp):
    window, client = make_window(qapp)
    qapp.processEvents()
    assert window.status_cards["cpu"].value_label.text() == "3.5%"

    window._status_failed("pipe unavailable")

    assert window.header_status.text() == "Unavailable"
    assert window.status_cards["uptime"].value_label.text() == "—"
    assert window.status_cards["cpu"].value_label.text() == "—"
    assert window.status_cards["ram"].value_label.text() == "—"
    assert window.status_cards["database"].value_label.text() == "—"
    assert window.status_feedback.toolTip() == "pipe unavailable"
    assert window.status_feedback.property("error") is True

    recovered = dict(client.status)
    recovered["state"] = "starting"
    window._status_loaded(recovered)

    assert window.header_status.text() == "Starting…"
    assert window.header_status.property("state") == "transitional"
    assert window.status_feedback.toolTip() == ""
    assert window.status_feedback.property("error") is False
    assert window.status_cards["database"].value_label.text() == "Present"
    window.deleteLater()


def test_server_address_copy_is_disabled_until_a_valid_status_arrives(qapp):
    window, client = make_window(qapp)
    window.status_timer.stop()
    qapp.clipboard().setText("unchanged")

    assert window.server_address_available is False
    assert window.copy_address_button.isEnabled() is False
    assert window.copy_server_address() is False
    assert qapp.clipboard().text() == "unchanged"

    window._status_loaded(dict(client.status))

    assert window.server_address_available is True
    assert window.copy_address_button.isEnabled()
    assert window.copy_server_address() is True
    assert qapp.clipboard().text() == "https://192.168.108.50:8765"
    window.deleteLater()


def test_tray_copy_enables_after_status_and_shows_confirmation(qapp):
    client = FakeManagementClient()
    manager = server_manager.ServerManagerApplication(
        qapp,
        startup_hidden=True,
        management_client=client,
        request_runner=ImmediateRunner(),
    )
    real_tray_icon = manager.tray_icon
    real_tray_icon.hide()

    assert manager.copy_address_action.isEnabled() is False
    manager.window.refresh_status()
    assert manager.copy_address_action.isEnabled()

    class MessageRecorder:
        def __init__(self):
            self.messages = []
            self.tooltip = ""

        def showMessage(self, *arguments):
            self.messages.append(arguments)

        def setToolTip(self, value):
            self.tooltip = value

    recorder = MessageRecorder()
    manager.tray_icon = recorder
    manager._copy_server_address_from_tray()

    assert qapp.clipboard().text() == "https://192.168.108.50:8765"
    assert recorder.messages
    assert "copied" in recorder.messages[0][1].casefold()

    manager.tray_icon = real_tray_icon
    manager.window.request_exit()
    manager.deleteLater()


def test_manager_swallows_title_bar_double_click_instead_of_maximizing(
    qapp,
    monkeypatch,
):
    window, _client = make_window(qapp)
    calls = []
    monkeypatch.setattr(
        window.title_bar,
        "toggle_maximized",
        lambda: calls.append("maximize"),
    )
    event = QEvent(QEvent.MouseButtonDblClick)

    handled = window.eventFilter(window.title_bar.drag_region, event)

    assert handled is True
    assert event.isAccepted()
    assert calls == []
    window.deleteLater()


def test_connection_smoke_is_headless_and_writes_only_public_fields(
    monkeypatch,
):
    pipe_module = types.ModuleType("server.management_pipe")
    pipe_module.PROTOCOL_VERSION = 7
    monkeypatch.setitem(sys.modules, "server.management_pipe", pipe_module)
    client = FakeManagementClient()
    result_path = Path("tests") / f"connection-{uuid.uuid4().hex}.json"
    try:
        exit_code = server_manager.run_connection_smoke(
            result_path,
            client_factory=lambda: client,
        )

        assert exit_code == 0
        assert json.loads(result_path.read_text(encoding="utf-8")) == {
            "status": "ok",
            "protocol": 7,
            "app_version": "0.1.4",
        }
    finally:
        result_path.unlink(missing_ok=True)
    assert client.calls == [("get_status", {})]


def test_connection_smoke_has_deterministic_failure_result(monkeypatch):
    pipe_module = types.ModuleType("server.management_pipe")
    pipe_module.PROTOCOL_VERSION = 7
    monkeypatch.setitem(sys.modules, "server.management_pipe", pipe_module)
    client = FakeManagementClient()
    client.status["state"] = "stopped"
    result_path = Path("tests") / f"connection-{uuid.uuid4().hex}.json"
    try:
        exit_code = server_manager.run_connection_smoke(
            result_path,
            client_factory=lambda: client,
        )

        assert exit_code == server_manager.CONNECTION_SMOKE_ERROR_EXIT_CODE
        assert json.loads(result_path.read_text(encoding="utf-8")) == {
            "status": "error",
            "protocol": None,
            "app_version": None,
        }
    finally:
        result_path.unlink(missing_ok=True)


def test_install_autostart_mode_is_headless_and_deterministic(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server_manager,
        "ensure_autostart",
        lambda: calls.append("install"),
    )

    assert server_manager.main(["--install-autostart"]) == 0
    assert calls == ["install"]


def test_remove_autostart_mode_is_headless_and_deterministic(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server_manager,
        "remove_autostart",
        lambda: calls.append("remove"),
    )

    assert server_manager.main(["--remove-autostart"]) == 0
    assert calls == ["remove"]


def test_installer_startup_and_autostart_flags_are_accepted_together():
    args = server_manager._parser().parse_args(
        ["--startup", "--install-autostart"]
    )

    assert args.startup is True
    assert args.install_autostart is True


def test_frozen_startup_accepts_only_the_installer_enrolled_user_sid(
    monkeypatch,
):
    monkeypatch.setenv(
        "MISSION_LEGAL_MANAGER_OPERATOR_SID",
        "S-1-5-21-999-999-999-999",
    )
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
            assert reserved == 0
            assert access == 3
            return FakeKey()

        @staticmethod
        def QueryValueEx(_key, name):
            assert name == "ManagerOperatorAccount"
            return (r"MISSION\server.operator", FakeRegistry.REG_SZ)

    class FakeToken:
        def __init__(self):
            self.closed = False

        def Close(self):
            self.closed = True

    token = FakeToken()

    class FakeSecurity:
        SidTypeUser = 1
        TOKEN_QUERY = 8
        TokenUser = 1

        @staticmethod
        def LookupAccountName(_system, account):
            assert account == r"MISSION\server.operator"
            return ("configured-sid", "MISSION", FakeSecurity.SidTypeUser)

        @staticmethod
        def OpenProcessToken(process, access):
            assert process == "current-process"
            assert access == FakeSecurity.TOKEN_QUERY
            return token

        @staticmethod
        def GetTokenInformation(received_token, information_class):
            assert received_token is token
            assert information_class == FakeSecurity.TokenUser
            return ("current-sid", 0)

        @staticmethod
        def ConvertSidToStringSid(sid):
            return {
                "configured-sid": "S-1-5-21-100-200-300-1001",
                "current-sid": "S-1-5-21-100-200-300-1001",
            }[sid]

    class FakeApi:
        @staticmethod
        def GetCurrentProcess():
            return "current-process"

    assert server_manager._current_user_is_configured_operator(
        frozen=True,
        platform="win32",
        registry_module=FakeRegistry,
        security_module=FakeSecurity,
        api_module=FakeApi,
    )
    assert token.closed


def test_frozen_startup_rejects_group_operator_and_wrong_user():
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeRegistry:
        HKEY_LOCAL_MACHINE = object()
        KEY_READ = 1
        REG_SZ = 1

        @staticmethod
        def OpenKey(*_args):
            return FakeKey()

        @staticmethod
        def QueryValueEx(*_args):
            return (r"MISSION\Server Operators", FakeRegistry.REG_SZ)

    class FakeGroupSecurity:
        SidTypeUser = 1

        @staticmethod
        def LookupAccountName(*_args):
            return ("group-sid", "MISSION", 2)

    assert not server_manager._current_user_is_configured_operator(
        frozen=True,
        platform="win32",
        registry_module=FakeRegistry,
        security_module=FakeGroupSecurity,
        api_module=object(),
    )

    class FakeUserSecurity(FakeGroupSecurity):
        TOKEN_QUERY = 8
        TokenUser = 1

        @staticmethod
        def LookupAccountName(*_args):
            return ("configured-sid", "MISSION", 1)

        @staticmethod
        def OpenProcessToken(*_args):
            return type("Token", (), {"Close": lambda self: None})()

        @staticmethod
        def GetTokenInformation(*_args):
            return ("current-sid", 0)

        @staticmethod
        def ConvertSidToStringSid(sid):
            return {
                "configured-sid": "S-1-5-21-1-2-3-1001",
                "current-sid": "S-1-5-21-1-2-3-1002",
            }[sid]

    class FakeApi:
        @staticmethod
        def GetCurrentProcess():
            return object()

    assert not server_manager._current_user_is_configured_operator(
        frozen=True,
        platform="win32",
        registry_module=FakeRegistry,
        security_module=FakeUserSecurity,
        api_module=FakeApi,
    )


def test_normal_manager_launch_does_not_write_per_user_autostart(
    qapp, monkeypatch
):
    _ = qapp
    monkeypatch.setattr(
        server_manager,
        "ensure_autostart",
        lambda: (_ for _ in ()).throw(
            AssertionError("normal launch must not write HKCU")
        ),
    )
    monkeypatch.setattr(
        server_manager,
        "send_instance_command",
        lambda *args, **kwargs: True,
    )

    assert server_manager.main([]) == 0


def test_unauthorized_machine_startup_exits_before_creating_ui(monkeypatch):
    monkeypatch.setattr(
        server_manager,
        "_current_user_is_configured_operator",
        lambda: False,
    )
    monkeypatch.setattr(
        server_manager,
        "ServerManagerApplication",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unauthorized startup must not create the manager UI")
        ),
    )

    assert server_manager.main(["--startup"]) == 0


def test_shutdown_existing_has_deterministic_exit_codes(qapp, monkeypatch):
    _ = qapp
    monkeypatch.setattr(
        server_manager,
        "send_instance_command",
        lambda *args, **kwargs: False,
    )
    assert (
        server_manager.main(["--shutdown-existing"])
        == server_manager.NO_EXISTING_INSTANCE_EXIT_CODE
    )

    monkeypatch.setattr(
        server_manager,
        "send_instance_command",
        lambda *args, **kwargs: True,
    )
    assert server_manager.main(["--shutdown-existing"]) == 0

    def fail(*_args, **_kwargs):
        raise RuntimeError("instance failure")

    monkeypatch.setattr(server_manager, "send_instance_command", fail)
    assert (
        server_manager.main(["--shutdown-existing"])
        == server_manager.INSTANCE_ERROR_EXIT_CODE
    )


def test_single_instance_listener_is_limited_to_the_current_user(qapp):
    window, _client = make_window(qapp)
    coordinator = server_manager.InstanceCoordinator(
        window,
        lambda: None,
        instance_name=f"MissionLegalServerManager-test-{uuid.uuid4().hex}",
    )

    assert (
        coordinator.server.socketOptions()
        & server_manager.QLocalServer.UserAccessOption
    )

    coordinator.server.close()
    window.deleteLater()
