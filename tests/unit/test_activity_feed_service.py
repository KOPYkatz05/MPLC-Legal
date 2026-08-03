from datetime import date, datetime
from types import SimpleNamespace

from services import activity_feed_service as feed_module
from services.activity_feed_service import ActivityFeedService


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class _Session:
    def __init__(self, rows_by_model):
        self.rows_by_model = rows_by_model
        self.closed = False

    def query(self, model):
        return _Query(self.rows_by_model.get(model, []))

    def close(self):
        self.closed = True


def test_activity_feed_normalizes_and_sorts_durable_server_records(monkeypatch):
    created = datetime(2026, 6, 1, 9, 0)
    advanced = datetime(2026, 7, 8, 15, 38)
    uploaded = datetime(2026, 6, 6, 21, 42)
    session = _Session({
        feed_module.Missionary: [SimpleNamespace(id=9, created_at=created)],
        feed_module.StageHistory: [SimpleNamespace(
            id=3,
            from_stage="INTERPOL",
            to_stage="BIOMETRICS",
            notes="Ready for fingerprints",
            created_at=advanced,
        )],
        feed_module.Document: [SimpleNamespace(
            id=4,
            document_type="PASSPORT",
            file_name="passport.pdf",
            uploaded_at=uploaded,
            invalidated_at=None,
            invalidated_reason=None,
        )],
        feed_module.Appointment: [SimpleNamespace(
            id=5,
            appointment_type="Biometric",
            scheduled_date=date(2026, 7, 18),
            status="SCHEDULED",
            created_at=datetime(2026, 6, 7, 10, 0),
            closed_at=None,
        )],
        feed_module.SecretaryTaskMissionary.task_id: [],
        feed_module.SecretaryTask: [],
        feed_module.ResidencyEvent: [],
    })
    monkeypatch.setattr(feed_module, "SessionLocal", lambda: session)

    feed = ActivityFeedService().get_missionary_activity(9)

    assert feed["events"][0]["event_type"] == "stage_changed"
    assert feed["events"][0]["details"].endswith("Ready for fingerprints")
    assert {event["event_type"] for event in feed["events"]} >= {
        "missionary_created",
        "document_uploaded",
        "appointment_scheduled",
    }
    assert feed["upcoming"] == [{
        "category": "appointments",
        "event_type": "upcoming_appointment",
        "scheduled_date": date(2026, 7, 18),
        "title": "Biometric appointment",
        "details": "Scheduled",
        "entity_type": "appointment",
        "entity_id": 5,
    }]
    assert session.closed is True
