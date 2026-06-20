from types import SimpleNamespace

from ui.pages.missionary_detail_page import MissionaryDetailPage
from ui.pages.missionaries_page import MissionariesPage


class LoadCounter:
    def __init__(self):
        self.load_count = 0

    def load_data(self):
        self.load_count += 1


def test_detail_stage_refresh_updates_related_pages():
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

    page._refresh_stage_related_pages()

    assert missionaries_page.load_count == 1
    assert dashboard_page.load_count == 1
    assert calendar_page.load_count == 1
    assert reports_page.load_count == 1


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
