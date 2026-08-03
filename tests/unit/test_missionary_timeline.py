from datetime import datetime
from types import MethodType, SimpleNamespace

from PySide6.QtWidgets import QListWidget

from ui.pages.missionary_detail_page import MissionaryDetailPage


def _timeline_page():
    page = SimpleNamespace(
        timeline_list=QListWidget(),
        _timeline_filter="all",
        _timeline_feed={
            "upcoming": [],
            "events": [
                {
                    "category": "workflow",
                    "occurred_at": datetime(2026, 7, 8, 15, 38),
                    "title": "Advanced to BIOMETRICS",
                    "details": "INTERPOL to BIOMETRICS\nReady for fingerprints",
                },
                {
                    "category": "tasks",
                    "occurred_at": datetime(2026, 6, 6, 21, 42),
                    "title": "Task completed",
                    "details": "Review passport",
                },
            ],
        },
    )
    for name in (
        "_build_timeline_event_widget",
        "_add_timeline_heading",
        "_render_timeline",
        "_set_timeline_filter",
    ):
        method = getattr(MissionaryDetailPage, name)
        setattr(page, name, MethodType(method, page))
    page._timeline_group_label = MissionaryDetailPage._timeline_group_label
    return page


def test_timeline_uses_sized_widgets_and_date_groups(qapp):
    page = _timeline_page()

    page._render_timeline()

    assert page.timeline_list.count() == 4
    event_widget = page.timeline_list.itemWidget(page.timeline_list.item(1))
    assert event_widget is not None
    assert page.timeline_list.item(1).sizeHint().height() > 34


def test_timeline_filter_keeps_only_matching_activity(qapp):
    page = _timeline_page()

    page._set_timeline_filter("tasks")

    assert page._timeline_filter == "tasks"
    assert page.timeline_list.count() == 2
    event_widget = page.timeline_list.itemWidget(page.timeline_list.item(1))
    assert event_widget.property("activityCategory") == "tasks"
