from datetime import date

import pytest

from services.settings_service import (
    SettingsService,
    is_wednesday,
    transfer_dates_from_anchor,
)


class FakeQSettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


def _settings_service():
    service = SettingsService.__new__(SettingsService)
    service._settings = FakeQSettings()
    return service


def test_transfer_dates_repeat_every_six_weeks_from_anchor():
    dates = transfer_dates_from_anchor(
        date(2026, 6, 17),
        today=date(2026, 6, 1),
        count=3,
    )

    assert dates == [
        date(2026, 6, 17),
        date(2026, 7, 29),
        date(2026, 9, 9),
    ]


def test_transfer_dates_advance_past_old_anchor():
    dates = transfer_dates_from_anchor(
        date(2026, 6, 17),
        today=date(2026, 8, 1),
        count=2,
    )

    assert dates == [
        date(2026, 9, 9),
        date(2026, 10, 21),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 6, 17), True),
        ("2026-06-17", True),
        (date(2026, 6, 18), False),
        ("not-a-date", False),
    ],
)
def test_is_wednesday(value, expected):
    assert is_wednesday(value) is expected


def test_transfer_setting_saves_loads_and_clears():
    service = _settings_service()

    saved = service.set_next_transfer_wednesday(date(2026, 6, 17))

    assert saved == date(2026, 6, 17)
    assert service.get_next_transfer_wednesday() == date(2026, 6, 17)
    assert service.get_upcoming_transfer_wednesdays(
        today=date(2026, 6, 1),
        count=2,
    ) == [
        date(2026, 6, 17),
        date(2026, 7, 29),
    ]

    service.set_next_transfer_wednesday(None)

    assert service.get_next_transfer_wednesday() is None


def test_transfer_setting_accepts_any_arrival_weekday():
    service = _settings_service()

    saved = service.set_next_transfer_wednesday(date(2026, 6, 18))

    assert saved == date(2026, 6, 18)
    assert service.get_upcoming_transfer_wednesdays(
        today=date(2026, 6, 1),
        count=2,
    ) == [
        date(2026, 6, 18),
        date(2026, 7, 30),
    ]
