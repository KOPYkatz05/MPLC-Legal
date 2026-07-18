from datetime import date
from pathlib import Path

from services import remote_service


class ExampleRemoteService(remote_service.RemoteServiceMixin):
    REMOTE_SERVICE = "example"
    REMOTE_METHODS = frozenset({"operation"})

    def operation(self, value):
        return f"local:{value}"


class FakeClient:
    def __init__(self):
        self.request = None

    def post(self, path, **kwargs):
        self.request = (path, kwargs)
        return {
            "result": {
                "__type__": "record",
                "value": {"id": 4, "due_date": {"__type__": "date", "value": "2026-07-12"}},
            }
        }


def test_mixin_routes_allowlisted_method_and_decodes_result(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(
        remote_service.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )

    result = ExampleRemoteService().operation(Path("sample"))

    assert result.id == 4
    assert result.due_date == date(2026, 7, 12)
    assert client.request[0] == "/v1/rpc/example/operation"
    assert client.request[1]["json"]["args"][0]["__type__"] == "path"


def test_mixin_keeps_local_behavior_without_remote_configuration(monkeypatch):
    monkeypatch.setattr(
        remote_service.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: None),
    )

    assert ExampleRemoteService().operation("value") == "local:value"
