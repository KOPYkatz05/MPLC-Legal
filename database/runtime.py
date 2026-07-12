import os
import sys
from pathlib import Path


APP_DATA_DIR_ENV = "MISSION_LEGAL_DATA_DIR"
DATABASE_PATH_ENV = "MISSION_LEGAL_DATABASE_PATH"
CLIENT_DATA_DIR_ENV = "MISSION_LEGAL_CLIENT_DATA_DIR"


def _project_root():
    return Path(__file__).resolve().parents[1]


def _program_data_root():
    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        return Path(program_data) / "MissionLegal"
    return Path.home() / "AppData" / "Local" / "MissionLegal"


def get_app_data_dir():
    configured = os.environ.get(APP_DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser().resolve()

    if getattr(sys, "frozen", False):
        return _program_data_root()

    # Keep source checkouts attached to their existing development database.
    return _project_root() / "data"


def get_database_path():
    configured = os.environ.get(DATABASE_PATH_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return get_app_data_dir() / "app.db"


def get_client_data_dir():
    configured = os.environ.get(CLIENT_DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "MissionLegal"
    return Path.home() / "AppData" / "Local" / "MissionLegal"


def ensure_runtime_directories():
    root = get_app_data_dir()
    for path in (root, root / "Backups", root / "Logs", root / "Configuration"):
        path.mkdir(parents=True, exist_ok=True)
    get_database_path().parent.mkdir(parents=True, exist_ok=True)
    return root


def sqlite_url(path=None):
    database_path = Path(path or get_database_path()).resolve()
    return f"sqlite:///{database_path.as_posix()}"
