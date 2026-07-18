from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from ui.pages import settings_page as settings_page_module
from version import APP_VERSION


class FakeSettingsService:
    def get_language(self):
        return "en"

    def get_storage_root(self):
        return "C:/MissionDocuments"

    def get_upload_auto_ocr_enabled(self):
        return True

    def get_automatic_updates_enabled(self):
        return True

    def get_notification_settings(self):
        return {}

    def get_daily_digest_settings(self):
        return {}

    def get_daily_digest_password(self):
        return ""

    def get_next_transfer_wednesday(self):
        return None


class FakeUpdateCoordinator(QObject):
    status_changed = Signal(str)
    progress_changed = Signal(int)
    update_ready = Signal(str)

    def __init__(self, *, enabled=True):
        super().__init__()
        self.enabled = enabled
        self.manual_checks = []

    def check_for_updates(self, manual=True):
        self.manual_checks.append(bool(manual))
        return True


def _settings_page(monkeypatch):
    service = FakeSettingsService()
    monkeypatch.setattr(
        settings_page_module,
        "SettingsService",
        lambda: service,
    )
    monkeypatch.setattr(
        settings_page_module,
        "WorkspaceService",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        settings_page_module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: None),
    )
    return settings_page_module.SettingsPage(None)


def test_settings_update_controls_bind_and_start_manual_check(
    qapp,
    monkeypatch,
):
    _ = qapp
    page = _settings_page(monkeypatch)
    coordinator = FakeUpdateCoordinator()
    try:
        assert APP_VERSION in page.update_version_label.text()
        assert page.check_updates_btn.isEnabled() is False

        page.bind_update_coordinator(coordinator)

        assert page.check_updates_btn.isEnabled() is True
        assert "automatically" in page.update_status_label.text().lower()

        page.check_updates_btn.click()

        assert coordinator.manual_checks == [True]
    finally:
        page.close()
        page.deleteLater()


def test_settings_update_controls_render_coordinator_lifecycle(
    qapp,
    monkeypatch,
):
    _ = qapp
    page = _settings_page(monkeypatch)
    coordinator = FakeUpdateCoordinator()
    try:
        page.bind_update_coordinator(coordinator)

        coordinator.status_changed.emit("checking")
        assert "checking" in page.update_status_label.text().lower()

        coordinator.progress_changed.emit(42)
        assert "42%" in page.update_status_label.text()

        coordinator.update_ready.emit("0.2.0")
        coordinator.status_changed.emit("ready")
        assert page._ready_update_version == "0.2.0"
        assert "ready" in page.update_status_label.text().lower()

        coordinator.status_changed.emit("failed")
        assert "could not be completed" in page.update_status_label.text().lower()
    finally:
        page.close()
        page.deleteLater()


def test_settings_update_controls_disable_manual_check_without_source(
    qapp,
    monkeypatch,
):
    _ = qapp
    page = _settings_page(monkeypatch)
    coordinator = FakeUpdateCoordinator(enabled=False)
    try:
        page.bind_update_coordinator(coordinator)

        assert page.check_updates_btn.isEnabled() is False
        assert "not configured" in page.update_status_label.text().lower()
    finally:
        page.close()
        page.deleteLater()
