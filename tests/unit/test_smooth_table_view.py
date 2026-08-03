from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QStandardItemModel, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView

from ui.widgets.smooth_table_view import SmoothTableView


def _wheel_event(delta):
    return QWheelEvent(
        QPointF(20, 20),
        QPointF(20, 20),
        QPoint(),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )


def test_wheel_scroll_glides_and_accumulates_targets(qapp):
    table = SmoothTableView(scroll_duration=180)
    model = QStandardItemModel(100, 2, table)
    table.setModel(model)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.resize(420, 240)
    table.show()
    QTest.qWait(20)
    scrollbar = table.verticalScrollBar()
    start = scrollbar.maximum() // 2
    scrollbar.setValue(start)

    try:
        table.wheelEvent(_wheel_event(-120))
        first_target = table._vertical_glide.target

        assert first_target > start
        assert table.is_gliding
        assert scrollbar.value() < first_target
        QTest.qWait(40)
        assert start < scrollbar.value() < first_target

        table.wheelEvent(_wheel_event(-120))
        assert table._vertical_glide.target > first_target
        QTest.qWait(24)
        assert scrollbar.value() < table._vertical_glide.target

        table.stop_smooth_scroll()
        assert not table.is_gliding
    finally:
        table.close()
