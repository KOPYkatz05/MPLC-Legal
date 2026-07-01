from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import QScrollArea

from ui.foundation import SmoothScrollDelegate, tune_fluent_scrollable


class EditableCanvasState:
    def __init__(
        self,
        zoom=1.0,
        min_zoom=0.4,
        max_zoom=2.5,
        zoom_step=0.1,
        base_grid_size=96,
        min_grid_size=24,
        max_grid_size=240,
    ):
        self.zoom = float(zoom)
        self.min_zoom = float(min_zoom)
        self.max_zoom = float(max_zoom)
        self.zoom_step = float(zoom_step)
        self.base_grid_size = int(base_grid_size)
        self.min_grid_size = int(min_grid_size)
        self.max_grid_size = int(max_grid_size)
        self.grid_visible = True

    def set_zoom(self, value):
        self.zoom = max(self.min_zoom, min(self.max_zoom, float(value)))
        return self.zoom

    def zoom_in(self):
        return self.set_zoom(self.zoom + self.zoom_step)

    def zoom_out(self):
        return self.set_zoom(self.zoom - self.zoom_step)

    def reset_zoom(self):
        return self.set_zoom(1.0)

    def fit_width_zoom(self, viewport_width, content_width, padding=36):
        usable_width = max(1, int(viewport_width) - int(padding))
        content_width = max(1, int(content_width))
        return self.set_zoom(usable_width / content_width)

    def set_grid_visible(self, visible):
        self.grid_visible = bool(visible)
        return self.grid_visible

    def set_grid_size(self, value):
        try:
            grid_size = int(value)
        except (TypeError, ValueError):
            grid_size = self.base_grid_size
        self.base_grid_size = max(
            self.min_grid_size,
            min(self.max_grid_size, grid_size),
        )
        return self.base_grid_size

    def scaled_grid_size(self):
        return int(self.base_grid_size * self.zoom)


class EditableCanvasScrollArea(QScrollArea):
    zoomRequested = Signal(float, QPoint)

    def __init__(self, parent=None, wheel_requires_control=True):
        super().__init__(parent)
        self._wheel_requires_control = wheel_requires_control
        self._canvas_interactions_enabled = True
        self._is_middle_panning = False
        self._last_pan_pos = QPoint()
        self.scrollDelegate = None
        self.setWidgetResizable(True)
        if SmoothScrollDelegate is not None:
            self.scrollDelegate = SmoothScrollDelegate(self)
            tune_fluent_scrollable(self)
        self.viewport().installEventFilter(self)

    def set_canvas_interactions_enabled(self, enabled):
        self._canvas_interactions_enabled = bool(enabled)
        if not enabled:
            self._stop_middle_pan()

    def eventFilter(self, watched, event):
        if watched == self.viewport():
            if self._handle_viewport_event(event):
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if not self._handle_wheel_zoom(event):
            super().wheelEvent(event)

    def _handle_viewport_event(self, event):
        event_type = event.type()
        if event_type == QEvent.Type.Wheel:
            return self._handle_wheel_zoom(event)
        if (
            event_type == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MiddleButton
        ):
            return self._start_middle_pan(event)
        if event_type == QEvent.Type.MouseMove and self._is_middle_panning:
            return self._continue_middle_pan(event)
        if (
            event_type == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MiddleButton
            and self._is_middle_panning
        ):
            self._stop_middle_pan()
            event.accept()
            return True
        return False

    def _handle_wheel_zoom(self, event):
        if not self._canvas_interactions_enabled:
            return False
        if (
            self._wheel_requires_control
            and not event.modifiers() & Qt.ControlModifier
        ):
            return False
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            return False
        factor = 1.25 if delta > 0 else 0.8
        self.zoomRequested.emit(factor, event.position().toPoint())
        event.accept()
        return True

    def _start_middle_pan(self, event):
        if not self._canvas_interactions_enabled:
            return False
        self._is_middle_panning = True
        self._last_pan_pos = event.position().toPoint()
        self.viewport().setCursor(Qt.ClosedHandCursor)
        event.accept()
        return True

    def _continue_middle_pan(self, event):
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
        return True

    def _stop_middle_pan(self):
        if not self._is_middle_panning:
            return
        self._is_middle_panning = False
        self.viewport().unsetCursor()


def resolve_overlapping_free_rects(
    rects,
    moving_key,
    canvas_width,
    padding=24,
    spacing=12,
):
    if moving_key not in rects:
        return {key: QRect(rect) for key, rect in rects.items()}

    resolved = {key: QRect(rect) for key, rect in rects.items()}
    moving_rect = QRect(resolved[moving_key])
    placed = [(moving_key, moving_rect)]

    ordered = sorted(
        (
            (key, QRect(rect))
            for key, rect in resolved.items()
            if key != moving_key
        ),
        key=lambda item: (item[1].y(), item[1].x()),
    )
    for key, rect in ordered:
        candidate = QRect(rect)
        for _, placed_rect in placed:
            if not candidate.intersects(placed_rect):
                continue
            candidate.moveTop(placed_rect.bottom() + spacing)
            max_x = max(padding, canvas_width - candidate.width() - padding)
            candidate.moveLeft(max(padding, min(candidate.x(), max_x)))
        resolved[key] = candidate
        placed.append((key, candidate))
    return resolved


def align_rect_to_peer(rect, peer_rects, edge, bounds=None):
    if edge not in {"left", "right", "top", "bottom", "center", "middle"}:
        return QRect(rect), False
    peers = [QRect(peer) for peer in peer_rects]
    if not peers:
        return QRect(rect), False

    aligned = QRect(rect)
    if edge in {"left", "right", "center"}:
        offset = {
            "left": 0,
            "right": aligned.width(),
            "center": aligned.width() / 2,
        }[edge]
        current_value = aligned.x() + offset
        peer_values = [
            {
                "left": peer.x(),
                "right": peer.x() + peer.width(),
                "center": peer.x() + (peer.width() / 2),
            }[edge]
            for peer in peers
        ]
        target_value = min(peer_values, key=lambda value: abs(value - current_value))
        aligned.moveLeft(round(target_value - offset))
    else:
        offset = {
            "top": 0,
            "bottom": aligned.height(),
            "middle": aligned.height() / 2,
        }[edge]
        current_value = aligned.y() + offset
        peer_values = [
            {
                "top": peer.y(),
                "bottom": peer.y() + peer.height(),
                "middle": peer.y() + (peer.height() / 2),
            }[edge]
            for peer in peers
        ]
        target_value = min(peer_values, key=lambda value: abs(value - current_value))
        aligned.moveTop(round(target_value - offset))

    if bounds is not None:
        bounded = QRect(bounds)
        aligned.moveLeft(
            max(bounded.left(), min(aligned.left(), bounded.right() - aligned.width() + 1))
        )
        aligned.moveTop(max(bounded.top(), min(aligned.top(), bounded.bottom() - aligned.height() + 1)))
    return aligned, aligned != rect
