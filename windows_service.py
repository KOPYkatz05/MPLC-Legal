import os
import re
import socket
import sys
import threading
from pathlib import Path


SERVICE_NAME = "MissionLegalServer"
DISPLAY_NAME = "Mission Legal Server"
DESCRIPTION = "Provides the encrypted local API and authoritative database for Mission Legal."
_INSTALLED_SERVICE_ENVIRONMENT_OVERRIDES = (
    "MISSION_LEGAL_DATA_DIR",
    "MISSION_LEGAL_DATABASE_PATH",
    "MISSION_LEGAL_TLS_CERT",
    "MISSION_LEGAL_TLS_KEY",
    "MISSION_LEGAL_SERVER_HOST",
    "MISSION_LEGAL_SERVER_PORT",
)
_MANAGER_OPERATOR_REGISTRY_PATH = r"SOFTWARE\MissionLegal\Server"
_MANAGER_OPERATOR_REGISTRY_VALUE = "ManagerOperatorAccount"
_SID_PATTERN = re.compile(r"^S-1-\d+(?:-\d+)+$")


def _configure_service_runtime_environment(*, frozen=None, environment=None):
    """Bind an installed service to its installer-owned runtime paths.

    Development entry points intentionally support environment overrides. A
    frozen Windows service must not inherit those overrides from the machine
    account because the installer protects, backs up, and publishes state only
    from ProgramData\\MissionLegal.
    """

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    environment = os.environ if environment is None else environment
    environment["MISSION_LEGAL_SERVER_PROCESS"] = "1"

    program_data = environment.get("PROGRAMDATA")
    if frozen:
        if not program_data:
            raise RuntimeError(
                "The installed Mission Legal service cannot locate Windows ProgramData."
            )
        program_data_path = Path(program_data).expanduser()
        if not program_data_path.is_absolute():
            raise RuntimeError(
                "The installed Mission Legal service received an invalid ProgramData path."
            )
        data_dir = program_data_path.resolve() / "MissionLegal"
        for name in _INSTALLED_SERVICE_ENVIRONMENT_OVERRIDES:
            environment.pop(name, None)
        environment["MISSION_LEGAL_DATA_DIR"] = str(data_dir)
        return data_dir

    if not environment.get("MISSION_LEGAL_DATA_DIR") and program_data:
        data_dir = Path(program_data).expanduser().resolve() / "MissionLegal"
        environment["MISSION_LEGAL_DATA_DIR"] = str(data_dir)
        return data_dir
    configured = environment.get("MISSION_LEGAL_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else None


def _read_manager_operator_account(*, registry_module=None):
    if registry_module is None:
        import winreg as registry_module

    access = registry_module.KEY_READ
    access |= getattr(registry_module, "KEY_WOW64_64KEY", 0)
    try:
        with registry_module.OpenKey(
            registry_module.HKEY_LOCAL_MACHINE,
            _MANAGER_OPERATOR_REGISTRY_PATH,
            0,
            access,
        ) as key:
            value, value_type = registry_module.QueryValueEx(
                key,
                _MANAGER_OPERATOR_REGISTRY_VALUE,
            )
    except OSError as exc:
        raise RuntimeError(
            "The installed Server Manager operator account is not configured."
        ) from exc
    if value_type not in {
        registry_module.REG_SZ,
        getattr(registry_module, "REG_EXPAND_SZ", registry_module.REG_SZ),
    }:
        raise RuntimeError(
            "The installed Server Manager operator account has an invalid registry type."
        )
    account = str(value).strip()
    if not account or len(account) > 256 or any(
        character in account for character in "\x00\r\n"
    ):
        raise RuntimeError(
            "The installed Server Manager operator account is invalid."
        )
    return account


def _resolve_manager_operator_sid(
    *,
    frozen=None,
    environment=None,
    registry_module=None,
    security_module=None,
    api_module=None,
):
    """Resolve the one local Windows account enrolled by Server Setup."""

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    environment = os.environ if environment is None else environment
    if security_module is None:
        import win32security as security_module
    if api_module is None:
        import win32api as api_module

    configured_sid = str(
        environment.get("MISSION_LEGAL_MANAGER_OPERATOR_SID") or ""
    ).strip()
    if configured_sid:
        try:
            sid = security_module.ConvertStringSidToSid(configured_sid)
            canonical = security_module.ConvertSidToStringSid(sid)
        except Exception as exc:
            raise RuntimeError(
                "MISSION_LEGAL_MANAGER_OPERATOR_SID is not a valid Windows SID."
            ) from exc
    elif frozen:
        account = _read_manager_operator_account(
            registry_module=registry_module
        )
        try:
            sid, _domain, account_type = security_module.LookupAccountName(
                None,
                account,
            )
            canonical = security_module.ConvertSidToStringSid(sid)
        except Exception as exc:
            raise RuntimeError(
                "Windows could not resolve the installed Server Manager operator "
                f"account: {account}"
            ) from exc
        if account_type != getattr(security_module, "SidTypeUser", 1):
            raise RuntimeError(
                "The installed Server Manager operator must identify one Windows "
                "user account, not a group or other security principal."
            )
    else:
        token = None
        try:
            token = security_module.OpenProcessToken(
                api_module.GetCurrentProcess(),
                security_module.TOKEN_QUERY,
            )
            sid = security_module.GetTokenInformation(
                token,
                security_module.TokenUser,
            )[0]
            canonical = security_module.ConvertSidToStringSid(sid)
        except Exception as exc:
            raise RuntimeError(
                "Windows could not resolve the current development account SID."
            ) from exc
        finally:
            if token is not None:
                token.Close()

    if not _SID_PATTERN.fullmatch(str(canonical)):
        raise RuntimeError("The resolved Server Manager operator SID is invalid.")
    return str(canonical)


def _require_pywin32():
    try:
        import servicemanager
        import win32event
        import win32service
        import win32serviceutil
    except ImportError as exc:
        raise RuntimeError(
            "The Windows service requires pywin32. Install the locked project dependencies."
        ) from exc
    return servicemanager, win32event, win32service, win32serviceutil


try:
    servicemanager, win32event, win32service, win32serviceutil = _require_pywin32()
except RuntimeError:
    if __name__ == "__main__":
        raise
else:
    class MissionLegalWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.server = None
            self.management_broker = None
            self.management_thread = None
            self.restart_requested = threading.Event()
            self.stopping = threading.Event()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if hasattr(self, "stopping"):
                self.stopping.set()
            if getattr(self, "management_broker", None) is not None:
                self.management_broker.stop()
            if self.server is not None:
                self.server.should_exit = True
            win32event.SetEvent(self.stop_event)

        def _request_api_restart(self):
            if getattr(self, "stopping", None) is not None and self.stopping.is_set():
                raise RuntimeError("The Windows service is stopping.")
            if self._api_runtime_state() != "running":
                raise RuntimeError("The API runtime is not ready to restart.")
            self.restart_requested.set()
            if self.server is not None:
                self.server.should_exit = True

        def _api_runtime_state(self):
            """Report Uvicorn readiness without probing through the public API."""

            stopping = getattr(self, "stopping", None)
            if stopping is not None and stopping.is_set():
                return "stopping"
            restart_requested = getattr(self, "restart_requested", None)
            if restart_requested is not None and restart_requested.is_set():
                return "restarting"
            server = getattr(self, "server", None)
            if server is None:
                return "starting"
            if getattr(server, "should_exit", False):
                return "stopping"
            return "running" if getattr(server, "started", False) else "starting"

        def _log_management_error(self, exc):
            servicemanager.LogErrorMsg(
                f"{DISPLAY_NAME} management channel error: {exc}"
            )

        def _start_management_broker(self):
            from server.management import MissionLegalManagement
            from server.management_pipe import MissionLegalManagementPipeServer

            operator_sid = _resolve_manager_operator_sid()
            management = MissionLegalManagement(
                restart_callback=self._request_api_restart,
                state_provider=self._api_runtime_state,
            )
            self.management_broker = MissionLegalManagementPipeServer(
                management,
                operator_sid=operator_sid,
            )
            self.management_thread = threading.Thread(
                target=self.management_broker.serve_forever,
                kwargs={"error_callback": self._log_management_error},
                name="MissionLegalServerManagerPipe",
                daemon=True,
            )
            self.management_thread.start()
            servicemanager.LogInfoMsg(
                f"{DISPLAY_NAME} local management channel started"
            )

        def SvcDoRun(self):
            servicemanager.LogInfoMsg(f"{DISPLAY_NAME} starting on {socket.gethostname()}")
            try:
                import uvicorn

                _configure_service_runtime_environment()
                if not hasattr(self, "restart_requested"):
                    self.restart_requested = threading.Event()
                if not hasattr(self, "stopping"):
                    self.stopping = threading.Event()
                if not hasattr(self, "management_broker"):
                    self.management_broker = None
                if not hasattr(self, "management_thread"):
                    self.management_thread = None
                cert = os.environ.get("MISSION_LEGAL_TLS_CERT")
                key = os.environ.get("MISSION_LEGAL_TLS_KEY")
                if not cert or not key:
                    from server.tls import generate_local_tls

                    paths = generate_local_tls()
                    cert = str(paths["server_cert"])
                    key = str(paths["server_key"])
                from server.configuration import load_server_configuration

                saved = load_server_configuration()
                if saved.get("mission_storage_root"):
                    os.environ["MISSIONS_ROOT"] = saved["mission_storage_root"]
                try:
                    self._start_management_broker()
                except Exception as exc:
                    # Keep the authoritative HTTPS API available. The installer
                    # separately requires the management connection smoke test,
                    # so a new release cannot be accepted in this degraded state.
                    self._log_management_error(exc)
                config = uvicorn.Config(
                    "server.app:app",
                    host=os.environ.get(
                        "MISSION_LEGAL_SERVER_HOST", saved.get("host", "0.0.0.0")
                    ),
                    port=int(
                        os.environ.get(
                            "MISSION_LEGAL_SERVER_PORT", saved.get("port", 8765)
                        )
                    ),
                    ssl_certfile=cert,
                    ssl_keyfile=key,
                    # Windows services do not have normal stdout/stderr streams.
                    # Uvicorn's automatic colour detection calls isatty() on
                    # those streams while configuring its formatters.
                    use_colors=False,
                    proxy_headers=False,
                    server_header=False,
                )
                while not self.stopping.is_set():
                    self.restart_requested.clear()
                    self.server = uvicorn.Server(config)
                    self.server.run()
                    self.server = None
                    if self.stopping.is_set() or not self.restart_requested.is_set():
                        break
            except Exception as exc:
                servicemanager.LogErrorMsg(f"{DISPLAY_NAME} failed: {exc}")
                raise
            finally:
                if getattr(self, "management_broker", None) is not None:
                    self.management_broker.stop()
                self.server = None
                servicemanager.LogInfoMsg(f"{DISPLAY_NAME} stopped")


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--package-smoke-test"]:
        from utils.package_smoke import run_server_package_smoke_test

        return run_server_package_smoke_test()

    service_manager, _event, _service, service_util = _require_pywin32()
    if "MissionLegalWindowsService" not in globals():
        raise RuntimeError("Windows service class is unavailable")

    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        service_manager.Initialize()
        service_manager.PrepareToHostSingle(MissionLegalWindowsService)
        service_manager.StartServiceCtrlDispatcher()
        return

    service_util.HandleCommandLine(MissionLegalWindowsService)


if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        raise SystemExit(result)
