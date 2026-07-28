"""Small, non-interactive splash shown while Mission Legal starts."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QBitmap, QCloseEvent, QCursor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget

from utils.runtime_paths import resource_path


class StartupSplash(QWidget):
    """Brand-consistent startup surface with no user actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._allow_close = False
        self._cursor_overridden = False
        self._progress_animation = None
        self.setObjectName("StartupSplash")
        self.setFixedSize(360, 250)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            """
            QFrame#StartupSplashSurface {
                background: #FFFFFF;
                border: 1px solid #D9E4E7;
                border-radius: 18px;
            }
            QLabel#StartupSplashTitle {
                color: #183238;
                font-size: 20px;
                font-weight: 600;
            }
            QLabel#StartupSplashStatus {
                color: #60777D;
                font-size: 12px;
            }
            QProgressBar#StartupSplashProgress {
                background: #E5EEF0;
                border: none;
                border-radius: 2px;
            }
            QProgressBar#StartupSplashProgress::chunk {
                background: #27A7A4;
                border-radius: 2px;
            }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        surface = QFrame(self)
        surface.setObjectName("StartupSplashSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        logo = QLabel(surface)
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(QPixmap(str(resource_path("assets", "icons", "server_manager", "server_manager_logo.png"))).scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(logo)
        title = QLabel("Mission Legal", surface)
        title.setObjectName("StartupSplashTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        status = QLabel("Starting Mission Legal…", surface)
        status.setObjectName("StartupSplashStatus")
        status.setAlignment(Qt.AlignCenter)
        layout.addWidget(status)
        self.progress = QProgressBar(surface)
        self.progress.setObjectName("StartupSplashProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)
        outer.addWidget(surface)
        self._apply_rounded_mask()

    def advance_to(self, value: int, *, duration_ms: int = 550):
        """Smoothly advance to a completed startup checkpoint."""
        target = max(0, min(100, int(value)))
        if target <= self.progress.value():
            return
        animation = QPropertyAnimation(self.progress, b"value", self)
        animation.setStartValue(self.progress.value())
        animation.setEndValue(target)
        animation.setDuration(duration_ms)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._progress_animation = animation
        animation.finished.connect(animation.deleteLater)
        animation.start()

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
        self._allow_close = True
        if self._cursor_overridden:
            QApplication.restoreOverrideCursor()
            self._cursor_overridden = False
        self.close()
        self.deleteLater()

    def closeEvent(self, event: QCloseEvent):
        event.accept() if self._allow_close else event.ignore()


__all__ = ["StartupSplash"]
