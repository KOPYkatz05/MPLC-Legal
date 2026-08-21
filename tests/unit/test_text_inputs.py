import inspect
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent, QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QPushButton,
    QStyle,
    QStyleOptionFrame,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
)

from ui.foundation import text_inputs
from ui.foundation import text_input_style
from ui.foundation.text_input_style import (
    PixelCrispTextInputStyle,
    install_pixel_crisp_text_input_style,
)
from ui.foundation.text_inputs import (
    ChatLineEdit,
    ChatPlainTextEdit,
    create_line_edit,
    create_plain_text_edit,
    create_search_edit,
)
from ui.foundation import create_date_picker


def _flush_deletes(qapp):
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def test_standard_text_input_factories_preserve_widget_contracts(qapp):
    line_edit = create_line_edit("Missionary name")
    search_edit = create_search_edit("Search missionaries")
    plain_text_edit = create_plain_text_edit()

    assert isinstance(line_edit, ChatLineEdit)
    assert isinstance(search_edit, ChatLineEdit)
    assert isinstance(plain_text_edit, ChatPlainTextEdit)
    assert line_edit.objectName() == "AppTextInput"
    assert search_edit.objectName() == "SearchInput"
    assert plain_text_edit.objectName() == "AppTextArea"
    assert line_edit.placeholderText() == "Missionary name"
    assert search_edit.placeholderText() == "Search missionaries"
    assert line_edit.height() == 42
    assert search_edit.height() == 42
    assert search_edit.isClearButtonEnabled()
    assert not line_edit.hasFrame()
    assert plain_text_edit.frameShape() == QFrame.StyledPanel
    assert line_edit.graphicsEffect() is None
    assert search_edit.graphicsEffect() is None
    assert plain_text_edit.graphicsEffect() is None
    assert line_edit.property("chatTextBoxVariant") == "line"
    assert search_edit.property("chatTextBoxVariant") == "search"
    assert plain_text_edit.property("chatTextBoxVariant") == "textarea"


def test_line_edit_factory_can_create_locked_text_box(qapp):
    line_edit = create_line_edit("Missionary name", locked=True)

    assert line_edit.isReadOnly()
    assert line_edit.property("lockedTextBox") is True
    assert line_edit.property("editLocked") is True


def test_missionary_detail_requires_commit_before_unlocking_another_box(qapp):
    from ui.pages.missionary_detail_page import (
        IntentionalEditField,
        MissionaryDetailPage,
    )

    class Harness:
        _set_detail_editor_locked = (
            MissionaryDetailPage._set_detail_editor_locked
        )
        _unlock_detail_editor = MissionaryDetailPage._unlock_detail_editor
        _lock_active_detail_editor = (
            MissionaryDetailPage._lock_active_detail_editor
        )

    first = create_line_edit("First", locked=True)
    second = create_line_edit("Second", locked=True)
    first_field = IntentionalEditField()
    second_field = IntentionalEditField()
    harness = Harness()
    harness._active_detail_editor = None
    harness._detail_edit_fields = {
        first: first_field,
        second: second_field,
    }

    harness._unlock_detail_editor(first)
    assert not first.isReadOnly()
    assert second.isReadOnly()

    harness._unlock_detail_editor(second)
    assert not first.isReadOnly()
    assert second.isReadOnly()
    assert harness._active_detail_editor is first


def test_locked_field_reveals_edit_button_when_child_input_is_hovered(qapp):
    from ui.pages.missionary_detail_page import IntentionalEditField

    field = IntentionalEditField()
    layout = QVBoxLayout(field)
    edit_button = QPushButton("Edit")
    editor = create_line_edit("Name", locked=True)
    field.set_edit_button(edit_button)
    layout.addWidget(edit_button)
    layout.addWidget(editor)
    field.enable_hover_tracking()
    field.resize(320, 100)
    field.show()
    qapp.processEvents()

    # Send the same child-enter event Qt emits on a real pointer transition.
    # QTest.mouseMove does not update the native cursor under every headless
    # Windows test backend, which made this assertion backend-dependent.
    QCoreApplication.sendEvent(editor, QEvent(QEvent.Enter))
    qapp.processEvents()

    assert edit_button.isVisible()


