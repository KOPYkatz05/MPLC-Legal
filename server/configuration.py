import json
from pathlib import Path

from database.runtime import get_app_data_dir


def server_configuration_path():
    return get_app_data_dir() / "Configuration" / "server.json"


def load_server_configuration():
    path = server_configuration_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_server_configuration(payload):
    path = server_configuration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
