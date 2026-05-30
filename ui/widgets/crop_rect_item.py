from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPen,
)

from PySide6.QtWidgets import (
    QGraphicsRectItem,
)


class CropRectItem(QGraphicsRectItem):

    def __init__(
        self,
        rect,
    ):
        super().__init__(rect)

        self.setPen(
            QPen(
                QColor(
                    0,
                    120,
                    255,
                ),
                3,
            )
        )

        self.setBrush(
            QBrush(
                QColor(
                    0,
                    120,
                    255,
                    40,
                )
            )
        )

        self.setFlags(
            QGraphicsRectItem.ItemIsMovable
            |
            QGraphicsRectItem.ItemIsSelectable
        )

        self.setZValue(999)

    def get_crop_rect(self):

        return self.sceneBoundingRect()