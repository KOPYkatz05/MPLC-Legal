"""Small, non-interactive splash shown while Mission Legal starts."""

from __future__ import annotations

import math

from PySide6.QtCore import (
    QEasingCurve,
    QEventLoop,
    Property,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QBitmap,
    QCloseEvent,
    QColor,
    QCursor,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from utils.runtime_paths import resource_path


class LiquidProgressBar(QWidget):
    """Rounded progress track with a gently moving liquid leading edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 100
        self._value = 0.0
        self._wave_offset = 0.0
        self.setFixedHeight(14)

        self._wave_timer = QTimer(self)
        self._wave_timer.setInterval(33)
        self._wave_timer.timeout.connect(self._advance_wave)

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def setRange(self, minimum: int, maximum: int):
        if maximum <= minimum:
            raise ValueError("maximum must be greater than minimum")
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self.setValue(self._value)

    def value(self) -> int:
        return round(self._value)

    def setValue(self, value: float):
        bounded = max(self._minimum, min(self._maximum, float(value)))
        if math.isclose(bounded, self._value):
            return
        self._value = bounded
        self.update()

    def _get_animated_value(self) -> float:
        return self._value

    def _set_animated_value(self, value: float):
        self.setValue(value)

    animatedValue = Property(float, _get_animated_value, _set_animated_value)

    def _advance_wave(self):
        self._wave_offset = (self._wave_offset + 0.18) % (2 * math.pi)
        self.update()

    def showEvent(self, event):
        self._wave_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._wave_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = track.height() / 2
        painter.setPen(QColor("#D8E8EA"))
        painter.setBrush(QColor("#E5EEF0"))
        painter.drawRoundedRect(track, radius, radius)

        span = self._maximum - self._minimum
        fraction = (self._value - self._minimum) / span if span else 0.0
        fraction = max(0.0, min(1.0, fraction))
        if fraction <= 0.0:
            return

        clip = QPainterPath()
        clip.addRoundedRect(track, radius, radius)
        painter.save()
        painter.setClipPath(clip)

        if fraction >= 0.995:
            painter.fillPath(clip, QColor("#27A7A4"))
            painter.restore()
            return

        leading_edge = track.left() + (fraction * track.width())
        amplitude = min(2.4, track.height() * 0.2) * math.sin(math.pi * fraction)

        back_wave = self._wave_path(
            track,
            leading_edge,
            amplitude,
            self._wave_offset + 1.8,
        )
        painter.fillPath(back_wave, QColor("#55BFBC"))
        front_wave = self._wave_path(
            track,
            leading_edge,
            amplitude,
            self._wave_offset,
        )
        painter.fillPath(front_wave, QColor("#27A7A4"))
        painter.restore()

    @staticmethod
    def _wave_path(
        track: QRectF,
        leading_edge: float,
        amplitude: float,
        phase: float,
    ) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(track.left(), track.top())
        path.lineTo(leading_edge, track.top())
        sample_count = max(12, round(track.height() * 1.5))
        for index in range(sample_count + 1):
            ratio = index / sample_count
            y = track.top() + (track.height() * ratio)
            x = leading_edge + amplitude * math.sin((ratio * math.tau * 1.2) + phase)
            path.lineTo(x, y)
        path.lineTo(track.left(), track.bottom())
        path.closeSubpath()
        return path


class StartupSplash(QWidget):
    """Brand-consistent startup surface with no user actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._allow_close = False
        self._dismissed = False
        self._cursor_overridden = False
        self._progress_animation = None
        self.setObjectName("StartupSplash")
        self.setFixedSize(640, 300)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            """
            QFrame#StartupSplashSurface {
                background: #FFFFFF;
                border: 1px solid #D9E4E7;
                border-radius: 18px;
            }
            QLabel#StartupSplashStatus {
                color: #60777D;
                font-size: 12px;
            }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        surface = QFrame(self)
        surface.setObjectName("StartupSplashSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)

        logo = QLabel(surface)
        logo.setAlignment(Qt.AlignCenter)
        splash_pixmap = QPixmap(
            str(
                resource_path(
                    "assets", "icons", "mission_legal", "mission_legal_splash.png"
                )
            )
        )
        screen = QApplication.primaryScreen()
        device_pixel_ratio = screen.devicePixelRatio() if screen is not None else 1.0
        splash_pixmap = splash_pixmap.scaled(
            round(584 * device_pixel_ratio),
            round(145 * device_pixel_ratio),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        splash_pixmap.setDevicePixelRatio(device_pixel_ratio)
        logo.setPixmap(splash_pixmap)
        layout.addWidget(logo)
        status = QLabel("Starting Mission Legal…", surface)
        status.setObjectName("StartupSplashStatus")
        status.setAlignment(Qt.AlignCenter)
        layout.addWidget(status)
        self.progress = LiquidProgressBar(surface)
        self.progress.setObjectName("StartupSplashProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        outer.addWidget(surface)
        self._apply_rounded_mask()

    def advance_to(
        self,
        value: int,
        *,
        duration_ms: int | None = None,
        wait: bool = False,
    ):
        """Smoothly advance to a completed startup checkpoint."""
        if self._dismissed:
            return
        target = max(0, min(100, int(value)))
        current = self.progress.value()
        if target <= current:
            return
        if duration_ms is None:
            duration_ms = max(320, min(720, 240 + ((target - current) * 8)))
        if self._progress_animation is not None:
            self._progress_animation.stop()
        animation = QPropertyAnimation(self.progress, b"animatedValue", self)
        animation.setStartValue(self.progress._get_animated_value())
        animation.setEndValue(target)
        animation.setDuration(duration_ms)
        animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._progress_animation = animation
        animation.finished.connect(lambda: self._finish_progress_animation(animation))
        animation.start()
        if wait:
            loop = QEventLoop()
            safety_timer = QTimer()
            safety_timer.setSingleShot(True)
            animation.finished.connect(loop.quit)
            safety_timer.timeout.connect(loop.quit)
            safety_timer.start(duration_ms + 100)
            loop.exec()
            safety_timer.stop()

    def _finish_progress_animation(self, animation: QPropertyAnimation):
        if self._progress_animation is animation:
            self._progress_animation = None

    def _apply_rounded_mask(self):
        mask = QBitmap(self.size())
        mask.fill(Qt.color0)
        painter = QPainter(mask)
        painter.setBrush(Qt.color1)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(mask.rect(), 18, 18)
        painter.end()
        self.setMask(mask)

    def show_centered(self):
        screen = self.screen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
        QApplication.setOverrideCursor(QCursor(Qt.ArrowCursor))
        self._cursor_overridden = True
        self.show()
        self.raise_()
        self.activateWindow()

    def dismiss(self):
        if self._dismissed:
            return
        self._dismissed = True
        self._allow_close = True
        self.progress._wave_timer.stop()
        if self._progress_animation is not None:
            self._progress_animation.stop()
            self._progress_animation = None
        if self._cursor_overridden:
            QApplication.restoreOverrideCursor()
            self._cursor_overridden = False
        self.close()

    def closeEvent(self, event: QCloseEvent):
        event.accept() if self._allow_close else event.ignore()


__all__ = ["LiquidProgressBar", "StartupSplash"]
