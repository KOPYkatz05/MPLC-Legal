from services.settings_service import SettingsService


class FakeSettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def _service():
    service = SettingsService.__new__(SettingsService)
    service._settings = FakeSettings()
    return service


def test_automatic_update_checks_default_to_enabled():
    assert _service().get_automatic_updates_enabled() is True


def test_automatic_update_preference_persists():
    service = _service()

    service.set_automatic_updates_enabled(False)
    assert service.get_automatic_updates_enabled() is False

    service.set_automatic_updates_enabled(True)
    assert service.get_automatic_updates_enabled() is True


def test_page_default_views_persist_and_invalid_values_use_safe_defaults():
    service = _service()

    assert service.get_calendar_default_view() == "calendar"
    assert service.set_calendar_default_view("history") == "history"
    assert service.get_calendar_default_view() == "history"
    assert service.set_calendar_default_view("unknown") == "calendar"

    assert service.get_analytics_default_view() == "general"
    assert service.set_analytics_default_view("documents") == "documents"
    assert service.get_analytics_default_view() == "documents"

    assert service.get_missionaries_default_view() == "active"
    assert service.set_missionaries_default_view("archive") == "archive"
    assert service.get_missionaries_default_view() == "archive"
