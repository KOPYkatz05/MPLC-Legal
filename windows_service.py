import os
import socket
import sys
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

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self.server is not None:
                self.server.should_exit = True
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            servicemanager.LogInfoMsg(f"{DISPLAY_NAME} starting on {socket.gethostname()}")
            try:
                import uvicorn

                _configure_service_runtime_environment()
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
                self.server = uvicorn.Server(config)
                self.server.run()
            except Exception as exc:
                servicemanager.LogErrorMsg(f"{DISPLAY_NAME} failed: {exc}")
                raise
            finally:
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
