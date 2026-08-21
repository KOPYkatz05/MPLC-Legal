import inspect
import math
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QPushButton,
    QStyle,
    QStyleOptionFrame,
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


def test_missionary_detail_unlocks_only_one_locked_text_box(qapp):
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
    assert first.isReadOnly()
    assert not second.isReadOnly()
    assert harness._active_detail_editor is second


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
