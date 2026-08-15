"""Reusable preview interaction surface for the upload dialog."""

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import QGraphicsView

from ui.foundation import SmoothScrollDelegate, tune_fluent_scrollable


class UploadPreviewGraphicsView(QGraphicsView):
    zoom_requested = Signal(float, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview_interactions_enabled = False
        self._is_middle_panning = False
        self._last_pan_pos = QPoint()
        self.scrollDelegate = None
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        if SmoothScrollDelegate is not None:
            self.scrollDelegate = SmoothScrollDelegate(self)
            tune_fluent_scrollable(self)
        self.viewport().installEventFilter(self)

    def set_preview_interactions_enabled(self, enabled):
        self._preview_interactions_enabled = enabled
        if not enabled:
            self._stop_middle_pan()

    def eventFilter(self, watched, event):
        if watched == self.viewport() and event.type() == QEvent.Type.Wheel:
            if self._handle_wheel_zoom(event):
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if not self._handle_wheel_zoom(event):
            super().wheelEvent(event)

    def _handle_wheel_zoom(self, event):
        if not self._preview_interactions_enabled:
            return False
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            return False
        factor = 1.25 if delta > 0 else 0.8
        self.zoom_requested.emit(factor, event.position().toPoint())
        event.accept()
        return True

    def mousePressEvent(self, event):
        if self._preview_interactions_enabled and event.button() == Qt.MiddleButton:
            self._is_middle_panning = True
            self._last_pan_pos = event.position().toPoint()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_middle_panning:
            current_pos = event.position().toPoint()
            delta = current_pos - self._last_pan_pos
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            self._last_pan_pos = current_pos
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_middle_panning and event.button() == Qt.MiddleButton:
            self._stop_middle_pan()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _stop_middle_pan(self):
        if not self._is_middle_panning:
            return
        self._is_middle_panning = False
        self.viewport().unsetCursor()
