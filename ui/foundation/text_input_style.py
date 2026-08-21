"""Pixel-crisp rendering for the standard text-input factories."""

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QProxyStyle,
    QStyle,
    QStyleOptionFrame,
)


_BORDER_COLORS = {
    "normal": QColor("#DADADF"),
    "hover": QColor("#C8C8CF"),
    "focus": QColor("#0EA5AC"),
}
_LOCKED_BORDER_COLOR = QColor("#D4D4D8")
_LOCKED_SURFACE_COLOR = QColor("#F4F4F5")


class PixelCrispTextInputStyle(QProxyStyle):
    """Draw factory text-input frames with a one-physical-pixel outline."""

    def drawPrimitive(self, element, option, painter, widget=None):
        if not self._is_factory_input(widget):
            return super().drawPrimitive(element, option, painter, widget)

        if isinstance(widget, QLineEdit):
            if element == QStyle.PE_PanelLineEdit:
                self._draw_input_surface(option, painter, widget)
                return
            if element == QStyle.PE_FrameLineEdit:
                return
        elif isinstance(widget, QPlainTextEdit) and element == QStyle.PE_Frame:
            self._draw_input_surface(option, painter, widget)
            return

        return super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _is_factory_input(widget):
        return (
            isinstance(widget, (QLineEdit, QPlainTextEdit))
            and widget.property("chatTextBox") is True
        )

    @staticmethod
    def _draw_input_surface(option, painter, widget=None):
        device = painter.device()
        device_pixel_ratio = (
            device.devicePixelRatioF()
            if device is not None and hasattr(device, "devicePixelRatioF")
            else 1.0
        )
        border_inset = 1.0 / max(device_pixel_ratio, 1.0)
        rect = QRectF(option.rect)
        # A 42px logical control is 52.5 physical pixels at 125% scaling.
        # Snap its drawn bounds to the real paint-device grid so the final
        # row is never a half-covered, lighter border pixel.
        rect.setWidth(
            math.ceil(rect.width() * device_pixel_ratio) / device_pixel_ratio
        )
        rect.setHeight(
            math.ceil(rect.height() * device_pixel_ratio) / device_pixel_ratio
        )
        outer_radius = min(12.0, rect.width() / 2.0, rect.height() / 2.0)
        inner_rect = rect.adjusted(
            border_inset,
            border_inset,
            -border_inset,
            -border_inset,
        )
        inner_radius = max(0.0, outer_radius - border_inset)

        is_locked = bool(
            widget is not None and widget.property("editLocked") is True
        )
        if is_locked:
            border_color = _LOCKED_BORDER_COLOR
        elif option.state & QStyle.State_HasFocus:
            border_color = _BORDER_COLORS["focus"]
        elif option.state & QStyle.State_MouseOver:
            border_color = _BORDER_COLORS["hover"]
        else:
            border_color = _BORDER_COLORS["normal"]

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(border_color)
        painter.drawRoundedRect(rect, outer_radius, outer_radius)
        painter.setBrush(
            _LOCKED_SURFACE_COLOR if is_locked else QColor("#FFFFFF")
        )
        painter.drawRoundedRect(inner_rect, inner_radius, inner_radius)
        painter.restore()


def paint_text_input_surface(widget):
    """Paint a complete factory-input surface before Qt draws its contents."""
    option = QStyleOptionFrame()
    option.initFrom(widget)
    option.rect = widget.rect()
    if widget.hasFocus():
        option.state |= QStyle.State_HasFocus
    painter = QPainter(widget)
    PixelCrispTextInputStyle._draw_input_surface(option, painter, widget)
    painter.end()


def install_pixel_crisp_text_input_style(app=None):
    """Install the factory style once, before the application QSS is loaded."""

    app = app or QApplication.instance()
    if app is None:
        return None
    if isinstance(app.style(), PixelCrispTextInputStyle):
        return app.style()

    style = PixelCrispTextInputStyle(app.style())
    app.setStyle(style)
    return style
