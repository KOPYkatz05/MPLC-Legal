"""Per-user Mission Legal Server tray manager."""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import importlib
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from utils.runtime_paths import resource_path
from version import APP_VERSION


AUTOSTART_VALUE_NAME = "Mission Legal Server Manager"
INSTANCE_COMMAND_SHOW = "show"
INSTANCE_COMMAND_QUIT = "quit"
NO_EXISTING_INSTANCE_EXIT_CODE = 3
INSTANCE_ERROR_EXIT_CODE = 4
CONNECTION_SMOKE_ERROR_EXIT_CODE = 5
AUTOSTART_ERROR_EXIT_CODE = 6
_MANAGER_OPERATOR_REGISTRY_PATH = r"SOFTWARE\MissionLegal\Server"
_MANAGER_OPERATOR_REGISTRY_VALUE = "ManagerOperatorAccount"


def create_management_client():
    from server.management_pipe import MissionLegalManagementClient

    return MissionLegalManagementClient()


def _instance_name():
    identity = "|".join(
        [
            os.environ.get("USERDOMAIN", ""),
            os.environ.get("USERNAME", ""),
            getpass.getuser(),
            str(Path.home()),
        ]
    ).casefold()
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"MissionLegalServerManager-{suffix}"


def _autostart_command():
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return f'"{executable}" --startup'

    executable = Path(sys.executable).resolve()
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.exists():
        executable = pythonw
    script = Path(__file__).resolve()
    return f'"{executable}" "{script}" --startup'


def ensure_autostart():
    if not sys.platform.startswith("win"):
        return False
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(
            key,
            AUTOSTART_VALUE_NAME,
            0,
            winreg.REG_SZ,
            _autostart_command(),
        )
    return True


def remove_autostart():
    if not sys.platform.startswith("win"):
        return True
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        pass
    return True


def _current_user_is_configured_operator(
    *,
    frozen=None,
    platform=None,
    registry_module=None,
    security_module=None,
    api_module=None,
):
    """Return whether this desktop token is the installer-enrolled operator.

    The installed machine-wide Run entry is evaluated at every user's sign-in.
    Only the exact user SID enrolled by Setup may keep the tray process alive.
    Development/source launches retain their existing behavior because they do
    not have the installer-owned registry contract.
    """

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if platform is None:
        platform = sys.platform
    if not platform.startswith("win") or not frozen:
        return True
    if registry_module is None:
        import winreg as registry_module
    if security_module is None:
        import win32security as security_module
    if api_module is None:
        import win32api as api_module

    access = registry_module.KEY_READ
    access |= getattr(registry_module, "KEY_WOW64_64KEY", 0)
    with registry_module.OpenKey(
        registry_module.HKEY_LOCAL_MACHINE,
        _MANAGER_OPERATOR_REGISTRY_PATH,
        0,
        access,
    ) as key:
        account, value_type = registry_module.QueryValueEx(
            key,
            _MANAGER_OPERATOR_REGISTRY_VALUE,
        )
    if value_type not in {
        registry_module.REG_SZ,
        getattr(
            registry_module,
            "REG_EXPAND_SZ",
            registry_module.REG_SZ,
        ),
    }:
        return False
    account = str(account).strip()
    if not account or len(account) > 256 or any(
        character in account for character in "\x00\r\n"
    ):
        return False
    configured_sid, _domain, account_type = security_module.LookupAccountName(
        None,
        account,
    )
    if account_type != getattr(security_module, "SidTypeUser", 1):
        return False

    token = None
    try:
        token = security_module.OpenProcessToken(
            api_module.GetCurrentProcess(),
            security_module.TOKEN_QUERY,
        )
        current_sid = security_module.GetTokenInformation(
            token,
            security_module.TokenUser,
        )[0]
        configured = security_module.ConvertSidToStringSid(configured_sid)
        current = security_module.ConvertSidToStringSid(current_sid)
        return configured.casefold() == current.casefold()
    finally:
        if token is not None:
            token.Close()


def _connect_to_instance(instance_name, timeout_ms=600):
    socket = QLocalSocket()
    socket.connectToServer(instance_name)
    if not socket.waitForConnected(timeout_ms):
        return None
    return socket


def send_instance_command(
    command,
    *,
    instance_name=None,
    timeout_ms=800,
    wait_for_exit=False,
):
    """Return True only when an existing manager accepted the command."""

    instance_name = instance_name or _instance_name()
    socket = _connect_to_instance(instance_name, timeout_ms)
    if socket is None:
        return False
    try:
        socket.write(f"{command}\n".encode("utf-8"))
        if not socket.waitForBytesWritten(timeout_ms):
            raise RuntimeError("The manager did not accept the instance command.")
        if not socket.waitForReadyRead(timeout_ms):
            raise RuntimeError("The manager did not acknowledge the instance command.")
        acknowledged = socket.readAll().data().decode("utf-8", errors="replace").strip()
        if acknowledged != "ok":
            raise RuntimeError("The manager rejected the instance command.")
    finally:
        socket.disconnectFromServer()

    if wait_for_exit:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            probe = _connect_to_instance(instance_name, 100)
            if probe is None:
                return True
            probe.disconnectFromServer()
            time.sleep(0.05)
        raise RuntimeError("The existing manager did not exit in time.")
    return True


