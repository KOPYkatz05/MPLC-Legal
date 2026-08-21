"""An endpoint-free drag ruler for arbitrary image rotation."""

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class InfiniteRotationRuler(QWidget):
    angleChanged = Signal(float)

    PIXELS_PER_DEGREE = 3.2
    TICK_STEP = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self._last_global_x = None
        self.setFixedHeight(56)
        self.setMinimumWidth(260)
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip(
            "Drag left or right to rotate without endpoints. Double-click to reset."
        )

    @property
    def angle(self):
        return self._angle

    @staticmethod
    def normalized_angle(angle):
        normalized = ((float(angle) + 180.0) % 360.0) - 180.0
        return 180.0 if normalized == -180.0 else normalized

    def set_angle(self, angle):
        angle = float(angle)
        if math.isclose(angle, self._angle, abs_tol=0.001):
            return
        self._angle = angle
        self.update()
        self.angleChanged.emit(angle)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_global_x = event.globalPosition().x()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._last_global_x is None:
            return super().mouseMoveEvent(event)
        current_x = event.globalPosition().x()
        delta = current_x - self._last_global_x
        self._last_global_x = current_x
        self.set_angle(self._angle - delta / self.PIXELS_PER_DEGREE)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._last_global_x is not None:
            self._last_global_x = None
            self.setCursor(Qt.SizeHorCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.set_angle(0.0)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self.set_angle(self._angle + steps)
        event.accept()

    def paintEvent(self, event):
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 23, 28, 220))
        painter.drawRoundedRect(self.rect(), 12, 12)

        center_x = self.width() / 2.0
        baseline = 39
        visible_degrees = self.width() / self.PIXELS_PER_DEGREE / 2.0
        first_tick = (
            math.floor((self._angle - visible_degrees) / self.TICK_STEP)
            * self.TICK_STEP
        )
        last_tick = self._angle + visible_degrees
        tick = first_tick
        while tick <= last_tick:
            x = center_x + (tick - self._angle) * self.PIXELS_PER_DEGREE
            is_major = int(round(tick)) % 45 == 0
            is_medium = int(round(tick)) % 15 == 0
            height = 14 if is_major else (9 if is_medium else 5)
            color = QColor(235, 239, 244, 210 if is_major else 145)
            painter.setPen(QPen(color, 2 if is_major else 1.5))
            painter.drawLine(int(x), baseline - height, int(x), baseline)
            tick += self.TICK_STEP

        painter.setPen(QPen(QColor("#FFFFFF"), 4))
        painter.drawLine(int(center_x), 24, int(center_x), 45)
        painter.setPen(QColor("#FFFFFF"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        display = self.normalized_angle(self._angle)
        label = f"{display:.1f}°" if not display.is_integer() else f"{int(display)}°"
        painter.drawText(self.rect().adjusted(0, 3, 0, 0), Qt.AlignHCenter, label)
