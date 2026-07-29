from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLineEdit,
    QPlainTextEdit,
)


class ChatLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrame(False)
        self.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 1px solid #DADADF; "
            "border-radius: 12px; padding: 8px 13px; color: #18181B; "
            "font-size: 13px; }"
            "QLineEdit:focus { border-color: #0EA5AC; }"
        )


class ChatPlainTextEdit(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setStyleSheet(
            "QWidget { background: transparent; border: none; }"
        )
        self.setStyleSheet(
            "QPlainTextEdit { background: #FFFFFF; border: 1px solid #DADADF; "
            "border-radius: 12px; padding: 10px 13px; color: #18181B; "
            "font-size: 13px; }"
            "QPlainTextEdit:focus { border-color: #0EA5AC; }"
        )


def _configure_chat_text_box(widget, fixed_height=None):
    widget.setProperty("chatTextBox", True)
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    widget.setAutoFillBackground(False)
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setContentsMargins(0, 0, 0, 0)
    if fixed_height is not None:
        widget.setFixedHeight(fixed_height)

    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(10)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(15, 23, 42, 32))
    widget.setGraphicsEffect(shadow)
    return widget


def create_line_edit(placeholder="", object_name="SearchInput", parent=None):
    line_edit = ChatLineEdit(parent)
    if object_name:
        line_edit.setObjectName(object_name)
    line_edit.setPlaceholderText(placeholder)
    return _configure_chat_text_box(line_edit, fixed_height=42)


def create_search_edit(placeholder="", object_name="SearchInput", parent=None):
    edit = ChatLineEdit(parent)
    if object_name:
        edit.setObjectName(object_name)
    edit.setPlaceholderText(placeholder)
    edit.setClearButtonEnabled(True)
    return _configure_chat_text_box(edit, fixed_height=42)


def create_plain_text_edit(object_name="DocumentNotesEditor", parent=None):
    edit = ChatPlainTextEdit(parent)
    if object_name:
        edit.setObjectName(object_name)
    return _configure_chat_text_box(edit)
