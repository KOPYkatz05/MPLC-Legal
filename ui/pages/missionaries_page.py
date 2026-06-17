from dataclasses import dataclass
from datetime import date, datetime

from PySide6.QtCore import QEvent, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from services.missionary_service import (
    MissionaryService,
    missionary_display_id,
)
from services.missionary_group_service import MissionaryGroupService

from services.export_service import ExportService
from services.settings_service import SettingsService
from ui.foundation import (
    FilterBar,
    DialogFooter,
    FLUENT_AVAILABLE,
    MaskDialogBase,
    PageHeader,
    configure_data_table,
    create_button,
    create_combo_box,
    create_list_widget,
    create_line_edit,
    create_menu,
    create_plain_text_edit,
    create_search_edit,
    create_table,
    divider,
    fluent_icon,
    setup_dialog_shell,
    show_message,
)

from ui.dialogs.add_missionary_dialog import (
    AddMissionaryDialog,
)

from utils.constants import WORKFLOW_STAGES

from utils.logger import logger


@dataclass(frozen=True)
class MissionaryColumn:
    key: str
    label: str
    getter: object
    default_width: int
    default_visible: bool = False
    required: bool = False
    copyable: bool = True


def _format_date(value):
    if not value:
        return ""

    try:
        return value.strftime("%d/%m/%Y")
    except AttributeError:
        return str(value)


def _text_attr(field_name):
    return lambda missionary: getattr(missionary, field_name, None) or ""


MISSIONARY_COLUMNS = [
    MissionaryColumn(
        "missionary_id",
        "Missionary ID",
        missionary_display_id,
        120,
        default_visible=True,
        required=True,
    ),
    MissionaryColumn(
        "full_name",
        "Full Name",
        _text_attr("full_name"),
        260,
        default_visible=True,
        required=True,
    ),
    MissionaryColumn(
        "preferred_name",
        "Preferred Name",
        _text_attr("preferred_name"),
        170,
    ),
    MissionaryColumn(
        "nationality",
        "Nationality",
        _text_attr("nationality"),
        120,
        default_visible=True,
    ),
    MissionaryColumn(
        "passport_number",
        "Passport Number",
        _text_attr("passport_number"),
        155,
        default_visible=True,
    ),
    MissionaryColumn(
        "carnet_number",
        "Carnet Number",
        _text_attr("carnet_number"),
        155,
    ),
    MissionaryColumn(
        "date_of_birth",
        "Date of Birth",
        lambda missionary: _format_date(missionary.date_of_birth),
        145,
    ),
    MissionaryColumn(
        "current_stage",
        "Current Stage",
        _text_attr("current_stage"),
        175,
        default_visible=True,
    ),
    MissionaryColumn(
        "tramite_usuario",
        "Tramite Usuario",
        _text_attr("tramite_usuario"),
        155,
    ),
    MissionaryColumn(
        "tramite_contrasena",
        "Tramite Contrasena",
        _text_attr("tramite_contrasena"),
        165,
    ),
    MissionaryColumn(
        "arrival_date",
        "Arrival Date",
        lambda missionary: _format_date(missionary.arrival_date),
        145,
    ),
    MissionaryColumn(
        "visa_expiration",
        "Visa Expiration",
        lambda missionary: _format_date(missionary.visa_expiration),
        155,
    ),
    MissionaryColumn(
        "passport_expiration",
        "Passport Expiration",
        lambda missionary: _format_date(missionary.passport_expiration),
        170,
    ),
    MissionaryColumn(
        "residency_expiration",
        "Residency Expiration",
        lambda missionary: _format_date(missionary.residency_expiration),
        175,
    ),
    MissionaryColumn(
        "prorroga_expiration",
        "Prorroga Expiration",
        lambda missionary: _format_date(missionary.prorroga_expiration),
        170,
    ),
    MissionaryColumn(
        "carnet_issue_date",
        "Carnet Issue Date",
        lambda missionary: _format_date(missionary.carnet_issue_date),
        165,
    ),
    MissionaryColumn(
        "cancelacion_date",
        "Cancelacion Date",
        lambda missionary: _format_date(missionary.cancelacion_date),
        165,
    ),
    MissionaryColumn(
        "interpol_appointment_date",
        "Interpol Appointment Date",
        lambda missionary: _format_date(
            missionary.interpol_appointment_date
        ),
        205,
    ),
    MissionaryColumn(
        "biometric_appointment_date",
        "Biometric Appointment Date",
        lambda missionary: _format_date(
            missionary.biometric_appointment_date
        ),
        210,
    ),
    MissionaryColumn(
        "pickup_appointment_date",
        "Pickup Appointment Date",
        lambda missionary: _format_date(missionary.pickup_appointment_date),
        205,
    ),
    MissionaryColumn(
        "notes",
        "Notes",
        _text_attr("notes"),
        280,
    ),
]

