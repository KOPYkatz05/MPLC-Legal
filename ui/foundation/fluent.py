from PySide6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QPushButton,
    QTableWidget,
)

try:
    from qfluentwidgets import (
        ComboBox as FluentComboBox,
        LineEdit as FluentLineEdit,
        PrimaryPushButton,
        PushButton,
        TableWidget,
    )

    FLUENT_AVAILABLE = True
except Exception:
    FluentComboBox = QComboBox
    FluentLineEdit = QLineEdit
    PrimaryPushButton = QPushButton
    PushButton = QPushButton
    TableWidget = QTableWidget
    FLUENT_AVAILABLE = False


BUTTON_OBJECT_NAMES = {
    "primary": "PrimaryButton",
    "secondary": "SecondaryButton",
    "subtle": "SubtleButton",
    "danger": "DangerButton",
    "success": "SuccessButton",
}


def create_button(text, variant="secondary", fixed_height=34, parent=None):
    button_class = (
        PrimaryPushButton
        if FLUENT_AVAILABLE and variant in {"primary", "success"}
        else PushButton
    )
    button = button_class(text, parent)
    button.setObjectName(
        BUTTON_OBJECT_NAMES.get(variant, BUTTON_OBJECT_NAMES["secondary"])
    )
    if fixed_height:
        button.setFixedHeight(fixed_height)
    return button


def create_line_edit(placeholder="", object_name="SearchInput", parent=None):
    line_edit = FluentLineEdit(parent)
    line_edit.setObjectName(object_name)
    line_edit.setPlaceholderText(placeholder)
    line_edit.setFixedHeight(34)
    return line_edit


def create_combo_box(object_name="FilterCombo", parent=None):
    combo = FluentComboBox(parent)
    combo.setObjectName(object_name)
    combo.setFixedHeight(34)
    return combo


def create_table(object_name="MissionaryTable", parent=None):
    table = TableWidget(parent)
    table.setObjectName(object_name)
    return table
