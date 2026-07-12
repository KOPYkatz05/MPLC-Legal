from datetime import date, datetime
from functools import partial
from pathlib import Path

from services.api_client import MissionLegalApiClient, RemoteRecord


def encode_remote_value(value):
    if isinstance(value, (date, datetime)):
        return {"__type__": "datetime" if isinstance(value, datetime) else "date", "value": value.isoformat()}
    if isinstance(value, Path):
        return {"__type__": "path", "value": str(value)}
    if isinstance(value, dict):
        return {str(key): encode_remote_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [encode_remote_value(item) for item in value]
    return value


def decode_remote_value(value):
    if isinstance(value, list):
        return [decode_remote_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    value_type = value.get("__type__")
    if value_type == "date":
        return date.fromisoformat(value["value"])
    if value_type == "datetime":
        return datetime.fromisoformat(value["value"])
    if value_type == "path":
        return Path(value["value"])
    if value_type == "record":
        return RemoteRecord(
            {key: decode_remote_value(item) for key, item in value["value"].items()}
        )
    return {key: decode_remote_value(item) for key, item in value.items()}


class RemoteServiceMixin:
    REMOTE_SERVICE = None
    REMOTE_METHODS = frozenset()

    def __getattribute__(self, name):
        if not name.startswith("_"):
            remote_methods = object.__getattribute__(self, "REMOTE_METHODS")
            if name in remote_methods:
                client = MissionLegalApiClient.from_environment()
                if client is not None:
                    return partial(self._remote_call, client, name)
        return super().__getattribute__(name)

    def _remote_call(self, client, method, *args, **kwargs):
        service = object.__getattribute__(self, "REMOTE_SERVICE")
        response = client.post(
            f"/v1/rpc/{service}/{method}",
            json={
                "args": encode_remote_value(args),
                "kwargs": encode_remote_value(kwargs),
            },
        )
        return decode_remote_value(response["result"])