COLUMN_BY_KEY = {
    column.key: column
    for column in MISSIONARY_COLUMNS
}

DEFAULT_COLUMN_KEYS = [
    column.key
    for column in MISSIONARY_COLUMNS
    if column.default_visible
]

REQUIRED_COLUMN_KEYS = [
    column.key
    for column in MISSIONARY_COLUMNS
    if column.required
]

SORT_VALUE_ROLE = Qt.UserRole + 1
MIN_TABLE_COLUMN_WIDTH = 64
DATE_COLUMN_KEYS = {
    "date_of_birth",
    "arrival_date",
    "visa_expiration",
    "passport_expiration",
    "residency_expiration",
    "prorroga_expiration",
    "carnet_issue_date",
    "cancelacion_date",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
}
GROUP_EDIT_ACTION = "__edit_selected_group__"
COPY_ICON_NAMES = ("COPY", "DUPLICATE", "DOCUMENT_COPY")
CHECK_ICON_NAMES = ("ACCEPT", "CHECKBOX", "CHECK_MARK", "COMPLETED")
EDIT_ICON_NAMES = ("EDIT", "EDIT_SOLID", "PENCIL")


def _date_sort_value(value):
    if not value:
        return ""

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date().isoformat()
        except ValueError:
            continue

    return str(value)


def _sort_value_for_column(column, missionary, display_text):
    if column.key in DATE_COLUMN_KEYS:
        return _date_sort_value(getattr(missionary, column.key, None))

    return display_text or ""


def _fallback_copy_icon():
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor("#52525B"), 1.6)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(6, 3, 8, 10), 2, 2)
    painter.drawRoundedRect(QRectF(3, 6, 8, 10), 2, 2)
    painter.end()

    return QIcon(pixmap)


def _fallback_check_icon():
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor("#059669"), 2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(4, 9, 8, 13)
    painter.drawLine(8, 13, 15, 5)
    painter.end()

    return QIcon(pixmap)


def _fallback_edit_icon():
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor("#52525B"), 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(5, 13, 13, 5)
    painter.drawLine(12, 4, 14, 6)
    painter.drawLine(4, 14, 6, 14)
    painter.drawLine(4, 14, 5, 12)
    painter.end()

    return QIcon(pixmap)


def _qicon_from_fluent(names, fallback):
    for name in names:
        icon = fluent_icon(name)

        if isinstance(icon, QIcon):
            return icon

        if hasattr(icon, "icon"):
            try:
                return icon.icon()
            except Exception:
                continue

    return fallback


class MissionaryTableItem(QTableWidgetItem):
    def __lt__(self, other):
        left = self.data(SORT_VALUE_ROLE) or ""
        right = other.data(SORT_VALUE_ROLE) or ""

        return str(left).casefold() < str(right).casefold()


