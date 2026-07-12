from datetime import date, datetime
from pathlib import Path

from sqlalchemy import inspect


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def model_snapshot(instance, extra_fields=()):
    mapper = inspect(instance).mapper
    payload = {
        attribute.key: json_value(getattr(instance, attribute.key))
        for attribute in mapper.column_attrs
    }
    for field in extra_fields:
        payload[field] = json_value(getattr(instance, field, None))
    return payload


def serialize_result(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"__type__": "date", "value": value.isoformat()}
    if isinstance(value, Path):
        return {"__type__": "path", "value": str(value)}
    if isinstance(value, dict):
        return {str(key): serialize_result(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_result(item) for item in value]
    try:
        snapshot = model_snapshot(value)
    except Exception as exc:
        raise TypeError(f"Unsupported API result type: {type(value).__name__}") from exc
    return {"__type__": "record", "value": {key: serialize_result(item) for key, item in snapshot.items()}}
