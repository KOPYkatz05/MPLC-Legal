from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class AppDialogFooter(QFrame):
    """Standard Qt action strip used by AppDialog surfaces."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppDialogFooter")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addStretch()

    def add_action(self, button):
        self.layout().addWidget(button)


class DialogBackdrop(QWidget):
    """Blurred and dimmed snapshot overlay owned by one AppDialog."""

    def __init__(self, host, *, blur_radius=10, dim_alpha=72):
        super().__init__(host)
        self._host = host
        self._blur_radius = blur_radius
        self._disposed = False

        self.snapshot = QLabel(self)
        self.snapshot.setScaledContents(True)
        self._blur = QGraphicsBlurEffect(self.snapshot)
        self._blur.setBlurRadius(blur_radius)
        self.snapshot.setGraphicsEffect(self._blur)

        self.dim = QWidget(self)
        self.dim.setObjectName("AppDialogBackdropDim")
        self.dim.setStyleSheet(
            f"background-color: rgba(15, 23, 42, {dim_alpha});"
        )

        host.installEventFilter(self)
        self.refresh(capture=True)

    def refresh(self, *, capture=False):
        if self._host is None:
            return
        self.setGeometry(self._host.rect())
        self.snapshot.setGeometry(self.rect())
        self.dim.setGeometry(self.rect())
        if capture:
            self.snapshot.setPixmap(self._host.grab())

    def eventFilter(self, watched, event):
        if watched is self._host and event.type() == QEvent.Resize:
            self.refresh(capture=True)
        return super().eventFilter(watched, event)

    def deactivate(self):
        self.hide()

    def dispose(self, *_args):
        if self._disposed:
            return
        self._disposed = True
        if self._host is not None:
            try:
                self._host.removeEventFilter(self)
            except RuntimeError:
                # Qt may delete a parent before the Python destroyed callback
                # runs.  There is no remaining event filter to remove then.
                pass
            self._host = None
        self.hide()
        self.setParent(None)
        self.deleteLater()


class AppDialog(QDialog):
    """Reusable standard-Qt dialog with a responsive rounded surface."""

    def __init__(
        self,
        parent=None,
        *,
        title="",
        subtitle="",
        width=520,
        min_height=None,
        max_height=None,
        radius=20,
        blur_radius=10,
        dim_alpha=72,
        shadow=True,
    ):
        host = parent.window() if isinstance(parent, QWidget) else None
        super().__init__(host or parent)
        self._host = host
        self._preferred_width = width
        self._requested_min_height = min_height
        self._requested_max_height = max_height
        self._backdrop_options = {
            "blur_radius": blur_radius,
            "dim_alpha": dim_alpha,
        }
        self._backdrop = None
        if self._host is not None:
            self._host.installEventFilter(self)

        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        self.surface_container = QFrame(self)
        self.surface_container.setObjectName("AppDialogSurfaceContainer")
        container_layout = QVBoxLayout(self.surface_container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(0)

        self.surface = QFrame(self.surface_container)
        self.surface.setObjectName("AppDialogSurface")
        container_layout.addWidget(self.surface)
        root.addWidget(self.surface_container, alignment=Qt.AlignCenter)

        if shadow:
            self._shadow = QGraphicsDropShadowEffect(self.surface_container)
            self._shadow.setBlurRadius(18)
            self._shadow.setOffset(0, 5)
            self._shadow.setColor(QColor(15, 23, 42, 42))
            self._shadow.setEnabled(True)
            self.surface_container.setGraphicsEffect(self._shadow)
        else:
            self._shadow = None

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(0)

        self.header = self._build_header(title, subtitle)
        surface_layout.addWidget(self.header)

        self.body = QWidget(self.surface)
        self.body.setObjectName("AppDialogBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 12, 14, 14)
        self.body_layout.setSpacing(10)
        surface_layout.addWidget(self.body, stretch=1)

        self.footer = AppDialogFooter(self.surface)
        surface_layout.addWidget(self.footer)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(170)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._apply_responsive_size()

    @staticmethod
    def _build_header(title, subtitle):
        header = QFrame()
        header.setObjectName("AppDialogHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("AppDialogTitle")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("AppDialogSubtitle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
        return header

    def _available_geometry(self):
        if self._host is not None and self._host.screen() is not None:
            return self._host.screen().availableGeometry()
        screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _apply_responsive_size(self):
        geometry = self._available_geometry()
        if geometry is None:
            return
        maximum_width = max(280, geometry.width() - 64)
        surface_width = min(self._preferred_width, maximum_width)
        self.surface.setFixedWidth(surface_width)
        self.surface_container.setFixedWidth(surface_width + 16)

        maximum_height = max(180, geometry.height() - 64)
        requested_minimum = self._requested_min_height or 0
        self.surface.setMinimumHeight(min(requested_minimum, maximum_height))
        requested_maximum = self._requested_max_height or maximum_height
        self.surface.setMaximumHeight(min(requested_maximum, maximum_height))

    def _ensure_backdrop(self):
        if self._host is None or not self._host.isVisible():
            return
        if self._backdrop is None:
            self._backdrop = DialogBackdrop(
                self._host,
                **self._backdrop_options,
            )
            self.destroyed.connect(self._backdrop.dispose)
        else:
            self._backdrop.refresh(capture=True)
        self._backdrop.show()
        self._backdrop.raise_()

    def _remove_backdrop(self):
        if self._backdrop is not None:
            backdrop = self._backdrop
            self._backdrop = None
            backdrop.dispose()

    def _center_on_host(self):
        self.adjustSize()
        if self._host is None:
            return
        self.move(self._host.frameGeometry().center() - self.rect().center())

    def _start_fade(self):
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def showEvent(self, event):
        self._apply_responsive_size()
        self._ensure_backdrop()
        self._center_on_host()
        self._start_fade()
        super().showEvent(event)

    def hideEvent(self, event):
        self._fade.stop()
        self.setWindowOpacity(1.0)
        self._remove_backdrop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._remove_backdrop()
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if watched is self._host and event.type() == QEvent.Resize:
            self._apply_responsive_size()
            if self.isVisible():
                self._center_on_host()
        return super().eventFilter(watched, event)
