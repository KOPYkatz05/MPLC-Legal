from PySide6.QtCore import QObject, Signal

from ui.pages import settings_page as settings_page_module
from version import APP_VERSION


class FakeSettingsService:
    def __init__(self):
        self.tab_indicator_thickness = 1

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

    def get_tab_indicator_thickness(self):
        return self.tab_indicator_thickness

    def set_tab_indicator_thickness(self, value):
        self.tab_indicator_thickness = value
        return value

    def get_calendar_default_view(self):
        return "calendar"

    def set_calendar_default_view(self, value):
        self.calendar_default_view = value

    def get_analytics_default_view(self):
        return "general"

    def set_analytics_default_view(self, value):
        self.analytics_default_view = value

    def get_missionaries_default_view(self):
        return "active"

    def set_missionaries_default_view(self, value):
        self.missionaries_default_view = value


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


def test_ui_tab_updates_tab_indicator_thickness(qapp, monkeypatch):
    _ = qapp
    page = _settings_page(monkeypatch)
    try:
        assert page.tab_thickness_slider.value() == 1
        page.tab_thickness_slider.setValue(4)

        assert page.tab_thickness_input.text() == "4"
        assert page.settings_service.get_tab_indicator_thickness() == 4
    finally:
        page.close()
        page.deleteLater()


def test_settings_has_one_real_tab_strip_and_new_tabs_save_defaults(
    qapp, monkeypatch
):
    _ = qapp
    page = _settings_page(monkeypatch)
    try:
        assert page.tabs.count() == 7
        assert not hasattr(page, "settings_top_tab_labels")

        page.calendar_default_view_combo.setCurrentIndex(
            page.calendar_default_view_combo.findData("history")
        )
        page.analytics_default_view_combo.setCurrentIndex(
            page.analytics_default_view_combo.findData("documents")
        )
        page.missionaries_default_view_combo.setCurrentIndex(
            page.missionaries_default_view_combo.findData("archive")
        )

        assert page.settings_service.calendar_default_view == "history"
        assert page.settings_service.analytics_default_view == "documents"
        assert page.settings_service.missionaries_default_view == "archive"
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
