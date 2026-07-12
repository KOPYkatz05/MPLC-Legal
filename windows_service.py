import os
import socket
from pathlib import Path


SERVICE_NAME = "MissionLegalServer"
DISPLAY_NAME = "Mission Legal Server"
DESCRIPTION = "Provides the encrypted local API and authoritative database for Mission Legal."


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

                os.environ["MISSION_LEGAL_SERVER_PROCESS"] = "1"
                if not os.environ.get("MISSION_LEGAL_DATA_DIR"):
                    program_data = os.environ.get("PROGRAMDATA")
                    if program_data:
                        os.environ["MISSION_LEGAL_DATA_DIR"] = str(
                            Path(program_data) / "MissionLegal"
                        )
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


def main():
    _servicemanager, _event, _service, service_util = _require_pywin32()
    if "MissionLegalWindowsService" not in globals():
        raise RuntimeError("Windows service class is unavailable")
    service_util.HandleCommandLine(MissionLegalWindowsService)


if __name__ == "__main__":
    main()
