from types import SimpleNamespace

from ui import main_window as main_window_module
from ui.main_window import MainWindow, NavigationContext
from ui.pages import reports_page as reports_page_module
from ui.pages import settings_page as settings_page_module
from ui.pages.reports_page import ReportsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.trash_page import TrashPage


class DeferredThreadPool:
    def __init__(self):
        self.tasks = []

    def start(self, task):
        self.tasks.append(task)

    def run_next(self, qapp):
        self.tasks.pop(0).run()
        qapp.processEvents()


class CountingReportsService:
    def __init__(self):
        self.calls = 0

    def get_data(self):
        self.calls += 1
        return {
            "missionaries": [],
            "documents": [],
            "stage_history": [],
            "completed_tasks": [],
        }


class CountingTrashService:
    def __init__(self):
        self.calls = 0

    def get_trashed(self):
        self.calls += 1
        return []


class FakeSettingsService:
    def get_language(self):
        return "en"

    def get_storage_root(self):
        return "C:/ClientDocuments"

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


class CountingApiClient:
    def __init__(self):
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return {"mission_storage_root": "C:/ServerDocuments"}


class FakeStack:
    def __init__(self, current=None):
        self.current = current

    def currentWidget(self):
        return self.current

    def setCurrentWidget(self, widget):
        self.current = widget


def test_reports_navigation_dispatches_once_and_reuses_fresh_cache(
    monkeypatch,
    qapp,
):
    service = CountingReportsService()
    monkeypatch.setattr(
        reports_page_module,
        "ReportsDataService",
        lambda: service,
    )
    page = ReportsPage(None)
    pool = DeferredThreadPool()
    page._refresh_loader._thread_pool = pool
    window = MainWindow.__new__(MainWindow)
    window.reports_page = page

    try:
        assert service.calls == 0

        MainWindow._on_nav_changed(window, "reports", 6)

        assert service.calls == 0
        assert len(pool.tasks) == 1

        pool.run_next(qapp)
        assert service.calls == 1
        assert page._analytics_snapshot is not None

        MainWindow._on_nav_changed(window, "reports", 6)
        assert service.calls == 1
        assert pool.tasks == []
    finally:
        page.close()


def test_trash_does_not_load_data_in_constructor(
    monkeypatch,
    qapp,
):
    trash_service = CountingTrashService()
    monkeypatch.setattr(
        "ui.pages.trash_page.MissionaryService",
        lambda: trash_service,
    )
    trash = TrashPage(None)

    try:
        assert trash_service.calls == 0
    finally:
        trash.close()


def test_settings_server_configuration_is_lazy_and_background_dispatched(
    monkeypatch,
    qapp,
):
    client = CountingApiClient()
    monkeypatch.setattr(
        settings_page_module.MissionLegalApiClient,
        "from_environment",
        classmethod(lambda cls: client),
    )
    page = SettingsPage(
        SimpleNamespace(
            settings_service=FakeSettingsService(),
        )
    )
    pool = DeferredThreadPool()
    page._server_configuration_loader._thread_pool = pool

    try:
        assert client.calls == []
        assert page.storage_input.text() == ""

        page.request_refresh()
        assert client.calls == []
        assert len(pool.tasks) == 1

        pool.run_next(qapp)
        assert client.calls == ["/v1/server/configuration"]
        assert page.storage_input.text() == "C:/ServerDocuments"

        page.request_refresh()
        assert client.calls == ["/v1/server/configuration"]
        assert pool.tasks == []
    finally:
        page.close()


def test_open_missionary_detail_switches_before_background_lookup_finishes():
    source = object()
    stack = FakeStack(source)
    context = NavigationContext(widget=source, nav_key="missionaries")

    class FakeDetail:
        requested_missionary_id = None

        def __init__(self):
            self.calls = []
            self.on_not_found = None

        def load_missionary_by_id(self, missionary_id, on_not_found=None):
            self.requested_missionary_id = missionary_id
            self.calls.append(missionary_id)
            self.on_not_found = on_not_found
            return True

    detail = FakeDetail()
    window = MainWindow.__new__(MainWindow)
    window.stack = stack
    window.detail_page = detail
    window._detail_navigation_stack = []
    window._nav_widgets = {}
    window._capture_current_view_context = lambda: context

    assert MainWindow.open_missionary_detail(window, 42) is True
    assert detail.calls == [42]
    assert stack.currentWidget() is detail
    assert window._detail_navigation_stack == [context]

    other_page = object()
    stack.setCurrentWidget(other_page)
    detail.on_not_found()
    assert stack.currentWidget() is other_page
    assert window._detail_navigation_stack == [context]


def test_task_navigation_uses_nonblocking_entry_point():
    window = MainWindow.__new__(MainWindow)
    window._clear_detail_navigation_stack_if_detail_visible = lambda: None
    window._nav_widgets = {}
    window.stack = FakeStack()
    window.set_current_key = lambda key: task_destinations.append(key)
    window.office_work_page = SimpleNamespace(
        focus_task_context=lambda title="": task_calls.append(title)
    )
    task_calls = []
    task_destinations = []

    assert MainWindow.open_task_list(
        window,
        7,
        title="Follow up",
    )
    assert task_calls == ["Follow up"]
    assert task_destinations == ["office_work"]


def test_startup_alerts_are_scheduled_without_running_feed_inline(
    monkeypatch,
):
    constructed = []

    class FakeFeed:
        def __init__(self, settings_service):
            constructed.append(settings_service)

        def startup_items(self):
            return []

    class CapturingLoader:
        def request(self, operation, **callbacks):
            self.operation = operation
            self.callbacks = callbacks

    monkeypatch.setattr(
        main_window_module,
        "NotificationFeedService",
        FakeFeed,
    )
    window = MainWindow.__new__(MainWindow)
    window.settings_service = object()
    window._startup_alerts_loader = CapturingLoader()

    MainWindow._load_startup_alerts(window)

    assert constructed == []
    assert callable(window._startup_alerts_loader.operation)
