from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget

from ui.widgets.animated_tab_strip import AnimatedTabStrip


def test_tab_strip_selects_and_settles_indicator(qtbot):
    selected = []
    host = QWidget()
    strip = AnimatedTabStrip(host)
    strip.resize(240, 30)
    strip.add_tab("active", "Active", selected.append)
    strip.add_tab("archive", "Archive", selected.append)
    host.resize(260, 40)
    host.show()
    qtbot.addWidget(host)

    strip.set_active("active", animate=False)
    qtbot.waitUntil(lambda: strip._indicator.isVisible())
    initial = strip._indicator.geometry()

    qtbot.mouseClick(strip.buttons["archive"], Qt.LeftButton)
    qtbot.wait(110)
    bridge = strip._indicator.geometry()
    qtbot.wait(160)

    assert selected == ["archive"]
    assert bridge.width() >= initial.width()
    assert strip._indicator.geometry().left() == strip.buttons["archive"].x()
    assert strip._indicator.geometry().width() == strip.buttons["archive"].width()


def test_tab_strip_repositions_indicator_after_resize(qtbot):
    strip = AnimatedTabStrip()
    strip.add_tab("one", "One", lambda key: None)
    strip.add_tab("two", "Two", lambda key: None)
    strip.resize(220, 30)
    strip.show()
    qtbot.addWidget(strip)
    strip.set_active("two", animate=False)
    qtbot.wait(20)

    strip.resize(320, 30)
    qtbot.wait(20)

    assert strip._indicator.geometry().left() == strip.buttons["two"].x()
    assert strip._indicator.geometry().width() == strip.buttons["two"].width()