class EditMissionaryColumnsDialog(MaskDialogBase):
    def __init__(
        self,
        columns,
        selected_keys,
        parent=None,
    ):
        fluent_parent = parent.window() if parent is not None else None
        self._use_fluent_dialog = (
            FLUENT_AVAILABLE and fluent_parent is not None
        )

        if self._use_fluent_dialog:
            super().__init__(fluent_parent)
        else:
            QDialog.__init__(self, parent)

        self.columns = columns
        self.selected_keys = list(selected_keys)
        self._updating_required = False

        self.setWindowTitle("Edit Columns")
        self.surface = setup_dialog_shell(
            self,
            surface_width=520,
            surface_min_height=560,
        )

        self.setup_ui()
        self._load_items(self.selected_keys)

    def _onDone(self, code):
        if self._use_fluent_dialog:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.surface.setLayout(root)

        header = PageHeader(
            "Edit Columns",
            "Choose the fields shown in the missionaries table.",
        )

        root.addWidget(header)

        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(14)
        body.setLayout(body_layout)

        hint = QLabel(
            "Checked columns are visible. Use Up and Down to set the display order."
        )
        hint.setObjectName("MutedText")
        hint.setWordWrap(True)
        body_layout.addWidget(hint)

        self.list_widget = create_list_widget(
            "MissionaryColumnList"
        )
        self.list_widget.setObjectName("MissionaryColumnList")
        self.list_widget.itemChanged.connect(
            self._keep_required_checked
        )
        body_layout.addWidget(self.list_widget, stretch=1)

        order_row = QHBoxLayout()
        order_row.setContentsMargins(0, 0, 0, 0)
        order_row.setSpacing(8)

        self.up_button = create_button(
            "Up",
            "secondary",
        )
        self.down_button = create_button(
            "Down",
            "secondary",
        )
        self.reset_button = create_button(
            "Reset to Default",
            "subtle",
        )

        self.up_button.clicked.connect(
            lambda: self._move_selected(-1)
        )
        self.down_button.clicked.connect(
            lambda: self._move_selected(1)
        )
        self.reset_button.clicked.connect(
            self._reset_to_default
        )

        order_row.addWidget(self.up_button)
        order_row.addWidget(self.down_button)
        order_row.addStretch()
        order_row.addWidget(self.reset_button)
        body_layout.addLayout(order_row)

        root.addWidget(body, stretch=1)

        footer = DialogFooter()
        self.cancel_button = create_button(
            "Cancel",
            "secondary",
        )
        self.save_button = create_button(
            "Save",
            "primary",
        )

        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.accept)

        footer.add_action(self.cancel_button)
        footer.add_action(self.save_button)
        root.addWidget(footer)

    def selected_column_keys(self):
        keys = []

        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)

            if item.checkState() == Qt.Checked:
                key = item.data(Qt.UserRole)

                if key not in keys:
                    keys.append(key)

        for required_key in REQUIRED_COLUMN_KEYS:
            if required_key not in keys:
                keys.insert(0, required_key)

        return keys

    def _load_items(self, selected_keys):
        self.list_widget.clear()

        ordered_keys = []

        for key in selected_keys:
            if key in COLUMN_BY_KEY and key not in ordered_keys:
                ordered_keys.append(key)

        for column in self.columns:
            if column.key not in ordered_keys:
                ordered_keys.append(column.key)

        for key in ordered_keys:
            column = COLUMN_BY_KEY[key]
            item = QListWidgetItem(column.label)
            item.setData(Qt.UserRole, column.key)
            item.setFlags(
                item.flags()
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsSelectable
                | Qt.ItemIsEnabled
            )
            item.setCheckState(
                Qt.Checked
                if column.key in selected_keys or column.required
                else Qt.Unchecked
            )

            if column.required:
                item.setToolTip(
                    "Required for row identity."
                )

            self.list_widget.addItem(item)

    def _keep_required_checked(self, item):
        if self._updating_required:
            return

        key = item.data(Qt.UserRole)

        if (
            key in REQUIRED_COLUMN_KEYS
            and item.checkState() != Qt.Checked
        ):
            self._updating_required = True
            item.setCheckState(Qt.Checked)
            self._updating_required = False

    def _move_selected(self, delta):
        current_row = self.list_widget.currentRow()

        if current_row < 0:
            return

        new_row = current_row + delta

        if new_row < 0 or new_row >= self.list_widget.count():
            return

        item = self.list_widget.takeItem(current_row)
        self.list_widget.insertItem(new_row, item)
        self.list_widget.setCurrentRow(new_row)

    def _reset_to_default(self):
        self._load_items(DEFAULT_COLUMN_KEYS)


class CreateMissionaryGroupDialog(MaskDialogBase):
    def __init__(self, group_service, missionaries, parent=None, group=None):
        fluent_parent = parent.window() if parent is not None else None
        self._use_fluent_dialog = (
            FLUENT_AVAILABLE and fluent_parent is not None
        )

        if self._use_fluent_dialog:
            super().__init__(fluent_parent)
        else:
            QDialog.__init__(self, parent)

        self.group_service = group_service
        self.missionaries = list(missionaries)
        self.group = group or {}
        self.saved_group = None
        self._is_editing = bool(self.group)

        self.setWindowTitle("Edit Group" if self._is_editing else "Create Group")
        self.surface = setup_dialog_shell(
            self,
            surface_width=560,
            surface_min_height=620,
        )
        self.setup_ui()

    def _onDone(self, code):
        if self._use_fluent_dialog:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def done(self, code):
        if self._use_fluent_dialog:
            super().done(code)
        else:
            QDialog.done(self, code)

    def setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.surface.setLayout(root)

        root.addWidget(
            PageHeader(
                "Edit Group" if self._is_editing else "Create Group",
                (
                    "Update who belongs to this reusable missionary group."
                    if self._is_editing
                    else "Save a reusable missionary group for filtering and shared tasks."
                ),
            )
        )

        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(12)
        body.setLayout(body_layout)

        self.name_input = create_line_edit("Group name")
        self.name_input.setText(self.group.get("name", ""))
        body_layout.addWidget(self._field("Name", self.name_input))

        self.description_input = create_plain_text_edit()
        self.description_input.setPlaceholderText("Optional description")
        self.description_input.setFixedHeight(76)
        self.description_input.setPlainText(self.group.get("description", ""))
        body_layout.addWidget(self._field("Description", self.description_input))

        self.search_input = create_search_edit("Search missionaries")
        self.search_input.textChanged.connect(self._filter_items)
        body_layout.addWidget(self.search_input)

        self.member_list = create_list_widget("MissionaryGroupMemberList")
        self.member_list.setMinimumHeight(260)
        body_layout.addWidget(self.member_list, stretch=1)
        self._load_members()

        root.addWidget(body, stretch=1)

        footer = DialogFooter()
        cancel_btn = create_button("Cancel", "secondary")
        cancel_btn.clicked.connect(self.reject)
        footer.add_action(cancel_btn)
        save_btn = create_button("Save", "primary")
        save_btn.clicked.connect(self._save)
        footer.add_action(save_btn)
        root.addWidget(footer)

    def _field(self, label_text, control):
        wrapper = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        wrapper.setLayout(layout)
        label = QLabel(label_text)
        label.setObjectName("OfficeWorkFieldLabel")
        layout.addWidget(label)
        layout.addWidget(control)
        return wrapper

    def _load_members(self):
        self.member_list.clear()
        selected_ids = set(self.group.get("missionary_ids", []))
        for missionary in self.missionaries:
            item = QListWidgetItem(missionary.full_name or "")
            item.setData(Qt.UserRole, missionary.id)
            item.setFlags(
                item.flags()
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsSelectable
                | Qt.ItemIsEnabled
            )
            item.setCheckState(
                Qt.Checked if missionary.id in selected_ids else Qt.Unchecked
            )
            self.member_list.addItem(item)

    def _filter_items(self, text):
        needle = text.strip().casefold()
        for index in range(self.member_list.count()):
            item = self.member_list.item(index)
            item.setHidden(needle not in item.text().casefold())

    def selected_missionary_ids(self):
        ids = []
        for index in range(self.member_list.count()):
            item = self.member_list.item(index)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _save(self):
        name = self.name_input.text().strip()
        if not name:
            show_message(
                self,
                "Group Name Required",
                "Enter a group name before saving.",
                kind="warning",
            )
            return

        payload = {
            "name": name,
            "description": self.description_input.toPlainText().strip(),
            "missionary_ids": self.selected_missionary_ids(),
        }
        if self._is_editing:
            self.saved_group = self.group_service.update_group(
                self.group["id"],
                **payload,
            )
        else:
            self.saved_group = self.group_service.create_group(**payload)
        self.accept()


