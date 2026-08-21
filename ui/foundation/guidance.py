"""Small, reusable help affordances for task-specific guidance."""

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QToolButton, QVBoxLayout

from ui.foundation.icons import lucide_icon


class _GuidancePopup(QFrame):
    """A stable, single-stage tooltip with restrained opacity transitions."""

    def __init__(self, title, text):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("GuidancePopup")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(2)
        if title:
            title_label = QLabel(title, self)
            title_label.setObjectName("GuidancePopupTitle")
            title_label.setWordWrap(True)
            title_label.setFixedWidth(185)
            layout.addWidget(title_label)

        body_label = QLabel(text, self)
        body_label.setObjectName("GuidancePopupBody")
        body_label.setWordWrap(True)
        body_label.setFixedWidth(185)
        layout.addWidget(body_label)

        self._animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._animation.finished.connect(self._animation_finished)
        self._hiding = False
        self.adjustSize()

    def paintEvent(self, event):
        """Paint a truly rounded app-colored surface on Windows."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        painter.fillPath(path, QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#9FDDE1"), 1))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)

    def show_at(self, anchor):
        self._hiding = False
        self._animation.stop()
        if not self.isVisible():
            self.adjustSize()
            position = anchor.mapToGlobal(QPoint(anchor.width() + 6, 2))
            screen = anchor.screen() or QApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                position = QPoint(
                    max(area.left(), min(position.x(), area.right() - self.width())),
                    max(area.top(), min(position.y(), area.bottom() - self.height())),
                )
            self.move(position)
            self.setWindowOpacity(0.0)
            self.show()

        self._animation.setDuration(130)
        self._animation.setStartValue(self.windowOpacity())
        self._animation.setEndValue(1.0)
        self._animation.start()

    def fade_out(self):
        if not self.isVisible() or self._hiding:
            return
        self._hiding = True
        self._animation.stop()
        self._animation.setDuration(170)
        self._animation.setStartValue(self.windowOpacity())
        self._animation.setEndValue(0.0)
        self._animation.start()

    def _animation_finished(self):
        if self._hiding:
            self.hide()
            self._hiding = False


class GuidanceButton(QToolButton):
    """Question-mark button that reveals concise guidance on hover or focus."""

    def __init__(self, text, *, title="", parent=None):
        super().__init__(parent)
        self.guidance_text = str(text or "")
        self.guidance_title = str(title or "")
        self._popup = _GuidancePopup(self.guidance_title, self.guidance_text)
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(300)
        self._show_timer.timeout.connect(self.show_guidance)

        self.setObjectName("GuidanceButton")
        icon = lucide_icon("circle-question-mark", size=16, color="#0F7F85")
        if icon is not None and not icon.isNull():
            self.setIcon(icon)
        else:
            self.setText("?")
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(
            f"Help: {self.guidance_title or self.guidance_text}"
        )

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def enterEvent(self, event):
        self._show_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._show_timer.stop()
        self._popup.fade_out()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._show_timer.start(0)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._show_timer.stop()
        self._popup.fade_out()
        super().focusOutEvent(event)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.MouseButtonPress, QEvent.WindowDeactivate):
            if watched is not self:
                self._show_timer.stop()
                self._popup.fade_out()
        return super().eventFilter(watched, event)

    def show_guidance(self):
        if self.guidance_text and (self.underMouse() or self.hasFocus()):
            self._popup.show_at(self)

    def hideEvent(self, event):
        self._show_timer.stop()
        self._popup.fade_out()
        super().hideEvent(event)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._popup.close()
        super().closeEvent(event)


def create_guidance_button(text, *, title="", parent=None):
    """Create a compact, smoothly animated guidance control."""
    return GuidanceButton(text, title=title, parent=parent)
