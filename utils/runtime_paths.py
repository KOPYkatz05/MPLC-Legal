import os
import sys
from pathlib import Path


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def resource_root():
    """Return the read-only source/bundle root containing application assets."""
    return Path(__file__).resolve().parents[1]


def resource_path(*parts):
    return resource_root().joinpath(*parts)


def runtime_logs_dir():
    """Return a writable log directory for source and packaged processes."""
    if not is_frozen():
        path = resource_root() / "logs"
    elif os.environ.get("MISSION_LEGAL_SERVER_PROCESS") == "1":
        from database.runtime import get_app_data_dir

        path = get_app_data_dir() / "Logs"
    else:
        from database.runtime import get_client_data_dir

        path = get_client_data_dir() / "Logs"

    path.mkdir(parents=True, exist_ok=True)
    return path