def test_field_edit_button_animates_loader_into_success(qapp):
    from ui.pages.missionary_detail_page import FieldEditButton

    button = FieldEditButton()
    button.show()
    finished = []
    button.start_loading()
    assert button._spin_timer.isActive()
    assert button.isEnabled()
    assert button.is_loading()

    button.show_success(lambda: finished.append(True))
    assert not button._spin_timer.isActive()
    QTest.qWait(750)
    qapp.processEvents()

    assert finished == [True]
    assert button._opacity_effect.opacity() == pytest.approx(1.0)


def test_single_field_checkmark_persists_only_that_field(qapp):
    from ui.foundation.background_loader import LatestRequestLoader
    from ui.pages.missionary_detail_page import (
        FieldEditButton,
        IntentionalEditField,
        MissionaryDetailPage,
    )

    class InlineThreadPool:
        @staticmethod
        def start(task):
            task.run()

    class Harness:
        _set_detail_editor_locked = MissionaryDetailPage._set_detail_editor_locked
        _detail_field_key = MissionaryDetailPage._detail_field_key
        _save_detail_editor = MissionaryDetailPage._save_detail_editor
        _lock_active_detail_editor = MissionaryDetailPage._lock_active_detail_editor

        def _clear_detail_form_focus(self):
            self.focus_clear_count += 1

        def _reload_missionary(self):
            self.reload_count += 1

        def _refresh_missionaries_table(self):
            self.refresh_count += 1

    editor = create_line_edit("Name", locked=False)
    editor.setText("Updated Name")
    button = FieldEditButton()
    field = IntentionalEditField()
    field.set_edit_button(button)
    field.set_unlocked(True)
    calls = []
    harness = Harness()
    harness.current_missionary = SimpleNamespace(id=7, full_name="Old Name")
    harness._text_edits = {"full_name": editor}
    harness._date_edits = {}
    harness._detail_edit_buttons = {editor: button}
    harness._detail_edit_fields = {editor: field}
    harness._active_detail_editor = editor
    harness._detail_field_save_loader = LatestRequestLoader(
        thread_pool=InlineThreadPool()
    )
    harness.missionary_service = SimpleNamespace(
        update_fields=lambda missionary_id, updates: calls.append(
            (missionary_id, dict(updates))
        )
    )
    harness.reload_count = 0
    harness.refresh_count = 0
    harness.focus_clear_count = 0

    harness._save_detail_editor(editor)
    QTest.qWait(750)
    qapp.processEvents()

    assert calls == [(7, {"full_name": "Updated Name"})]
    assert harness.current_missionary.full_name == "Updated Name"
    assert editor.isReadOnly()
    assert harness._active_detail_editor is None
    assert harness.reload_count == harness.refresh_count == 1
    assert harness.focus_clear_count == 1


def test_detail_refresh_moves_focus_off_editors_and_clears_selection(qapp):
    from ui.pages.missionary_detail_page import MissionaryDetailPage

    class FocusHarness(QFrame):
        _clear_detail_form_focus = MissionaryDetailPage._clear_detail_form_focus

    harness = FocusHarness()
    first = create_line_edit("First", parent=harness)
    second = create_line_edit("Second", parent=harness)
    first.setText("First value")
    second.setText("Passport value")
    harness._text_edits = {"first": first, "passport": second}
    harness._date_edits = {}
    harness._detail_edit_buttons = {}
    harness.show()
    second.setFocus()
    second.selectAll()
    qapp.processEvents()
    assert second.selectedText() == "Passport value"

    harness._clear_detail_form_focus()
    qapp.processEvents()

    assert first.selectedText() == ""
    assert second.selectedText() == ""
    assert qapp.focusWidget() is harness


def test_date_picker_factory_coordinates_pencil_and_calendar_icon(qapp):
    picker = create_date_picker(locked=True)
    picker.setFixedWidth(300)
    edit_button = QPushButton()
    edit_button.setFixedSize(28, 24)
    picker.set_edit_action(edit_button)
    picker.show()
    qapp.processEvents()

    calendar_rect = picker._calendar_icon.geometry()
    pencil_rect = edit_button.geometry()
    assert picker.height() == 42
    assert picker.isReadOnly()
    assert picker.getDate() == picker.date()
    assert picker.getDateFormat() == "MMM d, yyyy"
    assert pencil_rect.right() < calendar_rect.left()
    assert calendar_rect.left() - pencil_rect.right() - 1 == picker.CONTROL_GAP
    assert calendar_rect.right() == picker.width() - picker.EDGE_MARGIN - 1