class MissionariesPage(QWidget):
    def __init__(
        self,
        main_window
    ):
        super().__init__()

        self.setObjectName("MissionariesPage")

        self.main_window = main_window

        self.settings_service = (
            getattr(main_window, "settings_service", None)
            or SettingsService()
        )

        self.missionary_service = (
            MissionaryService()
        )
        self.group_service = MissionaryGroupService()

        self.export_service = ExportService()

        self._all_missionaries = []
        self._groups_by_id = {}
        self._group_members_by_id = {}
        self._last_group_filter_data = None
        self._hovered_cell = None
        self._applying_column_widths = False
        self._visible_column_keys = (
            self._load_visible_column_keys()
        )

        logger.info("Initialized MissionariesPage")

        self.setup_ui()

        self.add_button.clicked.connect(
            self.open_add_dialog
        )

        self.table.cellDoubleClicked.connect(
            self.open_missionary_detail
        )

        self.table.cellEntered.connect(
            self._set_hovered_cell
        )

        self.search_input.textChanged.connect(
            self._apply_filters
        )

        self.stage_filter.currentIndexChanged.connect(
            self._apply_filters
        )

        self.nationality_filter.currentIndexChanged.connect(
            self._apply_filters
        )

        self.group_filter.currentIndexChanged.connect(
            self._group_filter_changed
        )

        self.create_group_button.clicked.connect(
            self._create_group
        )

        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        self.add_button = create_button(
            "+ Add Missionary",
            "primary",
        )

        self.export_button = create_button(
            "Export to Excel",
            "secondary",
        )

        self.export_button.clicked.connect(
            self._export_excel
        )

        self.edit_columns_button = create_button(
            "Edit Columns",
            "secondary",
        )

        self.edit_columns_button.clicked.connect(
            self._edit_columns
        )

        self.auto_widths_button = create_button(
            "Auto Fit Widths",
            "secondary",
        )

        self.auto_widths_button.clicked.connect(
            self._auto_fit_column_widths
        )

        header = PageHeader(
            "Missionaries",
            "Track legal workflow status and documents.",
            [
                self.edit_columns_button,
                self.auto_widths_button,
                self.export_button,
                self.add_button,
            ],
        )

        outer.addWidget(header)

        outer.addWidget(divider())

        # ==========================================
        # Search + filter bar
        # ==========================================

        filter_bar = FilterBar()

        self.search_input = create_line_edit(
            "Search by ID or name..."
        )

        self.search_input.setMaximumWidth(280)

        self.stage_filter = create_combo_box()

        self.stage_filter.addItem("All Stages", None)

        for stage in WORKFLOW_STAGES:
            self.stage_filter.addItem(stage, stage)

        self.nationality_filter = create_combo_box()

        self.nationality_filter.setMaximumWidth(180)

        self.nationality_filter.addItem(
            "All Nationalities", None
        )

        self.group_filter = create_combo_box()

        self.group_filter.addItem("All Groups", None)
        self._edit_group_icon = _qicon_from_fluent(
            EDIT_ICON_NAMES,
            _fallback_edit_icon(),
        )

        self.create_group_button = create_button(
            "Create Group",
            "secondary",
        )

        self.batch_button = create_button(
            "Batch Actions",
            "secondary",
        )

        self.batch_button.clicked.connect(
            self._batch_actions
        )

        self.result_label = QLabel("")

        self.result_label.setObjectName(
            "ResultLabel"
        )

        filter_bar.add_filter(self.search_input)
        filter_bar.add_filter(self.stage_filter)
        filter_bar.add_filter(
            self.nationality_filter
        )
        filter_bar.add_filter(self.group_filter)
        filter_bar.add_spacer()
        filter_bar.add_filter(self.create_group_button)
        filter_bar.add_filter(self.batch_button)
        filter_bar.add_filter(self.result_label)

        outer.addWidget(filter_bar)

        outer.addWidget(divider())

        # ==========================================
        # Table
        # ==========================================

        self.table = create_table()
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)

        self._configure_table_columns()
        self._create_copy_button()
        self.table.horizontalHeader().sectionResized.connect(
            self._save_column_widths
        )
        self.table.horizontalHeader().sectionResized.connect(
            lambda *args: self._position_copy_button()
        )
        self.table.verticalScrollBar().valueChanged.connect(
            lambda value: self._position_copy_button()
        )
        self.table.horizontalScrollBar().valueChanged.connect(
            lambda value: self._position_copy_button()
        )

        outer.addWidget(self.table, stretch=1)

    # ==========================================
    # COLUMN SETTINGS
    # ==========================================

    def _load_visible_column_keys(self):
        saved_keys = (
            self.settings_service
            .get_missionaries_table_columns(
                DEFAULT_COLUMN_KEYS
            )
        )

        keys = []

        for key in saved_keys:
            if key in COLUMN_BY_KEY and key not in keys:
                keys.append(key)

        if not keys:
            keys = list(DEFAULT_COLUMN_KEYS)

        for required_key in reversed(REQUIRED_COLUMN_KEYS):
            if required_key not in keys:
                keys.insert(0, required_key)

        return keys

    def _save_visible_column_keys(self):
        self.settings_service.set_missionaries_table_columns(
            self._visible_column_keys
        )

    def _visible_columns(self):
        return [
            COLUMN_BY_KEY[key]
            for key in self._visible_column_keys
            if key in COLUMN_BY_KEY
        ]

    def _configure_table_columns(self):
        self._applying_column_widths = True
        columns = self._visible_columns()

        try:
            self.table.setColumnCount(len(columns))
            self.table.setHorizontalHeaderLabels([
                column.label
                for column in columns
            ])

            configure_data_table(
                self.table,
                {
                    index: QHeaderView.Interactive
                    for index, column in enumerate(columns)
                },
                selection_mode=QAbstractItemView.ExtendedSelection,
                sorting=True,
            )

            header = self.table.horizontalHeader()
            header.setMinimumSectionSize(72)
            header.setStretchLastSection(False)
            self.table.verticalHeader().setSectionResizeMode(
                QHeaderView.Fixed
            )
            self.table.verticalHeader().setDefaultSectionSize(40)

        finally:
            self._applying_column_widths = False

        self._apply_column_widths()

    def _create_copy_button(self):
        self.copy_button = QPushButton(
            self.table.viewport(),
        )
        self.copy_button.setObjectName(
            "MissionaryCellCopyButton"
        )
        self._copy_icon = _qicon_from_fluent(
            COPY_ICON_NAMES,
            _fallback_copy_icon(),
        )
        self._check_icon = _qicon_from_fluent(
            CHECK_ICON_NAMES,
            _fallback_check_icon(),
        )
        self.copy_button.setIcon(self._copy_icon)
        self.copy_button.setFixedSize(30, 26)
        self.copy_button.setCursor(Qt.PointingHandCursor)
        self.copy_button.setToolTip("Copy")
        self.copy_button.hide()
        self.copy_button.clicked.connect(
            self._copy_hovered_cell
        )

    def _apply_column_widths(self):
        saved_widths = (
            self.settings_service
            .get_missionaries_table_column_widths()
        )

        columns = self._visible_columns()
        default_widths = {
            column.key: column.default_width
            for column in columns
        }

        widths = {
            column.key: saved_widths.get(
                column.key,
                default_widths[column.key],
            )
            for column in columns
        }

        widths = self._balanced_default_widths(widths)

        self._applying_column_widths = True

        try:
            for index, column in enumerate(columns):
                self.table.setColumnWidth(
                    index,
                    max(
                        MIN_TABLE_COLUMN_WIDTH,
                        int(widths[column.key]),
                    ),
                )

        finally:
            self._applying_column_widths = False

    def _balanced_default_widths(self, widths):
        available = self.table.viewport().width()

        if available <= 0:
            available = self.table.width()

        if available <= 0:
            return widths

        columns = list(widths)

        if not columns:
            return widths

        minimum_total = MIN_TABLE_COLUMN_WIDTH * len(columns)

        if available <= minimum_total:
            return {
                key: MIN_TABLE_COLUMN_WIDTH
                for key in columns
            }

        preferred_total = sum(
            max(MIN_TABLE_COLUMN_WIDTH, int(width))
            for width in widths.values()
        )

        if preferred_total <= 0:
            return widths

        scale = available / preferred_total
        balanced = {}
        used = 0

        for key in columns[:-1]:
            width = max(
                MIN_TABLE_COLUMN_WIDTH,
                int(widths[key] * scale),
            )
            balanced[key] = width
            used += width

        last_key = columns[-1]
        balanced[last_key] = max(
            MIN_TABLE_COLUMN_WIDTH,
            available - used,
        )

        return balanced

    def _auto_fit_column_widths(self):
        widths = {
            column.key: column.default_width
            for column in self._visible_columns()
        }

        widths = self._balanced_default_widths(widths)

        self.settings_service.set_missionaries_table_column_widths(
            widths
        )

        self._apply_column_widths()

    def _save_column_widths(self, logical_index, old_size, new_size):
        _ = old_size

        if self._applying_column_widths:
            return

        columns = self._visible_columns()

        if logical_index < 0 or logical_index >= len(columns):
            return

        if new_size <= 0:
            return

        widths = (
            self.settings_service
            .get_missionaries_table_column_widths()
        )

        for index, column in enumerate(columns):
            widths[column.key] = self.table.columnWidth(index)

        self.settings_service.set_missionaries_table_column_widths(
            widths
        )

    # ==========================================
    # DATA
    # ==========================================

    def load_data(self):
        try:
            self._all_missionaries = (
                self.missionary_service
                .get_all_missionaries()
            )
            self._refresh_group_filter()

            # Update nationality filter dropdown
            existing = [
                self.nationality_filter.itemText(i)
                for i in range(
                    self.nationality_filter.count()
                )
            ]

            for m in self._all_missionaries:
                nat = (m.nationality or "").strip()

                if nat and nat not in existing:
                    self.nationality_filter.addItem(
                        nat, nat
                    )

                    existing.append(nat)

            self._apply_filters()

            logger.info(
                f"Loaded "
                f"{len(self._all_missionaries)} "
                f"missionaries into table"
            )

        except Exception:
            logger.exception(
                "Failed to load missionaries table"
            )

    def _apply_filters(self):
        search_text = (
            self.search_input.text().strip().lower()
        )

        selected_stage = (
            self.stage_filter.currentData()
        )

        selected_nationality = (
            self.nationality_filter.currentData()
        )

        selected_group = (
            self.group_filter.currentData()
        )

        group_member_ids = set(
            self._group_members_by_id.get(selected_group, [])
        )

        filtered = []

        for m in self._all_missionaries:
            display_id = (
                missionary_display_id(m).lower()
            )

            name = (m.full_name or "").lower()

            preferred = (
                (m.preferred_name or "").lower()
            )

            if search_text and (
                search_text not in display_id
                and search_text not in name
                and search_text not in preferred
            ):
                continue

            if (
                selected_stage
                and m.current_stage != selected_stage
            ):
                continue

            if (
                selected_nationality
                and (m.nationality or "")
                != selected_nationality
            ):
                continue

            if selected_group and m.id not in group_member_ids:
                continue

            filtered.append(m)

        self._populate_table(filtered)

        total = len(self._all_missionaries)

        shown = len(filtered)

        if shown == total:
            self.result_label.setText(
                f"{total} missionaries"
            )

        else:
            self.result_label.setText(
                f"{shown} of {total} missionaries"
            )

    def _populate_table(self, missionaries):
        # Disable sorting while populating to
        # avoid row index issues
        self.table.setSortingEnabled(False)
        self._hovered_cell = None

        if hasattr(self, "copy_button"):
            self.copy_button.hide()

        self.table.clearContents()

        self.table.setRowCount(len(missionaries))
        self.table.verticalHeader().setDefaultSectionSize(40)

        columns = self._visible_columns()

        for row, m in enumerate(missionaries):
            self.table.setRowHeight(row, 40)

            for column_index, column in enumerate(columns):
                text = str(column.getter(m) or "")
                item = self._make_table_item(
                    text,
                    m.id,
                    _sort_value_for_column(column, m, text),
                )

                self.table.setItem(
                    row,
                    column_index,
                    item,
                )

        self.table.setSortingEnabled(True)

    def _make_table_item(self, text, missionary_id, sort_value=None):
        item = MissionaryTableItem(text or "")

        item.setTextAlignment(
            Qt.AlignVCenter | Qt.AlignLeft
        )

        item.setData(
            Qt.UserRole,
            missionary_id,
        )

        item.setData(
            SORT_VALUE_ROLE,
            text if sort_value is None else sort_value,
        )

        return item

    def _refresh_group_filter(self):
        if not hasattr(self, "group_filter"):
            return

        current_group = self.group_filter.currentData()
        if current_group == GROUP_EDIT_ACTION:
            current_group = self._last_group_filter_data
        groups = self.group_service.list_groups()
        self._groups_by_id = {
            group["id"]: group
            for group in groups
        }
        self._group_members_by_id = {
            group["id"]: group.get("missionary_ids", [])
            for group in groups
        }

        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("All Groups", None)
        for group in groups:
            self.group_filter.addItem(
                f"{group['name']} ({group.get('member_count', 0)})",
                group["id"],
            )
        self._add_group_edit_action()
        index = self.group_filter.findData(current_group)
        if index >= 0:
            self.group_filter.setCurrentIndex(index)
        self._last_group_filter_data = self.group_filter.currentData()
        self.group_filter.blockSignals(False)

    def _add_group_edit_action(self):
        if FLUENT_AVAILABLE:
            self.group_filter.addItem(
                "Edit selected group members",
                GROUP_EDIT_ACTION,
                icon=self._edit_group_icon,
            )
        else:
            self.group_filter.addItem(
                self._edit_group_icon,
                "Edit selected group members",
                GROUP_EDIT_ACTION,
            )

    def _group_filter_changed(self, *_args):
        current_group = self.group_filter.currentData()
        if current_group == GROUP_EDIT_ACTION:
            group_id = self._last_group_filter_data
            self._set_combo_data(self.group_filter, group_id)
            if group_id is None:
                show_message(
                    self,
                    "Select Group",
                    "Choose a group before editing its members.",
                    kind="warning",
                )
                return
            QTimer.singleShot(0, lambda: self._edit_group_by_id(group_id))
            return

        self._last_group_filter_data = current_group
        self._apply_filters()

    def _set_combo_data(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    # ==========================================
    # COPY CELL STATE
    # ==========================================

    def eventFilter(self, watched, event):
        if watched is self.table.viewport():
            if event.type() == QEvent.Leave:
                self._hide_copy_button()

            elif event.type() == QEvent.MouseMove:
                index = self.table.indexAt(event.pos())

                if index.isValid():
                    self._set_hovered_cell(
                        index.row(),
                        index.column(),
                    )

                else:
                    self._hide_copy_button()

            elif event.type() in {
                QEvent.Resize,
                QEvent.Wheel,
            }:
                if event.type() == QEvent.Resize:
                    self._apply_column_widths()

                self._position_copy_button()

        return super().eventFilter(watched, event)

    def _set_hovered_cell(self, row, column):
        self._hovered_cell = (row, column)
        self._position_copy_button()

    def _hide_copy_button(self):
        self._hovered_cell = None

        if hasattr(self, "copy_button"):
            self.copy_button.hide()

    def _position_copy_button(self):
        if not hasattr(self, "copy_button"):
            return

        if self._hovered_cell is None:
            self.copy_button.hide()
            return

        row, column = self._hovered_cell
        item = self.table.item(row, column)
        visible_columns = self._visible_columns()

        if (
            not item
            or column >= len(visible_columns)
            or not visible_columns[column].copyable
        ):
            self.copy_button.hide()
            return

        text = item.data(SORT_VALUE_ROLE) or item.text()

        if not text:
            self.copy_button.hide()
            return

        index = self.table.model().index(row, column)
        rect = self.table.visualRect(index)

        if not rect.isValid() or rect.width() <= 0:
            self.copy_button.hide()
            return

        button_width = self.copy_button.width()
        button_height = self.copy_button.height()
        x = max(
            rect.left() + 4,
            rect.right() - button_width - 8,
        )
        y = rect.top() + ((rect.height() - button_height) // 2)

        self.copy_button.setToolTip(
            f"Copy {visible_columns[column].label}"
        )
        self.copy_button.move(x, y)
        self.copy_button.raise_()
        self.copy_button.show()

    def _copy_hovered_cell(self):
        if self._hovered_cell is None:
            return

        row, column = self._hovered_cell
        item = self.table.item(row, column)

        if not item:
            return

        text = item.data(SORT_VALUE_ROLE) or item.text()

        if not text:
            return

        QApplication.clipboard().setText(str(text))

        previous_icon = self.copy_button.icon()
        previous_tooltip = self.copy_button.toolTip()

        self.copy_button.setIcon(self._check_icon)
        self.copy_button.setToolTip("Copied")

        QTimer.singleShot(
            900,
            lambda: self._restore_copy_button(
                previous_icon,
                previous_tooltip,
            ),
        )

    def _restore_copy_button(self, icon, tooltip):
        if not hasattr(self, "copy_button"):
            return

        self.copy_button.setIcon(icon)
        self.copy_button.setToolTip(tooltip)
        self._position_copy_button()

    # ==========================================
    # ACTIONS
    # ==========================================

    def open_add_dialog(self):
        try:
            dialog = AddMissionaryDialog(
                self.main_window
            )

            if dialog.exec():
                logger.info(
                    "Missionary created successfully"
                )

                self.load_data()

        except Exception:
            logger.exception(
                "Failed to open AddMissionaryDialog"
            )

    def _edit_columns(self):
        dialog = EditMissionaryColumnsDialog(
            MISSIONARY_COLUMNS,
            self._visible_column_keys,
            parent=self,
        )

        if dialog.exec() != QDialog.Accepted:
            return

        self._visible_column_keys = (
            dialog.selected_column_keys()
        )

        self._save_visible_column_keys()
        self._configure_table_columns()
        self._apply_filters()

    def _export_excel(self):
        if not self._all_missionaries:
            show_message(
                self,
                "No Data",
                "No missionaries to export.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Missionaries to Excel",
            "missionaries_export.xlsx",
            "Excel Files (*.xlsx)",
        )

        if not file_path:
            return

        ok = self.export_service.export_missionaries_to_excel(
            self._all_missionaries,
            file_path,
            columns=self._visible_columns(),
        )

        if ok:
            show_message(
                self,
                "Export Complete",
                f"Exported "
                f"{len(self._all_missionaries)} "
                f"missionaries to:\n{file_path}",
            )

        else:
            show_message(
                self,
                "Export Failed",
                "Failed to export. "
                "Check logs for details.",
                kind="critical",
            )

    def open_missionary_detail(self, row, column):
        _ = column

        selected_rows = {
            item.row()
            for item in self.table.selectedItems()
        }

        # Only open detail if a single row is selected.
        if len(selected_rows) > 1:
            return

        missionary_id = self._missionary_id_for_row(row)

        if missionary_id is not None:
            self._open_missionary_by_id(missionary_id)

    def _missionary_id_for_row(self, row):
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)

            if not item:
                continue

            missionary_id = item.data(
                Qt.UserRole
            )

            if missionary_id is not None:
                return missionary_id

        return None

    def _open_missionary_by_id(self, missionary_id):
        try:
            opener = getattr(
                self.main_window,
                "open_missionary_detail",
                None,
            )
            if callable(opener):
                opener(missionary_id)

        except Exception:
            logger.exception(
                "Failed to open missionary detail page"
            )

    def _batch_actions(self):
        selected_rows = set()

        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            show_message(
                self,
                "No Selection",
                "Select at least one missionary "
                "from the table.",
            )

            return

        ids = []

        for row in selected_rows:
            missionary_id = self._missionary_id_for_row(row)

            if missionary_id is not None:
                ids.append(missionary_id)

        # Show simple menu
        menu = create_menu("", self)

        advance_action = menu.addAction(
            "Advance Stage"
        )

        action = menu.exec(
            self.batch_button.mapToGlobal(
                self.batch_button.rect().bottomLeft()
            )
        )

        if action == advance_action:
            from ui.dialogs.batch_stage_advance_dialog import (
                BatchStageAdvanceDialog,
            )

            dialog = BatchStageAdvanceDialog(
                ids, parent=self
            )

            if dialog.exec() == QDialog.Accepted:
                self.load_data()

                # Also refresh dashboard
                if hasattr(
                    self.main_window, "dashboard_page"
                ):
                    self.main_window.dashboard_page.load_data()

    def _create_group(self):
        dialog = CreateMissionaryGroupDialog(
            self.group_service,
            self._all_missionaries,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.load_data()
            if dialog.saved_group:
                index = self.group_filter.findData(dialog.saved_group["id"])
                if index >= 0:
                    self.group_filter.setCurrentIndex(index)

    def _edit_selected_group(self):
        self._edit_group_by_id(self.group_filter.currentData())

    def _edit_group_by_id(self, group_id):
        group = self._groups_by_id.get(group_id)
        if not group:
            return

        dialog = CreateMissionaryGroupDialog(
            self.group_service,
            self._all_missionaries,
            parent=self,
            group=group,
        )
        if dialog.exec() == QDialog.Accepted:
            self.load_data()
            if dialog.saved_group:
                index = self.group_filter.findData(dialog.saved_group["id"])
                if index >= 0:
                    self.group_filter.setCurrentIndex(index)
