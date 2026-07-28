"""Small reusable loading indicators for lightweight in-page feedback."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class LoadingIcon(QWidget):
    """A compact Mission Legal-style indeterminate loading ring."""

    def __init__(self, parent=None, *, size=18, color="#0F8D94"):
        super().__init__(parent)
        self._angle = 0
        self._color = QColor(color)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(size, size)
        self.hide()

    def start(self):
        self._angle = 0
        self.show()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _advance(self):
        self._angle = (self._angle + 28) % 360
        self.update()

    def paintEvent(self, event):
        _ = event
        inset = 3
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(
            inset,
            inset,
            self.width() - inset * 2,
            self.height() - inset * 2,
            -self._angle * 16,
            235 * 16,
        )


def create_loading_icon(parent=None, *, size=18, color="#0F8D94"):
    """Create the shared compact loading icon used by in-page status areas."""
    return LoadingIcon(parent, size=size, color=color)


__all__ = ["LoadingIcon", "create_loading_icon"]