def test_date_picker_factory_paints_complete_bottom_border(qapp):
    picker = create_date_picker(locked=True)
    picker.setFixedWidth(300)
    picker.show()
    qapp.processEvents()

    image = picker.grab().toImage()
    center_bottom = image.pixelColor(image.width() // 2, image.height() - 1)
    assert center_bottom.name() == "#d4d4d8"


def test_date_picker_factory_configures_app_popup_calendar(qapp):
    picker = create_date_picker()
    calendar = picker.calendarWidget()

    assert calendar.objectName() == "AppDatePickerCalendar"
    assert not calendar.isGridVisible()
    assert calendar.minimumWidth() == 336
    assert calendar.minimumHeight() == 292
    for object_name in ("qt_calendar_prevmonth", "qt_calendar_nextmonth"):
        button = calendar.findChild(QToolButton, object_name)
        assert button is not None
        assert not button.icon().isNull()

    weekend_color = calendar.weekdayTextFormat(Qt.Sunday).foreground().color()
    assert weekend_color.name() == "#71717a"
    selected_format = calendar.dateTextFormat(calendar.selectedDate())
    assert selected_format.foreground().color().name() == "#ffffff"
    assert selected_format.background().style() == Qt.NoBrush
    outside_date = next(
        formatted_date
        for formatted_date in picker._formatted_calendar_dates
        if formatted_date.month() != calendar.monthShown()
    )
    outside_format = calendar.dateTextFormat(outside_date)
    assert outside_format.foreground().color().name() == "#d4d4d8"

    stylesheet = Path("assets/styles/theme.qss").read_text(encoding="utf-8")
    calendar_styles = stylesheet.split(
        "QCalendarWidget#AppDatePickerCalendar",
        1,
    )[1].split("/* ==========================================", 1)[0]
    assert "selection-background-color: transparent" in calendar_styles
    assert "selection-color: #FFFFFF" in calendar_styles


def test_date_picker_grays_preceding_week_when_month_starts_on_first_day(qapp):
    picker = create_date_picker()
    calendar = picker.calendarWidget()

    # April 2007 began on Sunday. Qt displays March 25-31 as a full leading
    # week, even when Sunday is the calendar's configured first weekday.
    calendar.setCurrentPage(2007, 4)
    qapp.processEvents()

    for day in range(25, 32):
        date_format = calendar.dateTextFormat(QDate(2007, 3, day))
        assert date_format.foreground().color().name() == "#d4d4d8"


def test_date_picker_delegate_owns_rounded_selection_and_adjacent_dates(qapp):
    picker = create_date_picker()
    calendar = picker.calendarWidget()
    calendar.setCurrentPage(2007, 8)
    calendar.setSelectedDate(QDate(2007, 8, 2))
    qapp.processEvents()
    view = calendar.findChild(QTableView, "qt_calendar_calendarview")
    delegate = view.itemDelegate()

    assert delegate.date_for_index(view.model().index(1, 0)) == QDate(2007, 7, 29)
    selected_index = view.model().index(1, 4)
    assert delegate.date_for_index(selected_index) == QDate(2007, 8, 2)

    image = QImage(44, 36, QImage.Format_ARGB32_Premultiplied)
    # Simulate the native rectangular Qt selection beneath the delegate.
    image.fill("#0ea5ac")
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 44, 36)
    option.font = view.font()
    painter = QPainter(image)
    delegate.paint(painter, option, selected_index)
    painter.end()

    # The delegate erases the native selection, leaving a clean white inset
    # around the rounded app highlight.
    assert image.pixelColor(4, 2).name() == "#ffffff"
    assert image.pixelColor(0, image.height() // 2).name() == "#ffffff"
    assert image.pixelColor(10, 6).name() == "#0ea5ac"


def test_date_picker_slides_forward_between_months(qapp):
    picker = create_date_picker()
    calendar = picker.calendarWidget()
    calendar.window().show()
    qapp.processEvents()
    next_button = calendar.findChild(QToolButton, "qt_calendar_nextmonth")

    QTest.mouseClick(next_button, Qt.LeftButton)
    qapp.processEvents()

    assert picker._calendar_slide is not None
    assert len(picker._calendar_slide_overlays) == 2
    view = calendar.findChild(QTableView, "qt_calendar_calendarview")
    assert not view.viewport().isVisible()

    QTest.qWait(220)
    qapp.processEvents()
    assert picker._calendar_slide is None
    assert view.viewport().isVisible()


def test_text_input_factory_uses_no_direct_style_or_painter_code():
    source = inspect.getsource(text_inputs).casefold()
    assert "qgraphicsdropshadoweffect" not in source
    assert "setstylesheet" not in source
    assert "qpainter" not in source
    assert "wa_translucentbackground" not in source


def test_chat_input_styles_leave_surface_rendering_to_the_proxy_style():
    stylesheet = Path("assets/styles/theme.qss").read_text(encoding="utf-8")

    assert stylesheet.count('QLineEdit[chatTextBox="true"],') == 1
    assert 'QAbstractScrollArea::viewport' in stylesheet
    chat_block = stylesheet.split('QLineEdit[chatTextBox="true"],', 1)[1].split(
        'QLineEdit[chatTextBoxVariant="search"]',
        1,
    )[0]
    assert "border:" not in chat_block
    assert "border-radius:" not in chat_block
    assert "background" not in chat_block


def test_pixel_crisp_style_installs_once(qapp):
    style = install_pixel_crisp_text_input_style(qapp)
    assert isinstance(style, PixelCrispTextInputStyle)
    assert install_pixel_crisp_text_input_style(qapp) is style


def test_pixel_crisp_style_only_uses_qts_active_painter():
    source = inspect.getsource(text_input_style).casefold()
    assert "painter.begin" not in source
    assert "painter.end" not in source
    assert "paintevent" not in source


@pytest.mark.parametrize("device_pixel_ratio", [1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize(
    ("state", "expected_color"),
    [
        (QStyle.State_Enabled, "#dadadf"),
        (QStyle.State_Enabled | QStyle.State_MouseOver, "#c8c8cf"),
        (QStyle.State_Enabled | QStyle.State_HasFocus, "#0ea5ac"),
    ],
)
def test_pixel_crisp_style_draws_one_physical_pixel_border(
    device_pixel_ratio,
    state,
    expected_color,
):
    logical_width = 120
    logical_height = 42
    image = QImage(
        math.ceil(logical_width * device_pixel_ratio),
        math.ceil(logical_height * device_pixel_ratio),
        QImage.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(device_pixel_ratio)
    image.fill("#00000000")
    option = QStyleOptionFrame()
    option.rect = QRect(0, 0, logical_width, logical_height)
    option.state = state
    painter = QPainter(image)
    PixelCrispTextInputStyle._draw_input_surface(option, painter)
    painter.end()

    center_x = image.width() // 2
    center_y = image.height() // 2
    assert image.pixelColor(center_x, 0).name() == expected_color
    assert image.pixelColor(center_x, 1).name() == "#ffffff"
    assert image.pixelColor(0, center_y).name() == expected_color
    assert image.pixelColor(1, center_y).name() == "#ffffff"
    assert image.pixelColor(center_x, image.height() - 1).name() == expected_color
    assert image.pixelColor(image.width() - 1, center_y).name() == expected_color


def test_locked_text_box_factory_draws_muted_gray_surface(qapp):
    widget = create_line_edit("Name", locked=True)
    image = QImage(120, 42, QImage.Format_ARGB32_Premultiplied)
    image.fill("#00000000")
    option = QStyleOptionFrame()
    option.rect = QRect(0, 0, 120, 42)
    option.state = QStyle.State_Enabled
    painter = QPainter(image)
    PixelCrispTextInputStyle._draw_input_surface(
        option,
        painter,
        widget,
    )
    painter.end()

    assert image.pixelColor(60, 21).name() == "#f4f4f5"
    assert image.pixelColor(60, 0).name() == "#d4d4d8"


def test_repeated_text_input_dialog_lifecycle_is_stable(qapp):
    for _ in range(4):
        dialog = QDialog()
        layout = QVBoxLayout(dialog)
        layout.addWidget(create_line_edit("Name"))
        layout.addWidget(create_search_edit("Search"))
        layout.addWidget(create_plain_text_edit())
        dialog.show()
        qapp.processEvents()
        dialog.close()
        dialog.deleteLater()
        _flush_deletes(qapp)
