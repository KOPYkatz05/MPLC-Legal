"""Painting for the model-backed missionaries table.

The delegate intentionally depends only on standard Qt widgets.  The model
provides semantic values (row colour, accent and pending state); this class is
the single place where those values become pixels.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from ui.models.missionary_table_model import (
    MISSIONARY_ID_ROLE,
    PAINT_DATA_ROLE,
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
        paint_data = index.data(PAINT_DATA_ROLE)
        if paint_data is None:
            value = index.data(Qt.DisplayRole)
            missionary_id = index.data(MISSIONARY_ID_ROLE)
            semantic_color = index.data(ROW_COLOR_ROLE)
            accent_value = index.data(ROW_ACCENT_ROLE)
            pending = bool(index.data(PENDING_ROLE))
        else:
            (
                value,
                missionary_id,
                semantic_color,
                accent_value,
                pending,
            ) = paint_data
        hidden_ids = getattr(view, ANIMATION_HIDDEN_IDS_ATTRIBUTE, ()) if view else ()

        styled_option = QStyleOptionViewItem(option)

        painter.save()
        try:
            if missionary_id in hidden_ids:
                self._paint_empty_cell(painter, styled_option)
                return

            fill, accent = self._colors_for_values(
                semantic_color,
                accent_value,
                styled_option,
            )
            painter.fillRect(styled_option.rect, fill)

            selected = bool(styled_option.state & QStyle.State_Selected)
            hovered = bool(styled_option.state & QStyle.State_MouseOver)
            focused = bool(styled_option.state & QStyle.State_HasFocus)
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
                value,
                force_dark_text=semantic_color is not None,
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
        return self._colors_for_values(
            index.data(ROW_COLOR_ROLE),
            index.data(ROW_ACCENT_ROLE),
            option,
        )

    def _colors_for_values(
        self,
        semantic_color,
        accent_value,
        option,
    ) -> tuple[QColor, QColor | None]:
        fill_value = None
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
    def _paint_content(painter, option, value, *, force_dark_text):
        if value is None:
            return

        painter.setFont(option.font)
        if force_dark_text:
            text_color = QColor("#18181B")
        elif not option.state & QStyle.State_Enabled:
            text_color = option.palette.color(
                QPalette.Disabled,
                QPalette.Text,
            )
        else:
            text_color = option.palette.text().color()
        painter.setPen(text_color)

        text_rect = option.rect.adjusted(12, 0, -12, 0)
        text = painter.fontMetrics().elidedText(
            str(value),
            Qt.ElideRight,
            max(0, text_rect.width()),
        )
        painter.drawText(
            text_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            text,
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
