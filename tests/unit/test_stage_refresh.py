from types import SimpleNamespace

from PySide6.QtWidgets import QDialog

import ui.pages.missionary_detail_page as detail_module
from ui.pages.missionary_detail_page import MissionaryDetailPage
from ui.pages.missionaries_page import MissionariesPage


class LoadCounter:
    def __init__(self):
        self.load_count = 0

    def load_data(self):
        self.load_count += 1


def test_archive_confirmation_precedes_navigation_and_keeps_target(monkeypatch):
    events = []
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    page.current_missionary = SimpleNamespace(id=7)

    class ArchiveDialog:
        archive_reason = "Reassigned"

        def __init__(self, parent):
            assert parent is page

        def exec(self):
            page.current_missionary = SimpleNamespace(id=99)
            return QDialog.Accepted

    page.missionary_service = SimpleNamespace(
        archive_missionary=lambda missionary_id, archive_reason: events.append(
            ("archive", missionary_id, archive_reason)
        )
    )
    missionaries_page = SimpleNamespace(
        load_data=lambda: events.append(("load",))
    )
    page.main_window = SimpleNamespace(
        stack=SimpleNamespace(
            widget=lambda index: missionaries_page,
            setCurrentIndex=lambda index: events.append(("navigate", index)),
        )
    )
    monkeypatch.setattr(detail_module, "MissionaryArchiveDialog", ArchiveDialog)
    monkeypatch.setattr(
        detail_module,
        "show_message",
        lambda parent, title, content, **kwargs: events.append(
            ("message", parent, title, content)
        ),
    )

    page._archive_missionary()

    assert events[0] == ("archive", 7, "Reassigned")
    assert events[1][0:2] == ("message", page)
    assert events[2:] == [("load",), ("navigate", 1)]


def test_detail_stage_refresh_updates_related_pages(monkeypatch):
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    missionaries_page = LoadCounter()
    dashboard_page = LoadCounter()
    calendar_page = LoadCounter()
    reports_page = LoadCounter()
    page.main_window = SimpleNamespace(
        missionaries_page=missionaries_page,
        dashboard_page=dashboard_page,
        calendar_page=calendar_page,
        reports_page=reports_page,
    )
    monkeypatch.setattr(
        "ui.pages.missionary_detail_page.QTimer.singleShot",
        lambda _delay, callback: callback(),
    )

    page._refresh_stage_related_pages()

    assert missionaries_page.load_count == 1
    assert dashboard_page.load_count == 1
    assert calendar_page.load_count == 1
    assert reports_page.load_count == 1


def test_stage_advance_refresh_reloads_detail_and_related_pages(monkeypatch):
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    page.current_missionary = SimpleNamespace(id=7)
    page.reload_count = 0
    page.related_refresh_count = 0

    def reload_missionary():
        page.reload_count += 1

    def refresh_related_pages():
        page.related_refresh_count += 1

    page._reload_missionary = reload_missionary
    page._refresh_stage_related_pages = refresh_related_pages

    page._refresh_after_stage_advance()

    assert page.reload_count == 1
    assert page.related_refresh_count == 1


def test_save_dates_refreshes_missionaries_table(monkeypatch):
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    missionaries_page = LoadCounter()
    page.main_window = SimpleNamespace(missionaries_page=missionaries_page)
    page.current_missionary = SimpleNamespace(
        id=7,
        arrival_date=None,
        visa_expiration=None,
        field_sources=None,
    )
    page._date_edits = {}
    page._text_edits = {}
    page._date_empty_on_load = set()
    page.missionary_service = SimpleNamespace(
        update_fields=lambda missionary_id, updates: None
    )
    page._reload_missionary = lambda: None

    monkeypatch.setattr(
        "ui.pages.missionary_detail_page.show_message",
        lambda *args, **kwargs: None,
    )

    page._text_edits["carnet_number"] = SimpleNamespace(
        text=lambda: "CE123456"
    )
    page.current_missionary.carnet_number = None

    page._save_dates()

    assert missionaries_page.load_count == 1


def test_batch_stage_refresh_reloads_open_selected_detail():
    page = MissionariesPage.__new__(MissionariesPage)
    detail_page = SimpleNamespace(
        current_missionary=SimpleNamespace(id=7),
        reload_count=0,
    )

    def reload_missionary():
        detail_page.reload_count += 1

    detail_page._reload_missionary = reload_missionary
    page.main_window = SimpleNamespace(detail_page=detail_page)

    page._refresh_open_detail_if_selected([3, 7, 9])

    assert detail_page.reload_count == 1


def test_batch_stage_refresh_ignores_other_open_detail():
    page = MissionariesPage.__new__(MissionariesPage)
    detail_page = SimpleNamespace(
        current_missionary=SimpleNamespace(id=11),
        reload_count=0,
    )

    def reload_missionary():
        detail_page.reload_count += 1

    detail_page._reload_missionary = reload_missionary
    page.main_window = SimpleNamespace(detail_page=detail_page)

    page._refresh_open_detail_if_selected([3, 7, 9])

    assert detail_page.reload_count == 0