class InstanceCoordinator(QObject):
    def __init__(self, window, exit_callback, *, instance_name=None, parent=None):
        super().__init__(parent)
        self.window = window
        self.exit_callback = exit_callback
        self.instance_name = instance_name or _instance_name()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self._connections = set()
        self.server.newConnection.connect(self._accept_connections)

    def listen(self):
        if self.server.listen(self.instance_name):
            return True
        QLocalServer.removeServer(self.instance_name)
        return self.server.listen(self.instance_name)

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            self._connections.add(connection)
            connection.readyRead.connect(
                lambda connection=connection: self._read_command(connection)
            )
            connection.disconnected.connect(
                lambda connection=connection: self._connections.discard(connection)
            )

    def _read_command(self, connection):
        command = connection.readAll().data().decode("utf-8", errors="replace").strip()
        if command == INSTANCE_COMMAND_SHOW:
            self.window.show_and_activate()
            accepted = True
        elif command == INSTANCE_COMMAND_QUIT:
            accepted = True
        else:
            accepted = False
        connection.write(b"ok\n" if accepted else b"error\n")
        connection.flush()
        connection.waitForBytesWritten(250)
        connection.disconnectFromServer()
        if command == INSTANCE_COMMAND_QUIT and accepted:
            QTimer.singleShot(0, self.exit_callback)


def _atomic_json_write(path, payload):
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f"{target.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run_connection_smoke(result_path, client_factory=create_management_client):
    """Exercise the installed management channel without creating any Qt UI."""

    try:
        from server.management_pipe import PROTOCOL_VERSION

        client = client_factory()
        result = client.request("get_status", {})
        if not isinstance(result, dict):
            raise RuntimeError("The management status response was invalid.")
        state = str(result.get("state") or "").lower()
        if state != "running":
            raise RuntimeError("The server service is not running.")
        payload = {
            "status": "ok",
            "protocol": int(
                getattr(client, "protocol_version", PROTOCOL_VERSION)
            ),
            "app_version": str(result.get("app_version") or ""),
        }
        if not payload["app_version"]:
            raise RuntimeError("The management status response has no app version.")
        _atomic_json_write(result_path, payload)
        return 0
    except Exception:
        try:
            _atomic_json_write(
                result_path,
                {
                    "status": "error",
                    "protocol": None,
                    "app_version": None,
                },
            )
        except Exception:
            pass
        return CONNECTION_SMOKE_ERROR_EXIT_CODE


def run_package_smoke_test():
    update_config_asset = (
        resource_path("server_release.json")
        if getattr(sys, "frozen", False)
        else resource_path("deployment", "server_release.json")
    )
    required_assets = [
        resource_path("assets", "styles", "theme.qss"),
        resource_path(
            "assets",
            "icons",
            "server_manager",
            "server_manager_icon_256.png",
        ),
        resource_path(
            "assets",
            "icons",
            "server_manager",
            "server_manager_tray_64.png",
        ),
        update_config_asset,
    ]
    missing = [str(path) for path in required_assets if not path.is_file()]
    if missing:
        print(json.dumps({"status": "error", "missing": missing}, sort_keys=True))
        return 1
    from server.management_pipe import MissionLegalManagementClient

    if not callable(MissionLegalManagementClient):
        return 1
    with contextlib.redirect_stdout(io.StringIO()):
        ui_module = importlib.import_module("ui.server_manager_window")
    if not callable(getattr(ui_module, "ServerManagerWindow", None)):
        return 1
    from services.server_update_service import load_server_update_config

    if load_server_update_config(update_config_asset) is None:
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "role": "server-manager",
                "app_version": APP_VERSION,
                "assets": len(required_assets),
            },
            sort_keys=True,
        )
    )
    return 0


def load_stylesheet(app):
    theme = resource_path("assets", "styles", "theme.qss")
    try:
        app.setStyleSheet(theme.read_text(encoding="utf-8"))
    except OSError:
        pass


