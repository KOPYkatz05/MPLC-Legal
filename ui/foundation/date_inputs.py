"""Standard date-input factory with coordinated trailing controls."""

from PySide6.QtCore import (
    QDate,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDateEdit,
    QLabel,
    QStyle,
    QStyleOptionFrame,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
)

from ui.foundation.icons import lucide_icon
from ui.foundation.text_input_style import PixelCrispTextInputStyle


# AppDatePicker palette. These are the primary color-editing points for the
# calendar popup; matching QSS states live under AppDatePickerCalendar.
CALENDAR_ACCENT = "#0EA5AC"
CALENDAR_ACCENT_SOFT = "#EFFCFC"
CALENDAR_SELECTED_TEXT = "#FFFFFF"
CALENDAR_WEEKEND_TEXT = "#71717A"
CALENDAR_OUTSIDE_MONTH_TEXT = "#D4D4D8"


class CalendarDayDelegate(QStyledItemDelegate):
    """Paint calendar days with app-owned selection and month states."""

    def __init__(self, calendar):
        super().__init__(calendar)
        self._calendar = calendar

    def date_for_index(self, index):
        if not index.isValid() or index.row() == 0:
            return QDate()
        first = QDate(
            self._calendar.yearShown(),
            self._calendar.monthShown(),
            1,
        )
        leading_days = (
            first.dayOfWeek() - self._calendar.firstDayOfWeek().value
        ) % 7
        if leading_days == 0:
            leading_days = 7
        grid_start = first.addDays(-leading_days)
        return grid_start.addDays((index.row() - 1) * 7 + index.column())

    def paint(self, painter, option, index):
        visible_date = self.date_for_index(index)
        if not visible_date.isValid():
            super().paint(painter, option, index)
            return

        is_selected = visible_date == self._calendar.selectedDate()
        is_current_month = (
            visible_date.year() == self._calendar.yearShown()
            and visible_date.month() == self._calendar.monthShown()
        )
        is_today = visible_date == QDate.currentDate()
        is_hovered = bool(option.state & QStyle.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Erase Qt's native square selection/current-index background before
        # painting our rounded state. Otherwise a one-pixel accent sliver can
        # remain visible around the custom tile on some Windows styles.
        painter.fillRect(option.rect, QColor("#FFFFFF"))
        cell = option.rect.adjusted(4, 2, -4, -2)
        if is_selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(CALENDAR_ACCENT))
            painter.drawRoundedRect(cell, 7, 7)
            text_color = QColor(CALENDAR_SELECTED_TEXT)
        else:
            if is_hovered or is_today:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(CALENDAR_ACCENT_SOFT))
                painter.drawRoundedRect(cell, 7, 7)
            text_color = QColor(
                "#18181B" if is_current_month else CALENDAR_OUTSIDE_MONTH_TEXT
            )

        font = option.font
        if is_selected or is_today:
            font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(option.rect, Qt.AlignCenter, str(visible_date.day()))
        painter.restore()


