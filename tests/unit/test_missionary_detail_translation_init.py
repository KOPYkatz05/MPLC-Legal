from types import SimpleNamespace

from PySide6.QtWidgets import QPushButton

from ui.pages.missionary_detail_page import MissionaryDetailPage


def test_pivot_translation_is_safe_before_tabs_are_constructed():
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)

    page._set_pivot_text("overview", "Overview")


def test_pivot_translation_updates_animated_tab_strip(qapp):
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    button = QPushButton("Old")
    page.tab_bar = SimpleNamespace(buttons={"overview": button})

    page._set_pivot_text("overview", "Overview")

    assert button.text() == "Overview"
