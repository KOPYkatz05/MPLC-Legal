from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem


class CropRectItem(QGraphicsRectItem):
    HANDLE_SIZE = 12.0

    def __init__(self, rect, aspect_ratio=None):
        super().__init__(rect)
        self.aspect_ratio = aspect_ratio
        self._resize_handle = None
        self._resize_anchor = None

        self.setPen(QPen(QColor(0, 120, 255), 3))
        self.setBrush(QBrush(QColor(0, 120, 255, 40)))
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(999)

    def _handle_rects(self):
        rect = self.rect()
        half = self.HANDLE_SIZE / 2
        return {
            "top_left": QRectF(
                rect.left() - half,
                rect.top() - half,
                self.HANDLE_SIZE,
                self.HANDLE_SIZE,
            ),
            "top_right": QRectF(
                rect.right() - half,
                rect.top() - half,
                self.HANDLE_SIZE,
                self.HANDLE_SIZE,
            ),
            "bottom_left": QRectF(
                rect.left() - half,
                rect.bottom() - half,
                self.HANDLE_SIZE,
                self.HANDLE_SIZE,
            ),
            "bottom_right": QRectF(
                rect.right() - half,
                rect.bottom() - half,
                self.HANDLE_SIZE,
                self.HANDLE_SIZE,
            ),
        }

    def _handle_at(self, position):
        for name, rect in self._handle_rects().items():
            if rect.contains(position):
                return name
        return None

    def _opposite_corner(self, handle):
        rect = self.rect()
        return {
            "top_left": rect.bottomRight(),
            "top_right": rect.bottomLeft(),
            "bottom_left": rect.topRight(),
            "bottom_right": rect.topLeft(),
        }[handle]

    def boundingRect(self):
        margin = self.HANDLE_SIZE / 2 + self.pen().widthF()
        return self.rect().adjusted(-margin, -margin, margin, margin)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(QBrush(QColor(0, 120, 255)))
        for handle_rect in self._handle_rects().values():
            painter.drawRoundedRect(handle_rect, 2, 2)
        painter.restore()

    def hoverMoveEvent(self, event):
        handle = self._handle_at(event.pos())
        if handle in {"top_left", "bottom_right"}:
            self.setCursor(QCursor(Qt.SizeFDiagCursor))
        elif handle in {"top_right", "bottom_left"}:
            self.setCursor(QCursor(Qt.SizeBDiagCursor))
        else:
            self.setCursor(QCursor(Qt.SizeAllCursor))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        handle = self._handle_at(event.pos())
        if handle is not None:
            self._resize_handle = handle
            self._resize_anchor = self._opposite_corner(handle)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_handle is None:
            super().mouseMoveEvent(event)
            return

        current = event.pos()
        anchor = self._resize_anchor
        width = abs(current.x() - anchor.x())
        height = abs(current.y() - anchor.y())
        if self.aspect_ratio:
            if height <= 0 or width / height > self.aspect_ratio:
                height = width / float(self.aspect_ratio)
            else:
                width = height * float(self.aspect_ratio)
        if width < 24 or height < 24:
            event.accept()
            return

        x = anchor.x() - width if current.x() < anchor.x() else anchor.x()
        y = anchor.y() - height if current.y() < anchor.y() else anchor.y()
        self.prepareGeometryChange()
        self.setRect(QRectF(QPointF(x, y), QPointF(x + width, y + height)))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._resize_handle is not None:
            self._resize_handle = None
            self._resize_anchor = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            position = QPointF(value)
            bounds = self.scene().sceneRect()
            proposed = self.rect().translated(position)
            if proposed.left() < bounds.left():
                position.setX(position.x() + bounds.left() - proposed.left())
            if proposed.right() > bounds.right():
                position.setX(position.x() - proposed.right() + bounds.right())
            if proposed.top() < bounds.top():
                position.setY(position.y() + bounds.top() - proposed.top())
            if proposed.bottom() > bounds.bottom():
                position.setY(position.y() - proposed.bottom() + bounds.bottom())
            return position
        return super().itemChange(change, value)

    def get_crop_rect(self):
        mapped = self.mapRectToScene(self.rect())
        return mapped.boundingRect() if hasattr(mapped, "boundingRect") else mapped
