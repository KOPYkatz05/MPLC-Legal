from PySide6.QtCore import (
    QPoint,
    Qt,
    QRectF,
    Signal,
)

from PySide6.QtWidgets import (
    QGraphicsView,
)

from ui.widgets.crop_rect_item import (
    CropRectItem,
)


class CropGraphicsView(
    QGraphicsView
):

    crop_changed = Signal(QRectF)

    def __init__(
        self,
        parent=None,
        aspect_ratio=None,
        enable_zoom=False,
    ):
        super().__init__(parent)

        self.crop_item = None

        self.drag_start = None

        self.aspect_ratio = aspect_ratio
        self.enable_zoom = bool(enable_zoom)
        self._fit_scale = 1.0
        self._pan_start = None
        if self.enable_zoom:
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def clear_crop(self):
        if self.crop_item is not None:
            self.scene().removeItem(self.crop_item)
            self.crop_item = None

    def fit_scene(self):
        scene = self.scene()
        if scene is None or scene.sceneRect().isEmpty():
            return
        self.resetTransform()
        self.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
        self._fit_scale = max(self.transform().m11(), 0.000001)

    def zoom_by(self, factor):
        if not self.enable_zoom or factor <= 0:
            return
        relative_scale = self.transform().m11() / max(self._fit_scale, 0.000001)
        target = max(0.02, min(50.0, relative_scale * factor))
        self.scale(target / relative_scale, target / relative_scale)

    def wheelEvent(self, event):
        if not self.enable_zoom:
            return super().wheelEvent(event)
        delta = event.angleDelta().y()
        if delta:
            self.zoom_by(1.0015 ** delta)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.enable_zoom and event.button() == Qt.MiddleButton:
            self.fit_scene()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _selection_rect(self, current):
        rect = QRectF(self.drag_start, current).normalized()
        if not self.aspect_ratio or rect.isEmpty():
            return rect

        width = rect.width()
        height = width / float(self.aspect_ratio)
        if height > rect.height():
            height = rect.height()
            width = height * float(self.aspect_ratio)
        horizontal_sign = 1 if current.x() >= self.drag_start.x() else -1
        vertical_sign = 1 if current.y() >= self.drag_start.y() else -1
        endpoint = type(current)(
            self.drag_start.x() + width * horizontal_sign,
            self.drag_start.y() + height * vertical_sign,
        )
        return QRectF(self.drag_start, endpoint).normalized()

    def set_crop_rect(self, rect):
        if self.crop_item:
            self.scene().removeItem(self.crop_item)
        self.crop_item = CropRectItem(
            QRectF(rect),
            aspect_ratio=self.aspect_ratio,
        )
        self.scene().addItem(self.crop_item)

    def mousePressEvent(
        self,
        event,
    ):
        if self.enable_zoom and event.button() == Qt.MiddleButton:
            self._pan_start = QPoint(event.pos())
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(
                event
            )

        clicked_item = self.itemAt(event.pos())
        if self.crop_item is not None and clicked_item is self.crop_item:
            self.drag_start = None
            return super().mousePressEvent(event)

        self.drag_start = self.mapToScene(
            event.pos()
        )

        if self.crop_item:
            self.scene().removeItem(
                self.crop_item
            )

            self.crop_item = None

    def mouseMoveEvent(
        self,
        event,
    ):
        if self._pan_start is not None:
            current = QPoint(event.pos())
            delta = current - self._pan_start
            self._pan_start = current
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        if not self.drag_start:
            return super().mouseMoveEvent(
                event
            )

        current = self.mapToScene(
            event.pos()
        )

        rect = self._selection_rect(current)

        if self.crop_item:
            self.scene().removeItem(
                self.crop_item
            )

        self.crop_item = CropRectItem(
            rect,
            aspect_ratio=self.aspect_ratio,
        )

        self.scene().addItem(
            self.crop_item
        )

    def mouseReleaseEvent(
        self,
        event,
    ):
        if event.button() == Qt.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            self.unsetCursor()
            event.accept()
            return
        if not self.drag_start:
            return super().mouseReleaseEvent(
                event
            )

        current = self.mapToScene(
            event.pos()
        )

        rect = self._selection_rect(current)

        self.drag_start = None

        self.crop_changed.emit(
            rect
        )

    def get_crop_rect(
        self,
    ):
        if self.crop_item:
            return self.crop_item.get_crop_rect()

        return None
