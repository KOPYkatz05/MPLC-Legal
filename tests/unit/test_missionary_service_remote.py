from datetime import date

from services import missionary_service as module


class FakeApiClient:
    def __init__(self):
        self.calls = []

    def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs))
        return {"items": [{"id": 7, "full_name": "Ada Example", "status": "ACTIVE"}]}

    def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs))
        if path == "/v1/missionaries":
            return {"id": 8, "full_name": kwargs["json"]["full_name"]}
        if path.endswith("/archive"):
            return {"archived": True}
        if path.endswith("/trash"):
            return {"trashed": True}
        return {"restored": True}

    def patch(self, path, **kwargs):
        self.calls.append(("PATCH", path, kwargs))
        return {"updated": True}


def _remote_service(monkeypatch):
    client = FakeApiClient()
    monkeypatch.setattr(
        module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    return module.MissionaryService(), client


def test_remote_list_returns_attribute_compatible_records(monkeypatch):
    service, client = _remote_service(monkeypatch)

    rows = service.get_all_missionaries()

    assert rows[0].id == 7
    assert rows[0].full_name == "Ada Example"
    assert client.calls[0][2]["params"]["status_filter"] == "ACTIVE"
    assert service.onedrive_service is None


def test_remote_create_and_update_serialize_dates(monkeypatch):
    service, client = _remote_service(monkeypatch)

    created = service.create_missionary(
        "Ada Example", "100", arrival_date=date(2026, 7, 12)
    )
    updated = service.update_fields(8, {"visa_expiration": date(2027, 7, 12)})

    assert created.id == 8
    assert updated is True
    assert client.calls[0][2]["json"]["arrival_date"] == "2026-07-12"
    assert client.calls[0][2]["json"]["last_entry_date"] == "2026-07-12"
    assert client.calls[1][2]["json"]["fields"]["visa_expiration"] == "2027-07-12"


def test_remote_create_and_update_normalize_name_whitespace(monkeypatch):
    service, client = _remote_service(monkeypatch)

    service.create_missionary(
        full_name="  Smith,  Jane\tMarie  ", missionary_code="M1"
    )
    service.update_fields(8, {"full_name": "  Jones,  Ana   Lucia "})

    assert client.calls[0][2]["json"]["full_name"] == "Smith, Jane Marie"
    assert client.calls[1][2]["json"]["fields"]["full_name"] == (
        "Jones, Ana Lucia"
    )


def test_remote_last_entry_date_can_be_updated_independently(monkeypatch):
    service, client = _remote_service(monkeypatch)

    service.update_fields(8, {"last_entry_date": date(2026, 8, 8)})

    fields = client.calls[0][2]["json"]["fields"]
    assert fields == {"last_entry_date": "2026-08-08"}
