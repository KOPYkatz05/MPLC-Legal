from PySide6.QtCore import QDate, QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainterPath, QPalette, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QScrollBar,
    QSlider,
    QTableWidget,
    QTextEdit,
    QTabWidget,
    QVBoxLayout,
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
        InfoBadge,
        InfoLevel,
        LineEdit as FluentLineEdit,
        ListWidget as FluentListWidget,
        MaskDialogBase,
        MessageBox,
        IndeterminateProgressRing,
        PlainTextEdit as FluentPlainTextEdit,
        Pivot as FluentPivot,
        PillPushButton,
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
        StrongBodyLabel,
        TabWidget as FluentTabWidget,
        TableWidget,
        TextEdit as FluentTextEdit,
        TransparentPushButton,
    )

    FLUENT_AVAILABLE = True
except Exception:
    class _FallbackInfoLevel:
        ERROR = None
        WARNING = None
        ATTENTION = None
        SUCCESS = None

    BodyLabel = QLabel
    CardWidget = QFrame
    EditableComboBox = QComboBox
    FluentComboBox = QComboBox
    FluentDatePicker = QDateEdit
    FluentIcon = None
    InfoBadge = QLabel
    InfoLevel = _FallbackInfoLevel
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
    IndeterminateProgressRing = None
    PillPushButton = QPushButton
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
    StrongBodyLabel = QLabel
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

APP_DIALOG_SHELL_OBJECT_NAME = "AppDialogShell"
APP_DIALOG_SURFACE_OBJECT_NAME = "AppDialogSurface"
APP_DIALOG_SURFACE_RADIUS = 20
APP_DIALOG_SHELL_MARGINS = (24, 24, 24, 24)
APP_DIALOG_MASK_COLOR = QColor(0, 0, 0, 76)
APP_DIALOG_SHADOW = (60, (0, 10), QColor(0, 0, 0, 50))
APP_DIALOG_SURFACE_SHADOW = (32, 0, 16, QColor(0, 0, 0, 42))
MESSAGE_BOX_OBJECT_NAME = "AppMessageBox"


def _set_fixed_height(widget, fixed_height):
    if fixed_height:
        widget.setFixedHeight(fixed_height)
    return widget


def refresh_widget_style(widget):
    if widget is None:
        return
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _make_surface_opaque(widget):
    if widget is None:
        return
    palette = widget.palette()
    app = QApplication.instance()
    if app is not None:
        palette.setColor(
            QPalette.Window,
            app.palette().color(QPalette.Window),
        )
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


class _RoundedSurfaceMask(QObject):
    def __init__(self, widget, radius):
        super().__init__(widget)
        self.widget = widget
        self.radius = radius

    def eventFilter(self, watched, event):
        widget = getattr(self, "widget", None)
        if widget is not None and watched is widget and event.type() in {
            QEvent.Resize,
            QEvent.Show,
        }:
            self.apply()
        return super().eventFilter(watched, event)

    def apply(self):
        rect = self.widget.rect()
        if rect.isEmpty():
            return
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(rect),
            self.radius,
            self.radius,
        )
        self.widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


def _clip_surface_to_rounded_rect(widget, radius=APP_DIALOG_SURFACE_RADIUS):
    if widget is None:
        return
    mask_filter = getattr(widget, "_dialog_surface_mask_filter", None)
    if mask_filter is None:
        mask_filter = _RoundedSurfaceMask(widget, radius)
        widget._dialog_surface_mask_filter = mask_filter
        widget.installEventFilter(mask_filter)
    mask_filter.radius = radius
    mask_filter.apply()


