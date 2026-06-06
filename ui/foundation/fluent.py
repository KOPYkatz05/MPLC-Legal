from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSlider,
    QTableWidget,
    QTextEdit,
    QTabWidget,
)

try:
    from qfluentwidgets import (
        BodyLabel,
        CardWidget,
        ComboBox as FluentComboBox,
        DatePicker as FluentDatePicker,
        EditableComboBox,
        FluentIcon,
        HeaderCardWidget,
        InfoBar,
        LineEdit as FluentLineEdit,
        ListWidget as FluentListWidget,
        MaskDialogBase,
        MessageBox,
        PlainTextEdit as FluentPlainTextEdit,
        Pivot as FluentPivot,
        PrimaryPushButton,
        PushButton,
        RoundMenu,
        ScrollArea as FluentScrollArea,
        ScrollBar as FluentScrollBar,
        ScrollBarHandleDisplayMode,
        SearchLineEdit,
        SimpleCardWidget,
        Slider as FluentSlider,
        SmoothMode,
        SmoothScrollArea,
        SmoothScrollBar,
        SmoothScrollDelegate,
        SingleDirectionScrollArea,
        SubtitleLabel,
        TabWidget as FluentTabWidget,
        TableWidget,
        TextEdit as FluentTextEdit,
        TransparentPushButton,
    )

    FLUENT_AVAILABLE = True
except Exception:
    BodyLabel = QLabel
    CardWidget = QFrame
    EditableComboBox = QComboBox
    FluentComboBox = QComboBox
    FluentDatePicker = QDateEdit
    FluentIcon = None
    FluentLineEdit = QLineEdit
    FluentListWidget = QListWidget
    FluentPlainTextEdit = QPlainTextEdit
    FluentPivot = None
    FluentScrollArea = QScrollArea
    FluentScrollBar = QScrollBar
    FluentSlider = QSlider
    FluentTabWidget = QTabWidget
    FluentTextEdit = QTextEdit
    HeaderCardWidget = QFrame
    InfoBar = None
    MaskDialogBase = QDialog
    MessageBox = None
    PrimaryPushButton = QPushButton
    PushButton = QPushButton
    RoundMenu = QMenu
    SearchLineEdit = QLineEdit
    SimpleCardWidget = QFrame
    ScrollBarHandleDisplayMode = None
    SmoothMode = None
    SmoothScrollArea = QScrollArea
    SmoothScrollBar = QScrollBar
    SmoothScrollDelegate = None
    SingleDirectionScrollArea = QScrollArea
    SubtitleLabel = QLabel
    TableWidget = QTableWidget
    TransparentPushButton = QPushButton
    FLUENT_AVAILABLE = False


BUTTON_OBJECT_NAMES = {
    "primary": "PrimaryButton",
    "secondary": "SecondaryButton",
    "subtle": "SubtleButton",
    "danger": "DangerButton",
    "success": "SuccessButton",
}


def _set_fixed_height(widget, fixed_height):
    if fixed_height:
        widget.setFixedHeight(fixed_height)
    return widget


def _patch_fluent_combo_data_api(combo):
    if not FLUENT_AVAILABLE or getattr(combo, "_mission_data_patch", False):
        return combo

    native_add_item = combo.addItem

    def add_item(text, user_data=None, *args, **kwargs):
        if "userData" in kwargs:
            user_data = kwargs.pop("userData")
        if "icon" in kwargs:
            return native_add_item(text, kwargs["icon"], user_data)
        if args:
            return native_add_item(text, user_data, *args, **kwargs)

        native_add_item(text)
        if user_data is not None:
            combo.setItemData(combo.count() - 1, user_data)

    combo.addItem = add_item
    combo._mission_data_patch = True
    return combo


def create_button(text, variant="secondary", fixed_height=34, parent=None, icon=None):
    if FLUENT_AVAILABLE and variant in {"primary", "success"}:
        button_class = PrimaryPushButton
    elif FLUENT_AVAILABLE and variant == "subtle":
        button_class = TransparentPushButton
    else:
        button_class = PushButton

    if icon is not None and FLUENT_AVAILABLE:
        button = button_class(icon, text, parent)
    else:
        button = button_class(text, parent)

    button.setObjectName(
        BUTTON_OBJECT_NAMES.get(variant, BUTTON_OBJECT_NAMES["secondary"])
    )
    return _set_fixed_height(button, fixed_height)


def create_line_edit(placeholder="", object_name="SearchInput", parent=None):
    line_edit = FluentLineEdit(parent)
    line_edit.setObjectName(object_name)
    line_edit.setPlaceholderText(placeholder)
    return _set_fixed_height(line_edit, 34)


def create_search_edit(placeholder="", object_name="SearchInput", parent=None):
    edit = SearchLineEdit(parent)
    edit.setObjectName(object_name)
    edit.setPlaceholderText(placeholder)
    return _set_fixed_height(edit, 34)


def create_text_edit(object_name="NotesEditor", parent=None):
    edit = FluentTextEdit(parent)
    edit.setObjectName(object_name)
    return edit


def create_plain_text_edit(object_name="DocumentNotesEditor", parent=None):
    edit = FluentPlainTextEdit(parent)
    edit.setObjectName(object_name)
    return edit


def create_combo_box(object_name="FilterCombo", parent=None, editable=False):
    combo_class = EditableComboBox if editable else FluentComboBox
    combo = combo_class(parent)
    combo.setObjectName(object_name)
    _set_fixed_height(combo, 34)
    return _patch_fluent_combo_data_api(combo)


