"""Painting for the model-backed missionaries table.

The delegate intentionally depends only on standard Qt widgets.  The model
provides semantic values (row colour, accent and pending state); this class is
the single place where those values become pixels.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from ui.models.missionary_table_model import (
    MISSIONARY_ID_ROLE,
    PENDING_ROLE,
    ROW_ACCENT_ROLE,
    ROW_COLOR_ROLE,
)


DEFAULT_MISSIONARY_ROW_COLOR_STYLES = {
    "teal": ("#E6FFFB", "#0EA5AC"),
    "blue": ("#EFF6FF", "#2563EB"),
    "purple": ("#F5F3FF", "#7C3AED"),
    "amber": ("#FFFBEB", "#D97706"),
    "green": ("#ECFDF5", "#059669"),
    "red": ("#FEF2F2", "#DC2626"),
    "gray": ("#F4F4F5", "#71717A"),
}

# The move animator sets this attribute on its view while snapshot overlays are
# visible.  Keeping it private avoids adding animation state to the data model.
ANIMATION_HIDDEN_IDS_ATTRIBUTE = "_missionary_animation_hidden_ids"


def _valid_color(value: Any) -> QColor | None:
    if value is None:
        return None
    color = QColor(value)
    return color if color.isValid() else None


class MissionaryRowDelegate(QStyledItemDelegate):
    """Paint missionary rows with inexpensive, delegate-owned visuals.

    Args:
        parent: Usually the owning :class:`QTableView`.
        color_styles: Optional mapping of semantic colour names to
            ``(fill, accent)`` values.  It replaces matching defaults and can
            add application-specific colours.
        row_height: Minimum row height returned from :meth:`sizeHint`.
    """

    def __init__(
        self,
        parent=None,
        *,
        color_styles: Mapping[str, tuple[Any, Any]] | None = None,
        row_height: int = 40,
    ):
        super().__init__(parent)
        self._row_height = max(1, int(row_height))
        self._color_styles = dict(DEFAULT_MISSIONARY_ROW_COLOR_STYLES)
        if color_styles:
            self._color_styles.update(color_styles)

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(self._row_height, hint.height()))

    def paint(self, painter: QPainter, option, index):
        view = self._table_view(option)
        missionary_id = index.data(MISSIONARY_ID_ROLE)
        hidden_ids = getattr(view, ANIMATION_HIDDEN_IDS_ATTRIBUTE, ()) if view else ()

        styled_option = QStyleOptionViewItem(option)
        self.initStyleOption(styled_option, index)

        painter.save()
        try:
            if missionary_id in hidden_ids:
                self._paint_empty_cell(painter, styled_option)
                return

            fill, accent = self._row_colors(index, styled_option)
            painter.fillRect(styled_option.rect, fill)

            selected = bool(styled_option.state & QStyle.State_Selected)
            hovered = bool(styled_option.state & QStyle.State_MouseOver)
            focused = bool(styled_option.state & QStyle.State_HasFocus)
            pending = bool(index.data(PENDING_ROLE))

            if hovered and not selected:
                painter.fillRect(styled_option.rect, QColor(15, 23, 42, 14))
            if selected:
                painter.fillRect(styled_option.rect, QColor(37, 99, 235, 48))
            if pending:
                self._paint_pending_overlay(painter, styled_option.rect)

            self._paint_separator(painter, styled_option)
            self._paint_content(
                painter,
                styled_option,
                view,
                force_dark_text=index.data(ROW_COLOR_ROLE) is not None,
            )

            if accent is not None and self._is_first_visible_column(view, index.column()):
                accent_rect = styled_option.rect.adjusted(1, 5, 0, -5)
                accent_rect.setWidth(3)
                painter.fillRect(accent_rect, accent)

            if pending and self._is_first_visible_column(view, index.column()):
                painter.setPen(Qt.NoPen)
                painter.setBrush(accent or QColor("#64748B"))
                painter.drawEllipse(styled_option.rect.left() + 8, styled_option.rect.center().y() - 2, 5, 5)

            if focused:
                focus_color = accent or QColor("#2563EB")
                pen = QPen(focus_color, 1)
                pen.setStyle(Qt.DotLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(styled_option.rect.adjusted(1, 1, -2, -2))
        finally:
            painter.restore()

    def _table_view(self, option) -> QTableView | None:
        widget = getattr(option, "widget", None)
        if isinstance(widget, QTableView):
            return widget
        parent = self.parent()
        return parent if isinstance(parent, QTableView) else None

    def _row_colors(self, index, option) -> tuple[QColor, QColor | None]:
        semantic_color = index.data(ROW_COLOR_ROLE)
        fill_value = None
        accent_value = index.data(ROW_ACCENT_ROLE)
        accent_is_semantic = (
            isinstance(accent_value, str)
            and accent_value.casefold() in self._color_styles
        )
        accent = None if accent_is_semantic else _valid_color(accent_value)

        if semantic_color is not None:
            style = self._color_styles.get(str(semantic_color).casefold())
            if style is not None:
                fill_value, default_accent = style
                # Models may expose the semantic row colour through both
                # roles.  Only a valid direct QColor should override the
                # palette's mapped accent.
                if accent is None:
                    accent = _valid_color(default_accent)
            else:
                # A model may supply a QColor or a direct CSS colour instead of
                # one of the standard semantic names.
                fill_value = semantic_color

        fill = _valid_color(fill_value)
        if fill is None:
            if option.features & QStyleOptionViewItem.Alternate:
                fill = option.palette.alternateBase().color()
            else:
                fill = option.palette.base().color()

        return fill, accent

    @staticmethod
    def _paint_empty_cell(painter: QPainter, option):
        if option.features & QStyleOptionViewItem.Alternate:
            fill = option.palette.alternateBase().color()
        else:
            fill = option.palette.base().color()
        painter.fillRect(option.rect, fill)
        MissionaryRowDelegate._paint_separator(painter, option)

    @staticmethod
    def _paint_separator(painter: QPainter, option):
        separator = option.palette.mid().color()
        separator.setAlpha(38)
        painter.setPen(QPen(separator, 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

    @staticmethod
    def _paint_pending_overlay(painter: QPainter, rect):
        painter.fillRect(rect, QColor(255, 255, 255, 62))
        stripe = QColor(100, 116, 139, 20)
        painter.setPen(QPen(stripe, 1))
        start = rect.left() - rect.height()
        end = rect.right() + rect.height()
        for x in range(start, end, 12):
            painter.drawLine(x, rect.bottom(), x + rect.height(), rect.top())

    @staticmethod
    def _paint_content(painter, option, view, *, force_dark_text):
        content_option = QStyleOptionViewItem(option)
        content_option.state &= ~(
            QStyle.State_Selected
            | QStyle.State_MouseOver
            | QStyle.State_HasFocus
        )
        content_option.features &= ~QStyleOptionViewItem.Alternate
        content_option.backgroundBrush = QBrush(Qt.NoBrush)
        content_option.showDecorationSelected = False

        transparent = QBrush(Qt.transparent)
        palette = QPalette(content_option.palette)
        palette.setBrush(QPalette.Base, transparent)
        palette.setBrush(QPalette.AlternateBase, transparent)
        palette.setBrush(QPalette.Highlight, transparent)
        if force_dark_text:
            text_brush = QBrush(QColor("#18181B"))
            palette.setBrush(QPalette.Text, text_brush)
            palette.setBrush(QPalette.HighlightedText, text_brush)
        content_option.palette = palette

        style = view.style() if view is not None else QApplication.style()
        style.drawControl(
            QStyle.CE_ItemViewItem,
            content_option,
            painter,
            view,
        )

    @staticmethod
    def _is_first_visible_column(view: QTableView | None, logical_column: int) -> bool:
        if view is None:
            return logical_column == 0
        header = view.horizontalHeader()
        for visual_index in range(header.count()):
            candidate = header.logicalIndex(visual_index)
            if candidate >= 0 and not header.isSectionHidden(candidate):
                return candidate == logical_column
        return logical_column == 0
