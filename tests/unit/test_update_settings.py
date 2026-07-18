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