class _DialogSurfaceSizer(QObject):
    def __init__(self, dialog, surface, fixed_width=None, adjust_dialog=True):
        super().__init__(surface)
        self.dialog = dialog
        self.surface = surface
        self.fixed_width = fixed_width
        self.adjust_dialog = adjust_dialog
        self._pending = False

    def eventFilter(self, watched, event):
        surface = getattr(self, "surface", None)
        if surface is not None and watched is surface and event.type() in {
            QEvent.LayoutRequest,
            QEvent.Resize,
            QEvent.Show,
        }:
            self.schedule()
        return super().eventFilter(watched, event)

    def schedule(self):
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self.apply)

    def apply(self):
        self._pending = False
        surface = getattr(self, "surface", None)
        dialog = getattr(self, "dialog", None)
        if surface is None or dialog is None:
            return

        hint = surface.sizeHint()
        if not hint.isValid():
            return

        width = self.fixed_width or hint.width()
        width = max(width, surface.minimumWidth())
        height = max(hint.height(), surface.minimumHeight())

        if width > 0:
            surface.setFixedWidth(width)
        if height > 0:
            surface.setFixedHeight(height)

        if self.adjust_dialog:
            dialog.adjustSize()


def _fit_dialog_surface_to_content(
    dialog,
    surface,
    fixed_width=None,
    adjust_dialog=True,
):
    if dialog is None or surface is None:
        return
    sizer = getattr(surface, "_dialog_surface_sizer", None)
    if sizer is None:
        sizer = _DialogSurfaceSizer(
            dialog,
            surface,
            fixed_width,
            adjust_dialog,
        )
        surface._dialog_surface_sizer = sizer
        surface.installEventFilter(sizer)
    sizer.fixed_width = fixed_width
    sizer.adjust_dialog = adjust_dialog
    sizer.schedule()


def _apply_dialog_mask_color(dialog, color=None):
    if not hasattr(dialog, "setMaskColor"):
        return

    mask_color = color or APP_DIALOG_MASK_COLOR
    if isinstance(mask_color, QColor):
        dialog.setMaskColor(mask_color)
        return

    if isinstance(mask_color, str):
        parsed_color = QColor(mask_color)
        if parsed_color.isValid():
            dialog.setMaskColor(parsed_color)


def _apply_dialog_shadow(dialog, shadow=None):
    if not hasattr(dialog, "setShadowEffect"):
        return

    shadow_config = shadow or APP_DIALOG_SHADOW
    if shadow_config is None:
        return

    if isinstance(shadow_config, tuple):
        dialog.setShadowEffect(*shadow_config)


def _apply_surface_shadow(surface, shadow=None):
    if surface is None:
        return

    shadow_config = shadow or APP_DIALOG_SURFACE_SHADOW
    if shadow_config is None:
        surface.setGraphicsEffect(None)
        return

    blur_radius, x_offset, y_offset, color = shadow_config
    effect = QGraphicsDropShadowEffect(surface)
    effect.setBlurRadius(blur_radius)
    effect.setOffset(x_offset, y_offset)
    effect.setColor(color)
    surface.setGraphicsEffect(effect)


def _style_dialog_button(button, variant):
    if button is None:
        return
    button.setObjectName(
        BUTTON_OBJECT_NAMES.get(variant, BUTTON_OBJECT_NAMES["secondary"])
    )
    _set_fixed_height(button, 32)
    refresh_widget_style(button)


def _exec_fallback_message_box(parent, title, content, kind, buttons):
    box = QMessageBox(parent)
    box.setObjectName(MESSAGE_BOX_OBJECT_NAME)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(content)
    box.setModal(True)

    icon_by_kind = {
        "critical": QMessageBox.Critical,
        "warning": QMessageBox.Warning,
        "question": QMessageBox.Question,
        "information": QMessageBox.Information,
    }
    box.setIcon(icon_by_kind.get(kind, QMessageBox.Information))

    if kind == "question" or buttons == "yes_no":
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        _style_dialog_button(box.button(QMessageBox.Yes), "primary")
        _style_dialog_button(box.button(QMessageBox.No), "secondary")
    else:
        box.setStandardButtons(QMessageBox.Ok)
        box.setDefaultButton(QMessageBox.Ok)
        _style_dialog_button(box.button(QMessageBox.Ok), "primary")

    refresh_widget_style(box)
    return box.exec()


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