class ServerManagerApplication(QObject):
    def __init__(
        self,
        app,
        *,
        startup_hidden=False,
        management_client=None,
        request_runner=None,
    ):
        super().__init__(app)
        from ui.server_manager_window import ServerManagerWindow

        self.app = app
        self.window = ServerManagerWindow(
            management_client=management_client,
            request_runner=request_runner,
        )
        self.icon = QIcon(
            str(
                resource_path(
                    "assets",
                    "icons",
                    "server_manager",
                    "server_manager_icon_256.png",
                )
            )
        )
        self.tray_icon = QSystemTrayIcon(
            QIcon(
                str(
                    resource_path(
                        "assets",
                        "icons",
                        "server_manager",
                        "server_manager_tray_64.png",
                    )
                )
            ),
            self,
        )
        self.window.setWindowIcon(self.icon)
        self.tray_icon.setToolTip("Mission Legal Server — Checking")
        self._build_tray_menu()
        self.tray_icon.activated.connect(self._tray_activated)
        self.window.server_state_changed.connect(self._state_changed)
        self.window.server_address_availability_changed.connect(
            self.copy_address_action.setEnabled
        )
        self.window.update_launched.connect(self.exit_manager)
        self.tray_icon.show()
        if not startup_hidden or not QSystemTrayIcon.isSystemTrayAvailable():
            self.window.show_and_activate()

    def _build_tray_menu(self):
        menu = QMenu()
        open_action = QAction("Open Server Manager", menu)
        open_action.triggered.connect(self.window.show_and_activate)
        menu.addAction(open_action)

        pairing_action = QAction("Generate Pairing Code", menu)
        pairing_action.triggered.connect(
            lambda checked=False: self.window.show_pairing(generate=True)
        )
        menu.addAction(pairing_action)

        self.copy_address_action = QAction("Copy Server Address", menu)
        self.copy_address_action.setEnabled(self.window.server_address_available)
        self.copy_address_action.triggered.connect(
            self._copy_server_address_from_tray
        )
        menu.addAction(self.copy_address_action)
        menu.addSeparator()

        exit_action = QAction("Exit Manager", menu)
        exit_action.triggered.connect(self.exit_manager)
        menu.addAction(exit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_menu = menu

    def _tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
        ):
            self.window.show_and_activate()

    def _state_changed(self, state):
        label = {
            "starting": "Starting",
            "running": "Running",
            "restarting": "Restarting",
            "stopping": "Stopping",
            "unavailable": "Unavailable",
        }.get(str(state).casefold(), "Unavailable")
        self.tray_icon.setToolTip(f"Mission Legal Server — {label}")

    def _copy_server_address_from_tray(self):
        if not self.window.copy_server_address():
            return
        self.tray_icon.showMessage(
            "Mission Legal Server",
            "Server address copied to the clipboard.",
            QSystemTrayIcon.Information,
            2500,
        )

    def exit_manager(self):
        self.tray_icon.hide()
        self.window.request_exit()
        self.app.quit()


def _parser():
    parser = argparse.ArgumentParser(description="Mission Legal Server Manager")
    parser.add_argument("--startup", action="store_true")
    parser.add_argument("--install-autostart", action="store_true")
    parser.add_argument("--shutdown-existing", action="store_true")
    parser.add_argument("--remove-autostart", action="store_true")
    parser.add_argument("--package-smoke-test", action="store_true")
    parser.add_argument("--connection-smoke-test", metavar="RESULT_JSON_PATH")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)

    if args.remove_autostart:
        try:
            remove_autostart()
        except Exception:
            return AUTOSTART_ERROR_EXIT_CODE
        return 0
    if args.install_autostart:
        try:
            ensure_autostart()
        except Exception:
            return AUTOSTART_ERROR_EXIT_CODE
        if not args.startup:
            return 0
    if args.package_smoke_test:
        return run_package_smoke_test()
    if args.connection_smoke_test:
        return run_connection_smoke(args.connection_smoke_test)

    if args.startup:
        try:
            if not _current_user_is_configured_operator():
                return 0
        except Exception:
            # A machine-wide startup command must fail closed and silently when
            # its installer-owned identity contract cannot be verified.
            return 0

    if args.shutdown_existing:
        core = QCoreApplication.instance() or QCoreApplication(
            [sys.argv[0], "--shutdown-existing"]
        )
        _ = core
        try:
            contacted = send_instance_command(
                INSTANCE_COMMAND_QUIT,
                wait_for_exit=True,
            )
        except Exception:
            return INSTANCE_ERROR_EXIT_CODE
        return 0 if contacted else NO_EXISTING_INSTANCE_EXIT_CODE

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Mission Legal Server Manager")
    app.setOrganizationName("Mission Legal")
    app.setQuitOnLastWindowClosed(False)
    load_stylesheet(app)

    try:
        if send_instance_command(INSTANCE_COMMAND_SHOW):
            return 0
    except Exception:
        return INSTANCE_ERROR_EXIT_CODE

    manager = ServerManagerApplication(app, startup_hidden=args.startup)
    coordinator = InstanceCoordinator(manager.window, manager.exit_manager, parent=app)
    if not coordinator.listen():
        return INSTANCE_ERROR_EXIT_CODE
    app._mission_legal_server_manager = manager
    app._mission_legal_instance_coordinator = coordinator
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
