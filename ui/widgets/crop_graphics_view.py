from PySide6.QtCore import (
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
    ):
        super().__init__(parent)

        self.crop_item = None

        self.drag_start = None

    def mousePressEvent(
        self,
        event,
    ):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(
                event
            )

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
        if not self.drag_start:
            return super().mouseMoveEvent(
                event
            )

        current = self.mapToScene(
            event.pos()
        )

        rect = QRectF(
            self.drag_start,
            current,
        ).normalized()

        if self.crop_item:
            self.scene().removeItem(
                self.crop_item
            )

        self.crop_item = CropRectItem(
            rect
        )

        self.scene().addItem(
            self.crop_item
        )

    def mouseReleaseEvent(
        self,
        event,
    ):
        if not self.drag_start:
            return super().mouseReleaseEvent(
                event
            )

        current = self.mapToScene(
            event.pos()
        )

        rect = QRectF(
            self.drag_start,
            current,
        ).normalized()

        self.drag_start = None

        self.crop_changed.emit(
            rect
        )

    def get_crop_rect(
        self,
    ):
        if self.crop_item:
            return self.crop_item.rect()

        return None