def create_date_picker(object_name="DateInput", parent=None):
    picker = FluentDatePicker(parent)
    picker.setObjectName(object_name)

    if FLUENT_AVAILABLE:
        picker.setDate(QDate.currentDate())
    else:
        picker.setCalendarPopup(True)
        picker.setDate(QDate.currentDate())
        picker.setFixedHeight(34)

    return picker


def create_date_edit(object_name="DateInput", parent=None):
    picker = QDateEdit(parent)
    picker.setObjectName(object_name)
    picker.setCalendarPopup(True)
    picker.setFixedHeight(34)
    return picker


def create_table(object_name="MissionaryTable", parent=None):
    table = TableWidget(parent)
    table.setObjectName(object_name)
    if FLUENT_AVAILABLE and hasattr(table, "setBorderVisible"):
        table.setBorderVisible(False)
        table.setBorderRadius(0)
    return table


def create_list_widget(object_name="", parent=None):
    widget = FluentListWidget(parent)
    if object_name:
        widget.setObjectName(object_name)
    return widget


def tune_fluent_scrollable(
    widget,
    handle_display_mode=None,
    smooth_mode=None,
):
    if handle_display_mode is None and ScrollBarHandleDisplayMode is not None:
        handle_display_mode = ScrollBarHandleDisplayMode.ON_HOVER
    if smooth_mode is None and SmoothMode is not None:
        smooth_mode = SmoothMode.CONSTANT

    if not FLUENT_AVAILABLE or widget is None:
        return widget

    delegates = []
    for attr in ("scrollDelegate", "scrollDelagate", "delegate"):
        delegate = getattr(widget, attr, None)
        if delegate is not None:
            delegates.append(delegate)

    seen_bars = set()
    for delegate in delegates:
        for bar_name in ("vScrollBar", "hScrollBar"):
            bar = getattr(delegate, bar_name, None)
            if bar is None or id(bar) in seen_bars:
                continue
            seen_bars.add(id(bar))
            if handle_display_mode is not None and hasattr(
                bar, "setHandleDisplayMode"
            ):
                bar.setHandleDisplayMode(handle_display_mode)

        if smooth_mode is not None:
            for engine_name in (
                "verticalSmoothScroll",
                "horizonSmoothScroll",
            ):
                engine = getattr(delegate, engine_name, None)
                if engine is not None and hasattr(engine, "setSmoothMode"):
                    engine.setSmoothMode(smooth_mode)

    if handle_display_mode is not None:
        for bar_name in ("vScrollBar", "hScrollBar"):
            bar = getattr(widget, bar_name, None)
            if bar is None or id(bar) in seen_bars:
                continue
            if hasattr(bar, "setHandleDisplayMode"):
                bar.setHandleDisplayMode(handle_display_mode)

    if smooth_mode is not None:
        if hasattr(widget, "smoothScroll") and hasattr(
            widget.smoothScroll, "setSmoothMode"
        ):
            widget.smoothScroll.setSmoothMode(smooth_mode)
        elif hasattr(widget, "setSmoothMode"):
            try:
                widget.setSmoothMode(smooth_mode)
            except TypeError:
                for orientation in (Qt.Vertical, Qt.Horizontal):
                    try:
                        widget.setSmoothMode(smooth_mode, orientation)
                    except TypeError:
                        continue

    return widget


def create_scroll_area(
    object_name="",
    parent=None,
    transparent=True,
    single_direction=False,
    orientation=Qt.Vertical,
):
    if single_direction and FLUENT_AVAILABLE and SingleDirectionScrollArea is not None:
        scroll = SingleDirectionScrollArea(parent, orientation)
    else:
        scroll = SmoothScrollArea(parent)
    if object_name:
        scroll.setObjectName(object_name)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    if transparent and hasattr(scroll, "enableTransparentBackground"):
        scroll.enableTransparentBackground()
    return scroll


def create_card(object_name="FluentCard", parent=None, simple=True):
    card_class = SimpleCardWidget if simple else CardWidget
    card = card_class(parent)
    card.setObjectName(object_name)
    return card


def create_header_card(title="", object_name="FluentCard", parent=None):
    if FLUENT_AVAILABLE:
        card = HeaderCardWidget(title, parent)
    else:
        card = QFrame(parent)
    card.setObjectName(object_name)
    return card


def create_slider(orientation=Qt.Horizontal, parent=None):
    return FluentSlider(orientation, parent)


def create_tab_widget(parent=None):
    return FluentTabWidget(parent)


def create_pivot(parent=None):
    return FluentPivot(parent) if FLUENT_AVAILABLE and FluentPivot else None


def create_menu(title="", parent=None):
    return RoundMenu(title, parent) if FLUENT_AVAILABLE else QMenu(title, parent)


def fluent_icon(name, fallback=None):
    if not FLUENT_AVAILABLE or FluentIcon is None:
        return fallback
    return getattr(FluentIcon, name, fallback)


def show_message(parent, title, content, kind="information", buttons=None):
    if FLUENT_AVAILABLE and MessageBox is not None and parent is not None:
        box = MessageBox(title, content, parent)
        if kind in {"information", "warning"} and buttons is None:
            box.hideCancelButton()
        if buttons == "yes_no":
            box.yesButton.setText("Yes")
            box.cancelButton.setText("No")
        return box.exec()

    if kind == "critical":
        return QMessageBox.critical(parent, title, content)
    if kind == "warning":
        return QMessageBox.warning(parent, title, content)
    if kind == "question" or buttons == "yes_no":
        return QMessageBox.question(
            parent,
            title,
            content,
            QMessageBox.Yes | QMessageBox.No,
        )
    return QMessageBox.information(parent, title, content)
