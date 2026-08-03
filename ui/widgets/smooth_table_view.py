"""Standard-Qt table view with high-frequency inertial wheel scrolling."""

from __future__ import annotations

from math import exp
from time import perf_counter

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QTableView


class _ScrollGlide(QObject):
    """Critically damped scrollbar motion with continuous wheel accumulation."""

    started = Signal()
    finished = Signal()

    def __init__(self, scrollbar, parent=None, *, settle_time_ms=180):
        super().__init__(parent)
        self._scrollbar = scrollbar
        self._settle_time = max(80, int(settle_time_ms)) / 1000.0
        self._position = float(scrollbar.value())
        self._target = self._position
        self._velocity = 0.0
        self._last_tick = perf_counter()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._advance)

    @property
    def target(self) -> float:
        return self._target

    @property
    def is_active(self) -> bool:
        return self._timer.isActive()

    def add_distance(self, distance: float):
        if not self.is_active:
            self._position = float(self._scrollbar.value())
            self._target = self._position
            self._velocity = 0.0

        self._target = self._clamp(self._target + float(distance))
        if abs(self._target - self._position) < 0.5:
            return

        if not self.is_active:
            self._last_tick = perf_counter()
            self._timer.start()
            self.started.emit()

    def stop(self):
        was_active = self.is_active
        self._timer.stop()
        self._position = float(self._scrollbar.value())
        self._target = self._position
        self._velocity = 0.0
        if was_active:
            self.finished.emit()

    def _advance(self):
        now = perf_counter()
        elapsed = max(0.001, min(0.032, now - self._last_tick))
        self._last_tick = now
        self._target = self._clamp(self._target)

        # Exact integration of a critically damped spring. Unlike restarting
        # an easing curve for every wheel event, this preserves velocity when
        # the target changes and therefore avoids visible acceleration seams.
        omega = 5.0 / self._settle_time
        displacement = self._position - self._target
        combined = self._velocity + omega * displacement
        decay = exp(-omega * elapsed)
        displacement = (displacement + combined * elapsed) * decay
        self._velocity = (
            self._velocity - omega * combined * elapsed
        ) * decay
        self._position = self._target + displacement
        self._position = self._clamp(self._position)
        self._scrollbar.setValue(round(self._position))

        if (
            abs(self._target - self._position) < 0.45
            and abs(self._velocity) < 4.0
        ):
            self._scrollbar.setValue(round(self._target))
            self._position = self._target
            self._velocity = 0.0
            self._timer.stop()
            self.finished.emit()

    def _clamp(self, value: float) -> float:
        return max(
            float(self._scrollbar.minimum()),
            min(float(self._scrollbar.maximum()), value),
        )


class SmoothTableView(QTableView):
    """Glide toward accumulated wheel targets without Fluent UI helpers."""

    scrollingStarted = Signal()
    scrollingFinished = Signal()

    def __init__(self, parent=None, *, scroll_duration=180):
        super().__init__(parent)
        self._vertical_glide = _ScrollGlide(
            self.verticalScrollBar(),
            self,
            settle_time_ms=scroll_duration,
        )
        self._horizontal_glide = _ScrollGlide(
            self.horizontalScrollBar(),
            self,
            settle_time_ms=scroll_duration,
        )
        self._vertical_glide.started.connect(self.scrollingStarted)
        self._horizontal_glide.started.connect(self.scrollingStarted)
        self._vertical_glide.finished.connect(self._glide_finished)
        self._horizontal_glide.finished.connect(self._glide_finished)

    @property
    def is_gliding(self) -> bool:
        return (
            self._vertical_glide.is_active
            or self._horizontal_glide.is_active
        )

    def wheelEvent(self, event):
        # Precision touchpads already provide pixel deltas and platform-native
        # momentum. Preserve that high-resolution path as-is.
        if not event.pixelDelta().isNull():
            self.stop_smooth_scroll()
            super().wheelEvent(event)
            return

        angle = event.angleDelta()
        horizontal = bool(event.modifiers() & Qt.ShiftModifier)
        if abs(angle.x()) > abs(angle.y()):
            horizontal = True

        delta = angle.x() if horizontal and angle.x() else angle.y()
        if not delta:
            super().wheelEvent(event)
            return

        scrollbar = (
            self.horizontalScrollBar()
            if horizontal
            else self.verticalScrollBar()
        )
        glide = self._horizontal_glide if horizontal else self._vertical_glide
        unit = (
            max(24, scrollbar.singleStep())
            if horizontal
            else max(40, self.verticalHeader().defaultSectionSize())
        )
        wheel_lines = max(1, QApplication.wheelScrollLines())
        distance = -(float(delta) / 120.0) * unit * wheel_lines
        glide.add_distance(distance)
        event.accept()

    def stop_smooth_scroll(self):
        """Stop pending movement and make the current position authoritative."""

        self._vertical_glide.stop()
        self._horizontal_glide.stop()

    def _glide_finished(self):
        if not self.is_gliding:
            self.scrollingFinished.emit()


__all__ = ["SmoothTableView"]
