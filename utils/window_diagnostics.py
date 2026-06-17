from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from utils.logger import logger


class TopLevelWindowDiagnostics(QObject):
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self._installed = False

    def install(self):
        if self._installed:
            return
        self._installed = True
        self.app.installEventFilter(self)
        self.log_snapshot("diagnostics-installed")

    def eventFilter(self, watched, event):
        if isinstance(watched, QWidget) and watched.isWindow():
            if event.type() in {
                QEvent.Type.Show,
                QEvent.Type.Hide,
                QEvent.Type.Close,
                QEvent.Type.WindowActivate,
            }:
                self.log_widget(
                    self._event_name(event.type()),
                    watched,
                )
        return super().eventFilter(watched, event)

    def log_snapshot(self, context):
        widgets = QApplication.topLevelWidgets()
        logger.info(
            "WINDOW_DIAGNOSTIC_SNAPSHOT context=%s count=%s windows=%s",
            context,
            len(widgets),
            [self._widget_payload(widget) for widget in widgets],
        )

    def log_widget(self, event_name, widget):
        logger.info(
            "WINDOW_DIAGNOSTIC_EVENT event=%s window=%s",
            event_name,
            self._widget_payload(widget),
        )

    @staticmethod
    def _event_name(event_type):
        try:
            return event_type.name
        except AttributeError:
            return str(int(event_type))

    @staticmethod
    def _widget_payload(widget):
        geometry = widget.geometry()
        parent = widget.parentWidget()
        try:
            flags = int(widget.windowFlags())
        except TypeError:
            flags = int(widget.windowFlags().value)
        return {
            "class": type(widget).__name__,
            "title": widget.windowTitle(),
            "object": widget.objectName(),
            "visible": widget.isVisible(),
            "active": widget.isActiveWindow(),
            "modal": widget.isModal(),
            "flags": flags,
            "geometry": (
                geometry.x(),
                geometry.y(),
                geometry.width(),
                geometry.height(),
            ),
            "parent_class": type(parent).__name__ if parent else None,
            "parent_title": parent.windowTitle() if parent else None,
        }


def install_window_diagnostics(app=None):
    app = app or QApplication.instance()
    if app is None:
        return None

    existing = getattr(app, "_mission_window_diagnostics", None)
    if existing is not None:
        return existing

    diagnostics = TopLevelWindowDiagnostics(app)
    app._mission_window_diagnostics = diagnostics
    diagnostics.install()
    return diagnostics


def log_top_level_windows(context, delay_ms=0):
    app = QApplication.instance()
    diagnostics = getattr(app, "_mission_window_diagnostics", None)
    if diagnostics is None:
        diagnostics = install_window_diagnostics(app)
    if diagnostics is None:
        return

    if delay_ms:
        QTimer.singleShot(
            delay_ms,
            lambda: diagnostics.log_snapshot(context),
        )
    else:
        diagnostics.log_snapshot(context)
