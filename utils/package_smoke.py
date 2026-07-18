import importlib
import json
import os
from pathlib import Path

from utils.runtime_paths import is_frozen, resource_path
from version import API_VERSION, APP_VERSION, SCHEMA_VERSION


def _progress(message):
    progress_path = os.environ.get("MISSION_LEGAL_SMOKE_PROGRESS")
    if not progress_path:
        return
    path = Path(progress_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(str(message) + "\n")


def _import_modules(module_names):
    imported = []
    for module_name in module_names:
        _progress(f"import:{module_name}:begin")
        importlib.import_module(module_name)
        _progress(f"import:{module_name}:done")
        imported.append(module_name)
    return imported


def _require_paths(paths):
    missing = [str(path) for path in paths if not Path(path).exists()]
    if missing:
        raise FileNotFoundError(
            "Package resources are missing: " + ", ".join(missing)
        )


def _result(role, imported):
    payload = {
        "role": role,
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "frozen": is_frozen(),
        "imports": imported,
        "status": "ok",
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def run_client_package_smoke_test():
    _progress("client:begin")
    from services.ocr_service import default_paddle_model_dirs

    model_dirs = default_paddle_model_dirs()
    _require_paths(
        [
            resource_path("assets", "styles", "theme.qss"),
            resource_path("assets", "icons", "lucide_icon_map.json"),
            resource_path("data", "country_names_by_code.json"),
            *model_dirs.values(),
        ]
    )
    imported = _import_modules(
        [
            "PySide6",
            "qfluentwidgets",
            "iconipy",
            "httpx",
            "cryptography",
            "keyring",
            "fitz",
            "cv2",
            "openpyxl",
            "velopack",
            "winotify",
            "PySide6.QtWebEngineWidgets",
            "PySide6.QtWebChannel",
            "keyring.backends.Windows",
            "paddle",
            "paddleocr",
        ]
    )
    from PySide6.QtWidgets import QApplication
    from ui.foundation.icons import lucide_icon

    app = QApplication.instance() or QApplication([])
    _progress("client:icon:begin")
    icon = lucide_icon("check", size=16)
    if icon is None or icon.isNull():
        raise RuntimeError("Bundled Lucide icon resources are unavailable")
    app.processEvents()
    _progress("client:ocr-init:begin")
    from services.ocr_service import OCRService

    OCRService()
    _progress("client:ocr-init:done")
    _progress("client:done")
    return _result("client", imported)


def run_server_package_smoke_test():
    _progress("server:begin")
    old_data_dir = os.environ.get("MISSION_LEGAL_DATA_DIR")
    old_server_process = os.environ.get("MISSION_LEGAL_SERVER_PROCESS")
    try:
        os.environ["MISSION_LEGAL_SERVER_PROCESS"] = "1"
        smoke_root = os.environ.get("MISSION_LEGAL_SMOKE_DATA_DIR")
        if smoke_root:
            smoke_root = Path(smoke_root)
        elif is_frozen():
            from database.runtime import get_client_data_dir

            smoke_root = get_client_data_dir() / "PackageSmoke" / str(os.getpid())
        else:
            smoke_root = resource_path("build", "package-smoke-runtime", str(os.getpid()))
        smoke_root.mkdir(parents=True, exist_ok=True)
        os.environ["MISSION_LEGAL_DATA_DIR"] = str(smoke_root)
        imported = _import_modules(
            [
                "fastapi",
                "uvicorn",
                "cryptography",
                "sqlalchemy",
                "win32serviceutil",
                "server.app",
            ]
        )
    finally:
        if old_data_dir is None:
            os.environ.pop("MISSION_LEGAL_DATA_DIR", None)
        else:
            os.environ["MISSION_LEGAL_DATA_DIR"] = old_data_dir
        if old_server_process is None:
            os.environ.pop("MISSION_LEGAL_SERVER_PROCESS", None)
        else:
            os.environ["MISSION_LEGAL_SERVER_PROCESS"] = old_server_process

    _progress("server:done")
    return _result("server", imported)
