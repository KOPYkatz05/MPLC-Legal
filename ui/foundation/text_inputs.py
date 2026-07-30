from PySide6.QtWidgets import (
    QFrame,
    QLineEdit,
    QPlainTextEdit,
)


class ChatLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrame(False)


class ChatPlainTextEdit(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        # StyledPanel gives PixelCrispTextInputStyle a stable frame primitive
        # to render.  The proxy style owns its appearance completely.
        self.setFrameShape(QFrame.StyledPanel)
        self.viewport().setAutoFillBackground(False)


def _configure_chat_text_box(widget, fixed_height=None, variant="line"):
    widget.setProperty("chatTextBox", True)
    widget.setProperty("chatTextBoxVariant", variant)
    widget.setAutoFillBackground(False)
    widget.setContentsMargins(0, 0, 0, 0)
    if fixed_height is not None:
        widget.setFixedHeight(fixed_height)
    return widget


def create_line_edit(placeholder="", object_name="AppTextInput", parent=None):
    line_edit = ChatLineEdit(parent)
    if object_name:
        line_edit.setObjectName(object_name)
    line_edit.setPlaceholderText(placeholder)
    return _configure_chat_text_box(
        line_edit,
        fixed_height=42,
        variant="line",
    )


def create_search_edit(placeholder="", object_name="SearchInput", parent=None):
    edit = ChatLineEdit(parent)
    if object_name:
        edit.setObjectName(object_name)
    edit.setPlaceholderText(placeholder)
    edit.setClearButtonEnabled(True)
    return _configure_chat_text_box(
        edit,
        fixed_height=42,
        variant="search",
    )


def create_plain_text_edit(object_name="AppTextArea", parent=None):
    edit = ChatPlainTextEdit(parent)
    if object_name:
        edit.setObjectName(object_name)
    return _configure_chat_text_box(edit, variant="textarea")
