from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QDate

from ui.pages.missionary_detail.identity_section import IdentityDetailsSection
from ui.pages.missionary_detail_page import EDITABLE_DATE_FIELDS
from utils.i18n import field_label, get_i18n


class _DateEdit:
    def __init__(self, value):
        self._value = value

    def getDate(self):
        return self._value


class _MissionaryService:
    def __init__(self):
        self.calls = []

    def update_fields(self, missionary_id, updates):
        self.calls.append((missionary_id, updates))


def test_last_entry_date_is_an_editable_bilingual_detail_field():
    assert "last_entry_date" in EDITABLE_DATE_FIELDS
    i18n = get_i18n()
    i18n.set_language("en")
    assert field_label("last_entry_date") == "Last Entry into Peru"

    try:
        i18n.set_language("es")
        assert field_label("last_entry_date") == "\u00daltimo movimiento de entrada"
    finally:
        i18n.set_language("en")


def test_last_entry_date_saves_without_changing_original_arrival(monkeypatch):
    service = _MissionaryService()
    host = SimpleNamespace(
        current_missionary=SimpleNamespace(
            id=7,
            arrival_date=date(2025, 1, 15),
            last_entry_date=date(2025, 1, 15),
            visa_expiration=date(2026, 1, 15),
            field_sources=None,
        ),
        _date_edits={"last_entry_date": _DateEdit(QDate(2026, 8, 8))},
        _date_empty_on_load=set(),
        _text_edits={},
        missionary_service=service,
        _reload_missionary=lambda: None,
        _refresh_missionaries_table=lambda: None,
    )
    monkeypatch.setattr(IdentityDetailsSection, "_show_message", lambda *_a, **_k: None)

    IdentityDetailsSection(host).save()

    assert len(service.calls) == 1
    missionary_id, updates = service.calls[0]
    assert missionary_id == 7
    assert updates["last_entry_date"] == date(2026, 8, 8)
    assert "arrival_date" not in updates
    assert "visa_expiration" not in updates