def setup_dialog_shell(
    dialog,
    *,
    surface_width=None,
    surface_min_width=None,
    surface_min_height=None,
    fit_to_content=True,
    shell_object_name=APP_DIALOG_SHELL_OBJECT_NAME,
    surface_object_name=APP_DIALOG_SURFACE_OBJECT_NAME,
    shell_margins=APP_DIALOG_SHELL_MARGINS,
    use_masked_shell=True,
    mask_color=None,
    transparent_masked_shell=None,
    shadow=None,
):
    _ = transparent_masked_shell
    has_fluent_shell = hasattr(dialog, "_hBoxLayout") and hasattr(dialog, "widget")
    using_fluent_shell = use_masked_shell and has_fluent_shell
    surface_alignment = Qt.AlignCenter

    if shell_object_name:
        dialog.setObjectName(shell_object_name)

    if using_fluent_shell:
        _apply_dialog_mask_color(dialog, mask_color)
        _apply_dialog_shadow(dialog, shadow)
        dialog._hBoxLayout.setContentsMargins(*shell_margins)
        dialog._hBoxLayout.removeWidget(dialog.widget)
        dialog._hBoxLayout.addWidget(
            dialog.widget,
            1,
            surface_alignment,
        )

        surface = dialog.widget
        _make_surface_opaque(surface)
    else:
        dialog.setModal(True)
        dialog.setAttribute(Qt.WA_StyledBackground, True)
        dialog.setStyleSheet(
            dialog.styleSheet()
        )
        root = QVBoxLayout()
        root.setContentsMargins(*shell_margins)
        root.setSpacing(0)
        dialog.setLayout(root)

        surface = QFrame(dialog)
        root.addWidget(surface, 1, surface_alignment)
        _apply_surface_shadow(surface, shadow)

    if surface_object_name:
        surface.setObjectName(surface_object_name)
    surface.setAttribute(Qt.WA_StyledBackground, True)

    if surface_width is not None:
        surface.setFixedWidth(surface_width)
    if surface_min_width is not None:
        surface.setMinimumWidth(surface_min_width)
    if surface_min_height is not None:
        surface.setMinimumHeight(surface_min_height)

    if fit_to_content:
        _fit_dialog_surface_to_content(
            dialog,
            surface,
            surface_width,
            adjust_dialog=not using_fluent_shell,
        )
    _clip_surface_to_rounded_rect(surface)
    refresh_widget_style(dialog)
    refresh_widget_style(surface)
    return surface


class FluentLoadingDialog(MaskDialogBase):
    def __init__(self, parent=None, title="Please wait", message="Reading document..."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)

        self.surface = setup_dialog_shell(
            self,
            surface_width=420,
            surface_min_width=360,
            surface_min_height=220,
            shell_object_name="FluentLoadingDialog",
            surface_object_name="FluentLoadingSurface",
            use_masked_shell=True,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignCenter)
        self.surface.setLayout(layout)

        self._indicator = self._create_indicator(self.surface)
        if self._indicator is not None:
            layout.addWidget(self._indicator, alignment=Qt.AlignCenter)

        self._title_label = SubtitleLabel(title)
        self._title_label.setObjectName("FluentLoadingTitle")
        self._title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title_label)

        self._message_label = BodyLabel(message or "")
        self._message_label.setObjectName("FluentLoadingMessage")
        self._message_label.setAlignment(Qt.AlignCenter)
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

    @staticmethod
    def _create_indicator(parent=None):
        if FLUENT_AVAILABLE and IndeterminateProgressRing is not None:
            indicator = IndeterminateProgressRing(parent)
            indicator.setFixedSize(56, 56)
            if hasattr(indicator, "setStrokeWidth"):
                indicator.setStrokeWidth(4)
            return indicator

        indicator = QProgressBar(parent)
        indicator.setObjectName("FluentLoadingProgress")
        indicator.setRange(0, 0)
        indicator.setTextVisible(False)
        indicator.setFixedHeight(8)
        return indicator

    def set_message(self, message):
        self._message_label.setText(message or "")

    def show_busy(self, message=None):
        if message is not None:
            self.set_message(message)
        self.show()
        self.raise_()
        self.activateWindow()
        return self

    def hide_busy(self):
        self.hide()


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

    if not FLUENT_AVAILABLE:
        button.setObjectName(
            BUTTON_OBJECT_NAMES.get(variant, BUTTON_OBJECT_NAMES["secondary"])
        )
    return _set_fixed_height(button, fixed_height)