class AppDatePicker(QDateEdit):
    """A date editor whose surface and trailing icons are factory-owned."""

    CONTROL_SIZE = 24
    CONTROL_GAP = 4
    EDGE_MARGIN = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._edit_action = None
        self._calendar_slide = None
        self._calendar_slide_overlays = []
        self._pending_calendar_snapshot = None
        self._pending_calendar_direction = 0
        self.setCalendarPopup(True)
        self._configure_calendar_popup()
        self.setFrame(False)
        self.setFixedHeight(42)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)
        self.setProperty("dateTextBox", True)

        palette = self.palette()
        palette.setColor(QPalette.Base, Qt.transparent)
        self.setPalette(palette)

        self._calendar_icon = QLabel(self)
        self._calendar_icon.setObjectName("DatePickerCalendarIcon")
        self._calendar_icon.setFixedSize(self.CONTROL_SIZE, self.CONTROL_SIZE)
        self._calendar_icon.setAlignment(Qt.AlignCenter)
        self._calendar_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        icon = lucide_icon("calendar-days", size=16, color="#18181B")
        if icon is not None and not icon.isNull():
            self._calendar_icon.setPixmap(icon.pixmap(QSize(16, 16)))

    def _configure_calendar_popup(self):
        calendar = self.calendarWidget()
        calendar.setObjectName("AppDatePickerCalendar")
        calendar.setGridVisible(False)
        calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        calendar.setMinimumSize(336, 292)
        calendar_view = calendar.findChild(
            QTableView,
            "qt_calendar_calendarview",
        )
        if calendar_view is not None:
            self._calendar_day_delegate = CalendarDayDelegate(calendar)
            calendar_view.setItemDelegate(self._calendar_day_delegate)
            calendar_view.setMouseTracking(True)
        self._formatted_calendar_dates = set()

        weekend_format = QTextCharFormat()
        weekend_format.setForeground(QColor(CALENDAR_WEEKEND_TEXT))
        calendar.setWeekdayTextFormat(Qt.Saturday, weekend_format)
        calendar.setWeekdayTextFormat(Qt.Sunday, weekend_format)
        calendar.currentPageChanged.connect(self._refresh_calendar_date_formats)
        calendar.currentPageChanged.connect(self._queue_calendar_slide)
        calendar.selectionChanged.connect(
            lambda: self._refresh_calendar_date_formats(
                calendar.yearShown(),
                calendar.monthShown(),
            )
        )
        palette = calendar.palette()
        # The delegate owns selection painting. A transparent native highlight
        # prevents Qt's square selection from peeking around the rounded tile.
        palette.setColor(QPalette.Highlight, Qt.transparent)
        palette.setColor(
            QPalette.HighlightedText,
            QColor(CALENDAR_SELECTED_TEXT),
        )
        calendar.setPalette(palette)
        self._refresh_calendar_date_formats(
            calendar.yearShown(),
            calendar.monthShown(),
        )

        navigation_icons = {
            "qt_calendar_prevmonth": "chevron-left",
            "qt_calendar_nextmonth": "chevron-right",
        }
        for object_name, icon_name in navigation_icons.items():
            button = calendar.findChild(QToolButton, object_name)
            icon = lucide_icon(icon_name, size=16, color="#3F3F46")
            if button is not None and icon is not None and not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(16, 16))
            if button is not None:
                button.installEventFilter(self)
                button.setProperty(
                    "calendarSlideDirection",
                    -1 if object_name == "qt_calendar_prevmonth" else 1,
                )

    def eventFilter(self, watched, event):
        direction = watched.property("calendarSlideDirection") if watched else None
        if direction and event.type() == QEvent.MouseButtonPress:
            self._finish_calendar_slide()
            view = self.calendarWidget().findChild(
                QTableView,
                "qt_calendar_calendarview",
            )
            if view is not None and view.viewport().isVisible():
                self._pending_calendar_snapshot = view.viewport().grab()
                self._pending_calendar_direction = int(direction)
        return super().eventFilter(watched, event)

    def _queue_calendar_slide(self, *_args):
        if self._pending_calendar_snapshot is None:
            return
        QTimer.singleShot(0, self._start_calendar_slide)

    def _start_calendar_slide(self):
        old_pixmap = self._pending_calendar_snapshot
        direction = self._pending_calendar_direction
        self._pending_calendar_snapshot = None
        self._pending_calendar_direction = 0
        if old_pixmap is None or not direction:
            return

        view = self.calendarWidget().findChild(
            QTableView,
            "qt_calendar_calendarview",
        )
        if view is None or view.viewport().size().isEmpty():
            return
        new_pixmap = view.viewport().grab()
        viewport_geometry = view.viewport().geometry()
        width = viewport_geometry.width()
        if width <= 0:
            return

        old_overlay = QLabel(view)
        new_overlay = QLabel(view)
        for overlay, pixmap in (
            (old_overlay, old_pixmap),
            (new_overlay, new_pixmap),
        ):
            overlay.setPixmap(pixmap)
            overlay.setScaledContents(True)
            overlay.setGeometry(viewport_geometry)
            overlay.show()
            overlay.raise_()

        offset = width if direction > 0 else -width
        new_overlay.setGeometry(viewport_geometry.translated(offset, 0))
        view.viewport().setVisible(False)
        self._calendar_slide_overlays = [old_overlay, new_overlay]

        group = QParallelAnimationGroup(self)
        for overlay, start_rect, end_rect in (
            (
                old_overlay,
                viewport_geometry,
                viewport_geometry.translated(-offset, 0),
            ),
            (
                new_overlay,
                viewport_geometry.translated(offset, 0),
                viewport_geometry,
            ),
        ):
            animation = QPropertyAnimation(overlay, b"geometry", group)
            animation.setDuration(180)
            animation.setStartValue(QRect(start_rect))
            animation.setEndValue(QRect(end_rect))
            animation.setEasingCurve(QEasingCurve.OutCubic)

        self._calendar_slide = group
        group.finished.connect(self._finish_calendar_slide)
        group.start()

    def _finish_calendar_slide(self):
        group = self._calendar_slide
        self._calendar_slide = None
        if group is not None:
            group.stop()
        for overlay in self._calendar_slide_overlays:
            overlay.deleteLater()
        self._calendar_slide_overlays = []
        view = self.calendarWidget().findChild(
            QTableView,
            "qt_calendar_calendarview",
        )
        if view is not None:
            view.viewport().setVisible(True)

    def _refresh_calendar_date_formats(self, year, month):
        calendar = self.calendarWidget()
        for formatted_date in self._formatted_calendar_dates:
            calendar.setDateTextFormat(formatted_date, QTextCharFormat())
        self._formatted_calendar_dates.clear()

        first = QDate(year, month, 1)
        first_day_of_week = calendar.firstDayOfWeek().value
        leading_days = (first.dayOfWeek() - first_day_of_week) % 7
        # QCalendarWidget always renders six complete weeks. When a month
        # starts on the configured first weekday, Qt includes the entire
        # preceding week rather than starting the grid on day one.
        if leading_days == 0:
            leading_days = 7
        grid_start = first.addDays(-leading_days)
        today = QDate.currentDate()
        selected_date = calendar.selectedDate()

        for offset in range(42):
            visible_date = grid_start.addDays(offset)
            date_format = QTextCharFormat()
            should_apply = False
            if visible_date.month() != month:
                date_format.setForeground(QColor(CALENDAR_OUTSIDE_MONTH_TEXT))
                should_apply = True
            if visible_date == today and visible_date != selected_date:
                date_format.setForeground(QColor(CALENDAR_ACCENT))
                date_format.setBackground(QColor(CALENDAR_ACCENT_SOFT))
                date_format.setFontWeight(QFont.DemiBold)
                should_apply = True
            if visible_date == selected_date:
                date_format.setForeground(QColor(CALENDAR_SELECTED_TEXT))
                date_format.setFontWeight(QFont.DemiBold)
                should_apply = True
            if should_apply:
                calendar.setDateTextFormat(visible_date, date_format)
                self._formatted_calendar_dates.add(visible_date)

    def set_edit_action(self, button):
        """Install the optional pencil action beside the calendar icon."""
        self._edit_action = button
        button.setParent(self)
        button.setFixedSize(28, 24)
        self._layout_trailing_controls()
        button.raise_()

    # Preserve the small compatibility surface exposed by the former Fluent
    # picker so existing forms can adopt the new factory without page changes.
    def getDate(self):
        return self.date()

    def getDateFormat(self):
        return self.displayFormat()

    def _layout_trailing_controls(self):
        center_y = self.height() // 2
        calendar_x = self.width() - self.EDGE_MARGIN - self.CONTROL_SIZE
        self._calendar_icon.move(
            calendar_x,
            center_y - self.CONTROL_SIZE // 2,
        )
        if self._edit_action is not None:
            self._edit_action.move(
                calendar_x - self.CONTROL_GAP - self._edit_action.width(),
                center_y - self._edit_action.height() // 2,
            )
            self._edit_action.raise_()
        self._calendar_icon.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_trailing_controls()

    def paintEvent(self, event):
        option = QStyleOptionFrame()
        option.initFrom(self)
        option.rect = self.rect()
        if self.hasFocus():
            option.state |= QStyle.State_HasFocus
        painter = QPainter(self)
        PixelCrispTextInputStyle._draw_input_surface(option, painter, self)
        painter.end()
        super().paintEvent(event)


def create_date_picker(object_name="DateInput", parent=None, *, locked=False):
    picker = AppDatePicker(parent)
    if object_name:
        picker.setObjectName(object_name)
    picker.setDisplayFormat("MMM d, yyyy")
    picker.setDate(QDate.currentDate())
    picker.setProperty("editLocked", bool(locked))
    picker.setReadOnly(bool(locked))
    return picker


def create_date_edit(object_name="DateInput", parent=None, *, locked=False):
    return create_date_picker(object_name, parent, locked=locked)
