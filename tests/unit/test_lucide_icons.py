import pytest
from PySide6.QtGui import QIcon

from ui.foundation.icons import app_icon, available_lucide_icons


pytest.importorskip("iconipy")


def test_app_icon_uses_lucide_map(qapp):
    icon = app_icon("sidebar.dashboard")

    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_app_icon_returns_fallback_for_missing_slot(qapp):
    fallback = QIcon()

    assert app_icon("missing.slot", fallback=fallback) is fallback


def test_available_lucide_icons_can_search():
    matches = available_lucide_icons("user")

    assert "circle-user" in matches