def create_pill_button(text, parent=None, icon=None):
    if FLUENT_AVAILABLE and PillPushButton is not None:
        if icon is not None:
            button = PillPushButton(icon, text, parent)
        else:
            button = PillPushButton(parent)
            button.setText(text)
    else:
        button = create_button(text, "subtle", fixed_height=30, parent=parent, icon=icon)
    return button


def create_line_edit(placeholder="", object_name="SearchInput", parent=None):
    line_edit = FluentLineEdit(parent)
    if object_name and not FLUENT_AVAILABLE:
        line_edit.setObjectName(object_name)
    line_edit.setPlaceholderText(placeholder)
    return _set_fixed_height(line_edit, 34)


def create_search_edit(placeholder="", object_name="SearchInput", parent=None):
    edit = SearchLineEdit(parent)
    if object_name and not FLUENT_AVAILABLE:
        edit.setObjectName(object_name)
    edit.setPlaceholderText(placeholder)
    return _set_fixed_height(edit, 34)


def create_info_badge(value, level=None, parent=None, object_name="InfoBadge"):
    if FLUENT_AVAILABLE and InfoBadge is not None:
        if level is None:
            return InfoBadge(value, parent)
        return InfoBadge(value, parent, level)

    badge = QLabel(str(value), parent)
    if object_name and not FLUENT_AVAILABLE:
        badge.setObjectName(object_name)
    return badge


def create_text_edit(object_name="NotesEditor", parent=None):
    edit = FluentTextEdit(parent)
    if object_name and not FLUENT_AVAILABLE:
        edit.setObjectName(object_name)
    return edit


def create_plain_text_edit(object_name="DocumentNotesEditor", parent=None):
    edit = FluentPlainTextEdit(parent)
    if object_name and not FLUENT_AVAILABLE:
        edit.setObjectName(object_name)
    return edit


def create_combo_box(object_name="FilterCombo", parent=None, editable=False):
    combo_class = EditableComboBox if editable else FluentComboBox
    combo = combo_class(parent)
    if object_name and not FLUENT_AVAILABLE:
        combo.setObjectName(object_name)
    _set_fixed_height(combo, 34)
    return _patch_fluent_combo_data_api(combo)


def create_date_picker(object_name="DateInput", parent=None):
    picker = FluentDatePicker(parent)
    if object_name and not FLUENT_AVAILABLE:
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
    if object_name and not FLUENT_AVAILABLE:
        table.setObjectName(object_name)
    if FLUENT_AVAILABLE and hasattr(table, "setBorderVisible"):
        table.setBorderVisible(False)
        table.setBorderRadius(0)
    return table


def create_list_widget(object_name="", parent=None):
    widget = FluentListWidget(parent)
    if object_name and not FLUENT_AVAILABLE:
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
        if not FLUENT_AVAILABLE:
            scroll.setObjectName(object_name)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    if transparent and hasattr(scroll, "enableTransparentBackground"):
        scroll.enableTransparentBackground()
    return scroll


def create_card(object_name="FluentCard", parent=None, simple=True):
    card_class = SimpleCardWidget if simple else CardWidget
    card = card_class(parent)
    if object_name and not FLUENT_AVAILABLE:
        card.setObjectName(object_name)
    return card


def create_header_card(title="", object_name="FluentCard", parent=None):
    if FLUENT_AVAILABLE:
        card = HeaderCardWidget(title, parent)
    else:
        card = QFrame(parent)
    if object_name and not FLUENT_AVAILABLE:
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
        box.setObjectName(MESSAGE_BOX_OBJECT_NAME)
        if kind in {"information", "warning"} and buttons is None:
            box.hideCancelButton()
        if buttons == "yes_no":
            box.yesButton.setText("Yes")
            box.cancelButton.setText("No")
            _style_dialog_button(box.yesButton, "primary")
            _style_dialog_button(box.cancelButton, "secondary")
        elif hasattr(box, "yesButton"):
            _style_dialog_button(box.yesButton, "primary")
        refresh_widget_style(box)
        return box.exec()

    return _exec_fallback_message_box(parent, title, content, kind, buttons)
