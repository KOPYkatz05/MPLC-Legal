from dataclasses import dataclass
from datetime import date, datetime
import time

from PySide6.QtCore import (
    QEvent,
    QRectF,
    QTimer,
    Qt,
    QItemSelectionModel,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QStackedWidget,
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
from services.client_view_service import ClientViewService

from services.export_service import ExportService
from services.group_package_export_service import (
    GroupPackageExportError,
    GroupPackageExportService,
)
from services.settings_service import SettingsService
from ui.foundation import (
    AppDialog,
    DialogFooter,
    FLUENT_AVAILABLE,
    MaskDialogBase,
    configure_data_table,
    create_button,
    create_combo_box,
    create_list_widget,
    create_line_edit,
    create_menu,
    create_pill_button,
    create_plain_text_edit,
    create_search_edit,
    create_table,
    fluent_icon,
    app_icon,
    setup_dialog_shell,
    show_message,
)

from ui.dialogs.add_missionary_dialog import (
    AddMissionaryDialog,
)

from utils.constants import WORKFLOW_STAGES

from utils.i18n import tr
from utils.logger import logger
from ui.foundation.background_loader import LatestRequestLoader
from ui.widgets.animated_tab_strip import AnimatedTabStrip


MISSIONARY_ROW_COLOR_STYLES = {
    "teal": ("#E6FFFB", "#0EA5AC"),
    "blue": ("#EFF6FF", "#2563EB"),
    "purple": ("#F5F3FF", "#7C3AED"),
    "amber": ("#FFFBEB", "#D97706"),
    "green": ("#ECFDF5", "#059669"),
    "red": ("#FEF2F2", "#DC2626"),
    "gray": ("#F4F4F5", "#71717A"),
}


def _missionary_row_color_icon(color):
    fill, accent = MISSIONARY_ROW_COLOR_STYLES[color]
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(fill))
    painter.setPen(QPen(QColor(accent), 1.5))
    painter.drawEllipse(2, 2, 14, 14)
    painter.end()
    return QIcon(pixmap)


def _empty_missionary_row_color_icon():
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.transparent)
    return QIcon(pixmap)


@dataclass(frozen=True)
class MissionaryColumn:
    key: str
    label: str
    getter: object
    default_width: int
    default_visible: bool = False
    required: bool = False
    copyable: bool = True


def create_missionaries_pill_button(
    text,
    variant="secondary",
    fixed_height=34,
    parent=None,
    icon=None,
):
    """Create a Missionaries-page action using the shared pill button factory."""
    button = create_pill_button(text, parent=parent, icon=icon)
    button.setObjectName("MissionariesPillButton")
    button.setProperty("missionariesTone", variant)
    button.setFixedHeight(fixed_height)
    return button


def _format_date(value):
    if not value:
        return ""

    try:
        return value.strftime("%d/%m/%Y")
    except AttributeError:
        return str(value)


def _text_attr(field_name):
    return lambda missionary: getattr(missionary, field_name, None) or ""


def _last_name_first(full_name):
    parts = str(full_name or "").strip().split()

    if len(parts) <= 1:
        return " ".join(parts)

    surname_count = 2 if len(parts) >= 4 else 1
    surname = " ".join(parts[-surname_count:])
    given_names = " ".join(parts[:-surname_count])

    if not given_names:
        return surname

    return f"{surname}, {given_names}"


def _last_name_first_attr(missionary):
    preferred_name = (
        getattr(missionary, "preferred_name", None) or ""
    ).strip()

    if preferred_name:
        return preferred_name

    return _last_name_first(
        getattr(missionary, "full_name", None)
    )


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
        "last_name_first",
        "Last Name First",
        _last_name_first_attr,
        240,
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

ARCHIVE_REASON_COLUMN = MissionaryColumn(
    "archive_reason",
    "Archive Reason",
    _text_attr("archive_reason"),
    240,
)

COLUMN_BY_KEY = {
    column.key: column
    for column in MISSIONARY_COLUMNS
}
COLUMN_BY_KEY[ARCHIVE_REASON_COLUMN.key] = ARCHIVE_REASON_COLUMN

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


def _missionaries_dialog_header(title_text, subtitle_text):
    header = QFrame()
    header.setObjectName("MissionariesDialogHeader")
    header.setAttribute(Qt.WA_StyledBackground, True)

    layout = QVBoxLayout()
    layout.setContentsMargins(18, 16, 18, 12)
    layout.setSpacing(4)
    header.setLayout(layout)

    title = QLabel(title_text)
    title.setObjectName("MissionariesDialogTitle")
    subtitle = QLabel(subtitle_text)
    subtitle.setObjectName("MissionariesDialogSubtitle")
    subtitle.setWordWrap(True)

    layout.addWidget(title)
    layout.addWidget(subtitle)
    return header


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
    lucide_icon = app_icon(
        _icon_slot_for_names(names),
        size=18,
        color="#52525B",
    )
    if isinstance(lucide_icon, QIcon) and not lucide_icon.isNull():
        return lucide_icon

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


def _icon_slot_for_names(names):
    slot_by_name = {
        "ACCEPT": "table.copy_done",
        "CHECKBOX": "table.copy_done",
        "CHECK_MARK": "table.copy_done",
        "COMPLETED": "table.copy_done",
        "COPY": "table.copy",
        "DOCUMENT_COPY": "table.copy",
        "DUPLICATE": "table.copy",
        "EDIT": "table.edit",
        "EDIT_SOLID": "table.edit",
        "PENCIL": "table.edit",
    }
    for name in names:
        slot = slot_by_name.get(name)
        if slot:
            return slot
    return ""


def _arrival_date_sort_key(missionary):
    """Return the stable default ordering for the missionaries list."""
    arrival_date = _date_sort_value(
        getattr(missionary, "arrival_date", None)
    )
    return (
        not arrival_date,
        arrival_date,
        (getattr(missionary, "full_name", None) or "").casefold(),
        getattr(missionary, "id", 0),
    )


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

        header = _missionaries_dialog_header(
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
        body_layout.setContentsMargins(20, 18, 20, 20)
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


class CreateMissionaryGroupDialog(AppDialog):
    def __init__(
        self,
        group_service,
        missionaries,
        parent=None,
        group=None,
        selected_missionary_ids=None,
    ):
        self.group_service = group_service
        self.missionaries = list(missionaries)
        self.group = group or {}
        self._is_editing = group is not None
        if group is None and selected_missionary_ids:
            self.group["missionary_ids"] = list(selected_missionary_ids)
        self.saved_group = None

        super().__init__(
            parent,
            title="Edit Group" if self._is_editing else "Create Group",
            subtitle=(
                "Update who belongs to this reusable missionary group."
                if self._is_editing
                else "Save a reusable missionary group for filtering and shared tasks."
            ),
            width=520,
            min_height=560,
        )
        self.setup_ui()

    def setup_ui(self):
        self.name_input = create_line_edit("Group name")
        self.name_input.setText(self.group.get("name", ""))
        self.body_layout.addWidget(self._field("Name", self.name_input))

        self.description_input = create_plain_text_edit()
        self.description_input.setPlaceholderText("Optional description")
        self.description_input.setFixedHeight(76)
        self.description_input.setPlainText(self.group.get("description", ""))
        self.body_layout.addWidget(self._field("Description", self.description_input))

        self.search_input = create_search_edit("Search missionaries")
        self.search_input.textChanged.connect(self._filter_items)
        self.body_layout.addWidget(self.search_input)

        self.member_list = create_list_widget("MissionaryGroupMemberList")
        self.member_list.setMinimumHeight(220)
        self.body_layout.addWidget(self.member_list, stretch=1)
        self._load_members()
        cancel_btn = create_button("Cancel", "secondary")
        cancel_btn.clicked.connect(self.reject)
        self.footer.add_action(cancel_btn)
        save_btn = create_button("Save", "primary")
        save_btn.clicked.connect(self._save)
        self.footer.add_action(save_btn)

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


class BatchArchiveDialog(MaskDialogBase):
    def __init__(self, selected_count, parent=None):
        fluent_parent = parent.window() if parent is not None else None
        self._use_fluent_dialog = (
            FLUENT_AVAILABLE and fluent_parent is not None
        )

        if self._use_fluent_dialog:
            super().__init__(fluent_parent)
        else:
            QDialog.__init__(self, parent)

        self.selected_count = selected_count
        self.archive_mode = "group"
        self.group_name = ""

        self.setWindowTitle("Archive Missionaries")
        self.surface = setup_dialog_shell(
            self,
            surface_width=520,
            surface_min_height=360,
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
            _missionaries_dialog_header(
                "Archive Missionaries",
                (
                    "Make group out of selected missionaries and archive? "
                    "Or archive each individually all at once?"
                ),
            )
        )

        body = QWidget()
        body.setObjectName("MissionariesDialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(18, 16, 18, 16)
        body_layout.setSpacing(12)
        body.setLayout(body_layout)

        count_label = QLabel(
            f"{self.selected_count} missionary(s) selected."
        )
        count_label.setObjectName("MutedText")
        body_layout.addWidget(count_label)

        self.mode_group = QButtonGroup(self)
        self.group_radio = QRadioButton(
            "Group into one archive file"
        )
        self.individual_radio = QRadioButton(
            "Archive each individually"
        )
        self.group_radio.setChecked(True)
        self.mode_group.addButton(self.group_radio)
        self.mode_group.addButton(self.individual_radio)

        body_layout.addWidget(self.group_radio)

        self.name_input = create_line_edit("Archive group name")
        body_layout.addWidget(
            self._field("Group Name", self.name_input)
        )

        body_layout.addWidget(self.individual_radio)

        self.group_radio.toggled.connect(
            self._update_name_enabled
        )
        self._update_name_enabled()

        root.addWidget(body, stretch=1)

        footer = DialogFooter()
        cancel_btn = create_button("Cancel", "secondary")
        cancel_btn.clicked.connect(self.reject)
        footer.add_action(cancel_btn)
        archive_btn = create_button("Archive", "primary")
        archive_btn.clicked.connect(self._accept_archive)
        footer.add_action(archive_btn)
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

    def _update_name_enabled(self, checked=True):
        _ = checked
        enabled = self.group_radio.isChecked()
        self.name_input.setEnabled(enabled)

    def _accept_archive(self):
        if self.group_radio.isChecked():
            group_name = self.name_input.text().strip()
            if not group_name:
                show_message(
                    self,
                    "Group Name Required",
                    "Enter a name for the archive group.",
                    kind="warning",
                )
                return

            self.archive_mode = "group"
            self.group_name = group_name

        else:
            self.archive_mode = "individual"
            self.group_name = ""

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
        self.client_view_service = ClientViewService()
        self._background_loads_enabled = isinstance(main_window, QWidget)
        self._data_loader = LatestRequestLoader(parent=self)
        self._has_loaded_data = False
        self._last_load_at = 0.0
        self._cache_ttl_seconds = 20.0
        self._pending_navigation_restore = None

        self.export_service = ExportService()
        self.group_package_export_service = GroupPackageExportService(
            self.export_service
        )

        self._all_missionaries = []
        self._archived_missionaries = []
        self._filtered_missionaries = []
        self._groups_by_id = {}
        self._group_members_by_id = {}
        self._last_group_filter_data = None
        self._default_sort_initialized = False
        self._selected_tab = getattr(
            self.settings_service,
            "get_missionaries_default_view",
            lambda: "active",
        )()
        self._tab_buttons = {}
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

        self.groups_table.cellDoubleClicked.connect(
            self._open_group_from_table
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

        if not self._background_loads_enabled:
            self._load_data_synchronously()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        self.add_button = create_missionaries_pill_button(
            "+ Add Missionary",
            "primary",
        )

        self.export_button = create_missionaries_pill_button(
            tr("export_menu"),
            "secondary",
        )

        self.export_button.clicked.connect(
            self._show_export_menu
        )

        self.edit_columns_button = create_missionaries_pill_button(
            "Edit Columns",
            "secondary",
        )

        self.edit_columns_button.clicked.connect(
            self._edit_columns
        )

        self.auto_widths_button = create_missionaries_pill_button(
            "Fit Columns",
            "secondary",
        )

        self.auto_widths_button.clicked.connect(
            self._auto_fit_column_widths
        )

        outer.addWidget(self._build_top_bar())

        workspace = QWidget()
        workspace.setObjectName("MissionariesWorkspace")
        workspace.setAttribute(Qt.WA_StyledBackground, True)
        workspace_layout = QVBoxLayout()
        workspace_layout.setContentsMargins(12, 12, 24, 24)
        workspace_layout.setSpacing(12)
        workspace.setLayout(workspace_layout)

        self.filter_bar = QFrame()
        self.filter_bar.setObjectName("MissionariesFilterBar")
        self.filter_bar.setAttribute(Qt.WA_StyledBackground, True)
        self._filter_layout = QGridLayout()
        self._filter_layout.setContentsMargins(18, 12, 18, 12)
        self._filter_layout.setHorizontalSpacing(12)
        self._filter_layout.setVerticalSpacing(8)
        self.filter_bar.setLayout(self._filter_layout)

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

        self.create_group_button = create_missionaries_pill_button(
            "Create Group",
            "secondary",
        )

        self.batch_button = create_missionaries_pill_button(
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

        self._filter_widgets = [
            self.search_input,
            self.stage_filter,
            self.nationality_filter,
            self.group_filter,
            self.create_group_button,
            self.batch_button,
        ]

        workspace_layout.addWidget(self.filter_bar)

        # ==========================================
        # Table
        # ==========================================

        self.table = create_table()
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            self._show_archive_context_menu
        )

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

        self.table_surface = QFrame()
        self.table_surface.setObjectName("MissionariesTableSurface")
        self.table_surface.setAttribute(Qt.WA_StyledBackground, True)
        table_surface_layout = QVBoxLayout()
        table_surface_layout.setContentsMargins(0, 0, 0, 0)
        table_surface_layout.setSpacing(0)
        self.table_surface.setLayout(table_surface_layout)

        table_header = QFrame()
        table_header.setObjectName("MissionariesTableHeader")
        table_header.setAttribute(Qt.WA_StyledBackground, True)
        table_header_layout = QHBoxLayout()
        table_header_layout.setContentsMargins(16, 10, 16, 10)
        table_header_layout.setSpacing(10)
        table_header.setLayout(table_header_layout)

        self.table_title = QLabel("Missionary Records")
        self.table_title.setObjectName("PanelTitle")
        table_header_layout.addWidget(self.table_title)
        table_header_layout.addStretch()
        table_header_layout.addWidget(self.result_label)

        table_surface_layout.addWidget(table_header)
        table_surface_layout.addWidget(self.table, stretch=1)

        self.groups_surface = self._build_groups_surface()

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.table_surface)
        self.view_stack.addWidget(self.groups_surface)
        workspace_layout.addWidget(self.view_stack, stretch=1)
        outer.addWidget(workspace, stretch=1)
        QTimer.singleShot(0, self._update_responsive_layout)

    def _build_top_bar(self):
        top_bar = QFrame()
        top_bar.setObjectName("MissionariesTopBar")
        top_bar.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 16, 12)
        layout.setSpacing(8)
        top_bar.setLayout(layout)

        tabs = AnimatedTabStrip()
        self._tab_buttons = tabs.buttons
        for key, text in [
            ("active", "Active"),
            ("groups", "Groups"),
            ("archive", "Archive"),
        ]:
            tabs.add_tab(key, text, self._select_tab)
        tabs.set_active(self._selected_tab, animate=False)
        layout.addWidget(tabs)

        command_row = QGridLayout()
        command_row.setContentsMargins(0, 0, 0, 0)
        command_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(3)

        title = QLabel("Missionaries")
        title.setObjectName("MissionariesTitle")
        subtitle = QLabel("Track legal workflow status and documents.")
        subtitle.setObjectName("MissionariesSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)

        title_widget = QWidget()
        title_widget.setLayout(title_stack)
        self._command_layout = command_row
        self._command_title = title_widget
        self._command_buttons = [
            self.edit_columns_button,
            self.auto_widths_button,
            self.export_button,
            self.add_button,
        ]


        layout.addLayout(command_row)

        return top_bar

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _update_responsive_layout(self):
        """Reflow page controls to fit the current screen/window width."""
        if not hasattr(self, "_filter_layout"):
            return

        width = self.width()
        compact = width < 960
        very_compact = width < 680

        for widget in self._command_buttons:
            self._command_layout.removeWidget(widget)
        self._command_layout.removeWidget(self._command_title)
        self._command_layout.addWidget(
            self._command_title, 0, 0, 1, 4 if compact else 1
        )
        if compact:
            button_columns = 2 if very_compact else 4
            for index, button in enumerate(self._command_buttons):
                self._command_layout.addWidget(
                    button,
                    1 + index // button_columns,
                    index % button_columns,
                )
        else:
            for column, button in enumerate(self._command_buttons, start=1):
                self._command_layout.addWidget(button, 0, column)
            self._command_layout.setColumnStretch(0, 1)

        for widget in self._filter_widgets:
            self._filter_layout.removeWidget(widget)
        if very_compact:
            columns = 2
        elif compact:
            columns = 3
        else:
            columns = 6
        for index, widget in enumerate(self._filter_widgets):
            self._filter_layout.addWidget(
                widget, index // columns, index % columns
            )
        self._filter_layout.setColumnStretch(0, 1)
        self.search_input.setMaximumWidth(16777215 if compact else 280)

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
        columns = [
            COLUMN_BY_KEY[key]
            for key in self._visible_column_keys
            if key in COLUMN_BY_KEY
            and (
                key != ARCHIVE_REASON_COLUMN.key
                or self._selected_tab == "archive"
            )
        ]
        if (
            self._selected_tab == "archive"
            and ARCHIVE_REASON_COLUMN.key not in {
                column.key for column in columns
            }
        ):
            columns.append(ARCHIVE_REASON_COLUMN)
        return columns

    def _column_dialog_columns(self):
        if self._selected_tab == "archive":
            return [*MISSIONARY_COLUMNS, ARCHIVE_REASON_COLUMN]

        return MISSIONARY_COLUMNS

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

    def _build_groups_surface(self):
        surface = QFrame()
        surface.setObjectName("MissionariesTableSurface")
        surface.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        surface.setLayout(layout)

        header = QFrame()
        header.setObjectName("MissionariesTableHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(10)
        header.setLayout(header_layout)

        self.groups_title = QLabel("Missionary Groups")
        self.groups_title.setObjectName("PanelTitle")
        self.groups_result_label = QLabel("")
        self.groups_result_label.setObjectName("ResultLabel")
        header_layout.addWidget(self.groups_title)
        header_layout.addStretch()
        header_layout.addWidget(self.groups_result_label)

        self.groups_table = create_table()
        self.groups_table.setColumnCount(5)
        self.groups_table.setHorizontalHeaderLabels([
            "Group Name",
            "Members",
            "Description",
            "Type",
            "Updated",
        ])
        configure_data_table(
            self.groups_table,
            {
                0: QHeaderView.Interactive,
                1: QHeaderView.ResizeToContents,
                2: QHeaderView.Stretch,
                3: QHeaderView.Interactive,
                4: QHeaderView.Interactive,
            },
            selection_mode=QAbstractItemView.SingleSelection,
            sorting=True,
        )
        self.groups_table.setColumnWidth(0, 260)
        self.groups_table.setColumnWidth(3, 160)
        self.groups_table.setColumnWidth(4, 150)

        layout.addWidget(header)
        layout.addWidget(self.groups_table, stretch=1)
        return surface

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
        """Compatibility entry point for mutation-triggered forced refreshes."""
        if self._background_loads_enabled:
            return self.request_refresh(force=True)
        self._load_data_synchronously()
        return True

    def request_refresh(self, force=False):
        """Refresh in the background while retaining the last rendered table."""
        if not self._background_loads_enabled:
            cache_is_fresh = (
                self._has_loaded_data
                and time.monotonic() - self._last_load_at
                < self._cache_ttl_seconds
            )
            if cache_is_fresh and not force:
                return False
            self._load_data_synchronously()
            return True

        cache_is_fresh = (
            self._has_loaded_data
            and time.monotonic() - self._last_load_at
            < self._cache_ttl_seconds
        )
        if cache_is_fresh and not force:
            return False
        if self._data_loader.busy and not force:
            return False

        self._data_loader.request(
            self.client_view_service.get_missionaries_snapshot,
            on_success=self._apply_missionaries_snapshot,
            on_error=self._missionaries_refresh_failed,
        )
        return True

    def _load_data_synchronously(self):
        try:
            get_archived = getattr(
                self.missionary_service,
                "get_archived_missionaries",
                None,
            )
            self._apply_missionaries_snapshot({
                "active": self.missionary_service.get_all_missionaries(),
                "archived": (
                    get_archived()
                    if callable(get_archived)
                    else []
                ),
                "groups": self.group_service.list_groups(),
            })
        except Exception:
            logger.exception(
                "Failed to load missionaries table"
            )

    def _apply_missionaries_snapshot(self, snapshot):
        self._all_missionaries = list(snapshot.get("active") or [])
        self._archived_missionaries = list(snapshot.get("archived") or [])
        self._refresh_group_filter(snapshot.get("groups") or [])

        existing = [
            self.nationality_filter.itemText(i)
            for i in range(self.nationality_filter.count())
        ]
        for missionary in self._all_missionaries:
            nationality = (missionary.nationality or "").strip()
            if nationality and nationality not in existing:
                self.nationality_filter.addItem(nationality, nationality)
                existing.append(nationality)

        pending_state = self._pending_navigation_restore
        if pending_state:
            self._restore_navigation_controls(pending_state)

        self._render_selected_tab()
        self._has_loaded_data = True
        self._last_load_at = time.monotonic()

        if pending_state:
            self._pending_navigation_restore = None
            QTimer.singleShot(
                0,
                lambda state=pending_state:
                self._restore_table_view_state(state),
            )

        logger.info(
            "Loaded %s active and %s archived missionaries into table",
            len(self._all_missionaries),
            len(self._archived_missionaries),
        )

    @staticmethod
    def _missionaries_refresh_failed(error):
        logger.error(
            "Failed to refresh missionaries in background: %s",
            error,
        )

    def _apply_filters(self):
        source = (
            self._archived_missionaries
            if self._selected_tab == "archive"
            else self._all_missionaries
        )
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
            None
            if self._selected_tab == "archive"
            else self.group_filter.currentData()
        )

        group_member_ids = set(
            self._group_members_by_id.get(selected_group, [])
        )

        filtered = []

        for m in source:
            display_id = (
                missionary_display_id(m).lower()
            )

            name = (m.full_name or "").lower()

            preferred = (
                (m.preferred_name or "").lower()
            )

            last_name_first = (
                _last_name_first_attr(m).lower()
            )

            if search_text and (
                search_text not in display_id
                and search_text not in name
                and search_text not in preferred
                and search_text not in last_name_first
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
        self._filtered_missionaries = list(filtered)

        total = len(source)

        shown = len(filtered)

        if shown == total:
            self.result_label.setText(
                f"{total} missionaries"
            )

        else:
            self.result_label.setText(
                f"{shown} of {total} missionaries"
            )

    def _render_selected_tab(self):
        self._sync_tab_buttons()

        if self._selected_tab == "groups":
            self.view_stack.setCurrentWidget(self.groups_surface)
            self.filter_bar.hide()
            self.edit_columns_button.hide()
            self.auto_widths_button.hide()
            self.export_button.hide()
            self.add_button.hide()
            if hasattr(self, "copy_button"):
                self.copy_button.hide()
            self._populate_groups_table()
            return

        self.view_stack.setCurrentWidget(self.table_surface)
        self.filter_bar.show()
        self.edit_columns_button.show()
        self.auto_widths_button.show()
        self.export_button.show()

        is_archive = self._selected_tab == "archive"
        self.add_button.setVisible(not is_archive)
        self.create_group_button.setVisible(not is_archive)
        self.batch_button.setVisible(not is_archive)
        self.group_filter.setVisible(not is_archive)
        self.table_title.setText(
            "Archived Missionary Records"
            if is_archive
            else "Missionary Records"
        )

        self._configure_table_columns()
        self._apply_filters()

    def _select_tab(self, tab_key):
        if tab_key not in {"active", "groups", "archive"}:
            return

        if self._selected_tab == tab_key:
            return

        self._selected_tab = tab_key
        self._render_selected_tab()

    def _sync_tab_buttons(self):
        tab_strip = next(
            (button.parentWidget() for button in self._tab_buttons.values()), None
        )
        if isinstance(tab_strip, AnimatedTabStrip):
            tab_strip.set_active(self._selected_tab, animate=False)
            return
        for key, button in getattr(self, "_tab_buttons", {}).items():
            active = key == self._selected_tab
            button.setChecked(active)
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _populate_groups_table(self):
        groups = list(self._groups_by_id.values())
        groups.sort(key=lambda group: (group.get("name") or "").casefold())

        self.groups_table.setSortingEnabled(False)
        self.groups_table.clearContents()
        self.groups_table.setRowCount(len(groups))
        self.groups_table.verticalHeader().setDefaultSectionSize(40)

        for row, group in enumerate(groups):
            self.groups_table.setRowHeight(row, 40)
            values = [
                group.get("name", ""),
                str(group.get("member_count", 0)),
                group.get("description", ""),
                self._group_type_label(group),
                _format_date(group.get("updated_at")),
            ]
            for column, value in enumerate(values):
                item = MissionaryTableItem(value or "")
                item.setData(Qt.UserRole, group.get("id"))
                item.setData(SORT_VALUE_ROLE, value or "")
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.groups_table.setItem(row, column, item)

        self.groups_table.setSortingEnabled(True)
        self.groups_result_label.setText(f"{len(groups)} groups")

    @staticmethod
    def _group_type_label(group):
        if group.get("group_type") == "TEMPORARY_AUTOMATION":
            return "Temporary"

        return group.get("group_type") or "Manual"

    def _populate_table(self, missionaries):
        # Disable sorting while populating to
        # avoid row index issues
        if not self._default_sort_initialized:
            dated = [m for m in missionaries if _date_sort_value(getattr(m, "arrival_date", None))]
            undated = [m for m in missionaries if not _date_sort_value(getattr(m, "arrival_date", None))]
            missionaries = sorted(
                dated,
                key=_arrival_date_sort_key,
                reverse=True,
            ) + undated
        else:
            columns = self._visible_columns()
            header = self.table.horizontalHeader()
            sort_column = header.sortIndicatorSection()
            if 0 <= sort_column < len(columns):
                column = columns[sort_column]
                missionaries = sorted(
                    missionaries,
                    key=lambda missionary: _sort_value_for_column(
                        column,
                        missionary,
                        str(column.getter(missionary) or ""),
                    ),
                    reverse=header.sortIndicatorOrder() == Qt.DescendingOrder,
                )
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

            self._apply_missionary_row_color(row, m)

        self.table.setSortingEnabled(True)
        if not self._default_sort_initialized:
            columns = self._visible_columns()
            arrival_index = next(
                (index for index, column in enumerate(columns) if column.key == "arrival_date"),
                0,
            )
            self.table.horizontalHeader().setSortIndicator(
                arrival_index,
                Qt.DescendingOrder,
            )
            self._default_sort_initialized = True

    def _apply_missionary_row_color(self, row, missionary):
        fill, accent = MISSIONARY_ROW_COLOR_STYLES.get(
            getattr(missionary, "row_color", None),
            (None, None),
        )
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item is None:
                continue
            item.setData(Qt.BackgroundRole, QColor(fill) if fill else None)
            item.setData(Qt.ForegroundRole, QColor("#18181B"))
            item.setData(Qt.UserRole + 1, accent)

    def _replace_cached_missionary(self, updated):
        for collection_name in ("_all_missionaries", "_archived_missionaries"):
            collection = getattr(self, collection_name)
            for index, missionary in enumerate(collection):
                if missionary.id == updated.id:
                    collection[index] = updated

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

    def _refresh_group_filter(self, groups=None):
        if not hasattr(self, "group_filter"):
            return

        current_group = self.group_filter.currentData()
        if current_group == GROUP_EDIT_ACTION:
            current_group = self._last_group_filter_data
        if groups is None:
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
                self._group_filter_label(group),
                group["id"],
            )
        self._add_group_edit_action()
        index = self.group_filter.findData(current_group)
        if index >= 0:
            self.group_filter.setCurrentIndex(index)
        self._last_group_filter_data = self.group_filter.currentData()
        self.group_filter.blockSignals(False)
        if hasattr(self, "groups_table"):
            self._populate_groups_table()

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

    @staticmethod
    def _group_filter_label(group):
        label = f"{group['name']} ({group.get('member_count', 0)})"
        if group.get("group_type") == "TEMPORARY_AUTOMATION":
            return f"{label}  [Temporary]"
        return label

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

    def capture_navigation_state(self):
        selected_ids = self._selected_missionary_ids() if hasattr(self, "table") else []
        current_item = self.table.currentItem() if hasattr(self, "table") else None
        current_id = current_item.data(Qt.UserRole) if current_item is not None else None

        return {
            "search_text": self.search_input.text() if hasattr(self, "search_input") else "",
            "stage_filter": self.stage_filter.currentData() if hasattr(self, "stage_filter") else None,
            "nationality_filter": self.nationality_filter.currentData() if hasattr(self, "nationality_filter") else None,
            "group_filter": self.group_filter.currentData() if hasattr(self, "group_filter") else None,
            "selected_tab": self._selected_tab,
            "selected_ids": selected_ids,
            "current_id": current_id,
            "vertical_scroll": self.table.verticalScrollBar().value() if hasattr(self, "table") else 0,
            "horizontal_scroll": self.table.horizontalScrollBar().value() if hasattr(self, "table") else 0,
        }

    def restore_navigation_state(self, state):
        if not state:
            return

        self._restore_navigation_controls(state)

        if self._background_loads_enabled:
            self._pending_navigation_restore = dict(state)
            refresh_started = self.request_refresh(force=False)
            if self._has_loaded_data:
                self._render_selected_tab()
                QTimer.singleShot(
                    0,
                    lambda snapshot=state:
                    self._restore_table_view_state(snapshot),
                )
            if not refresh_started and not self._data_loader.busy:
                self._pending_navigation_restore = None
            return

        self.load_data()

        QTimer.singleShot(
            0,
            lambda snapshot=state: self._restore_table_view_state(snapshot),
        )

    def _restore_navigation_controls(self, state):
        controls = (
            getattr(self, "search_input", None),
            getattr(self, "stage_filter", None),
            getattr(self, "nationality_filter", None),
            getattr(self, "group_filter", None),
        )
        for control in controls:
            if control is not None and hasattr(control, "blockSignals"):
                control.blockSignals(True)

        try:
            if hasattr(self, "search_input"):
                self.search_input.setText(state.get("search_text", ""))
            if hasattr(self, "stage_filter"):
                self._set_combo_data(
                    self.stage_filter,
                    state.get("stage_filter"),
                )
            if hasattr(self, "nationality_filter"):
                self._set_combo_data(
                    self.nationality_filter,
                    state.get("nationality_filter"),
                )
            if hasattr(self, "group_filter"):
                self._set_combo_data(
                    self.group_filter,
                    state.get("group_filter"),
                )
            self._selected_tab = state.get("selected_tab", "active")
        finally:
            for control in controls:
                if control is not None and hasattr(control, "blockSignals"):
                    control.blockSignals(False)

    def _restore_table_view_state(self, state):
        if not hasattr(self, "table"):
            return

        selected_ids = state.get("selected_ids") or []
        current_id = state.get("current_id")
        row_to_focus = None
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()

        for row in range(self.table.rowCount()):
            missionary_id = self._missionary_id_for_row(row)
            if missionary_id is None:
                continue
            if missionary_id in selected_ids:
                index = self.table.model().index(row, 0)
                if selection_model is not None:
                    selection_model.select(
                        index,
                        QItemSelectionModel.Select | QItemSelectionModel.Rows,
                    )
                if row_to_focus is None:
                    row_to_focus = row
            if row_to_focus is None and missionary_id == current_id:
                row_to_focus = row

        if row_to_focus is not None:
            index = self.table.model().index(row_to_focus, 0)
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index)

        if hasattr(self, "table"):
            self.table.verticalScrollBar().setValue(
                state.get("vertical_scroll", 0)
            )
            self.table.horizontalScrollBar().setValue(
                state.get("horizontal_scroll", 0)
            )

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
            self._column_dialog_columns(),
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
        self._render_selected_tab()

    def _export_excel(self):
        missionaries = list(self._filtered_missionaries)

        if not missionaries:
            show_message(
                self,
                "No Data",
                "No missionaries in the current view to export.",
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
            missionaries,
            file_path,
            columns=self._visible_columns(),
        )

        if ok:
            show_message(
                self,
                "Export Complete",
                f"Exported "
                f"{len(missionaries)} "
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

    def _show_export_menu(self):
        menu = create_menu("", self)
        export_columns_action = QAction(
            tr("export_columns"),
            self,
        )
        full_export_action = QAction(
            tr("export_full"),
            self,
        )
        export_columns_action.triggered.connect(self._export_excel)
        full_export_action.triggered.connect(self._export_full_group)

        menu.addAction(export_columns_action)
        menu.addAction(full_export_action)
        self._export_menu = menu

        menu.exec(
            self.export_button.mapToGlobal(
                self.export_button.rect().bottomLeft()
            )
        )

    def _export_full_group(self):
        if self._selected_tab == "archive":
            show_message(
                self,
                "Active Group Required",
                "Full group packages are exported from the Active tab.",
                kind="warning",
            )
            return

        group_id = self.group_filter.currentData()

        if not group_id:
            show_message(
                self,
                tr("export_select_group_title"),
                tr("export_select_group_message"),
                kind="warning",
            )
            return

        group = self._groups_by_id.get(group_id, {})
        group_name = group.get("name") or "missionary_group"
        default_name = f"{self._safe_export_filename(group_name)} - Full Export.zip"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("export_full_dialog_title"),
            default_name,
            "Zip Files (*.zip)",
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".zip"):
            file_path = f"{file_path}.zip"

        try:
            result = self.group_package_export_service.export_group_package(
                group_id,
                file_path,
            )
        except GroupPackageExportError as exc:
            show_message(
                self,
                tr("export_failed_title"),
                str(exc),
                kind="critical",
            )
            return
        except Exception:
            logger.exception("Failed to export full missionary group package")
            show_message(
                self,
                tr("export_failed_title"),
                tr("export_failed_message"),
                kind="critical",
            )
            return

        message = tr(
            "export_full_complete_message",
            count=result.missionary_count,
            path=file_path,
        )
        if result.skipped_folders:
            message = (
                f"{message}\n\n"
                f"{tr('export_full_missing_folders')}\n"
                + "\n".join(result.skipped_folders)
            )

        show_message(
            self,
            tr("export_complete_title"),
            message,
        )

    @staticmethod
    def _safe_export_filename(value):
        blocked = '<>:"/\\|?*'
        safe = "".join("-" if char in blocked else char for char in value)
        safe = " ".join(safe.split())
        return safe.strip(" .") or "missionary_group"

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

    def _open_group_from_table(self, row, column):
        _ = column
        group_id = None

        for column_index in range(self.groups_table.columnCount()):
            item = self.groups_table.item(row, column_index)
            if item is not None:
                group_id = item.data(Qt.UserRole)
                break

        if group_id is None:
            return

        self._select_tab("active")
        self._set_combo_data(self.group_filter, group_id)
        self._last_group_filter_data = group_id
        self._apply_filters()

    def _show_archive_context_menu(self, position):
        if self._selected_tab == "groups":
            return

        index = self.table.indexAt(position)
        if not index.isValid():
            return

        missionary_id = self._missionary_id_for_row(index.row())
        if missionary_id is None:
            return

        self.table.selectRow(index.row())

        menu = create_menu("", self)

        color_menu = create_menu("Change Color", menu)
        for color in sorted(MissionaryService.ROW_COLORS):
            action = QAction(color.title(), color_menu)
            action.setIcon(_missionary_row_color_icon(color))
            action.triggered.connect(
                lambda _checked=False, value=color, mid=missionary_id:
                self._set_missionary_row_color(mid, value)
            )
            color_menu.addAction(action)
        color_menu.addSeparator()
        clear_color = QAction("Remove", color_menu)
        clear_color.setIcon(_empty_missionary_row_color_icon())
        clear_color.triggered.connect(
            lambda _checked=False, mid=missionary_id:
            self._set_missionary_row_color(mid, None)
        )
        color_menu.addAction(clear_color)
        menu.addMenu(color_menu)

        group_menu = create_menu("Add to group", menu)
        groups = sorted(
            self._groups_by_id.values(),
            key=lambda group: (group.get("name") or "").casefold(),
        )
        if groups:
            for group in groups:
                group_id = group.get("id")
                action = QAction(group.get("name") or "Unnamed group", group_menu)
                action.triggered.connect(
                    lambda _checked=False, gid=group_id, mid=missionary_id:
                    self._add_missionary_to_group(mid, gid)
                )
                group_menu.addAction(action)
        else:
            empty_action = QAction("No groups available", group_menu)
            empty_action.setEnabled(False)
            group_menu.addAction(empty_action)
        menu.addMenu(group_menu)

        if self._selected_tab == "archive":
            delete_action = QAction("Delete", self)
            recover_action = QAction("Recover", self)

            delete_action.triggered.connect(
                lambda checked=False, mid=missionary_id:
                self._delete_archived_missionary(mid)
            )
            recover_action.triggered.connect(
                lambda checked=False, mid=missionary_id:
                self._recover_archived_missionary(mid)
            )

            menu.addAction(delete_action)
            menu.addAction(recover_action)
        self._archive_context_menu = menu
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _add_missionary_to_group(self, missionary_id, group_id):
        try:
            existing_ids = self.group_service.missionary_ids_for_group(group_id)
            existing_ids = list(existing_ids or [])
            if missionary_id in existing_ids:
                return

            self.group_service.update_group(
                group_id,
                missionary_ids=[*existing_ids, missionary_id],
            )
            self._refresh_group_filter()
            self._apply_filters()
        except Exception as exc:
            logger.exception(
                "Failed to add missionary %s to group %s",
                missionary_id,
                group_id,
            )
            show_message(
                self,
                "Add to Group",
                f"Could not add the missionary to the group: {exc}",
                kind="error",
            )

    def _set_missionary_row_color(self, missionary_id, color):
        try:
            updated = (
                self.missionary_service.clear_missionary_row_color(missionary_id)
                if color is None
                else self.missionary_service.set_missionary_row_color(missionary_id, color)
            )
            if updated is not None:
                self._replace_cached_missionary(updated)
                self._apply_filters()
        except Exception as exc:
            logger.exception("Failed to save missionary row color")
            show_message(
                self,
                "Row Color",
                f"Could not save the row color: {exc}",
                kind="error",
            )

    def _delete_archived_missionary(self, missionary_id):
        response = show_message(
            self,
            "Delete Archived Missionary",
            "Move this archived missionary to Trash?",
            kind="question",
            buttons="yes_no",
        )

        if response not in {1, 16384}:
            return

        try:
            self.missionary_service.delete_missionary(missionary_id)
            self.load_data()
            self._refresh_trash_page()
            show_message(
                self,
                "Deleted",
                "Archived missionary moved to Trash.",
            )

        except Exception:
            logger.exception("Failed to delete archived missionary")
            show_message(
                self,
                "Delete Failed",
                "Failed to delete archived missionary.",
                kind="critical",
            )

    def _recover_archived_missionary(self, missionary_id):
        try:
            self.missionary_service.restore_missionary(missionary_id)
            self.load_data()
            show_message(
                self,
                "Recovered",
                "Missionary recovered to Active.",
            )

        except Exception:
            logger.exception("Failed to recover archived missionary")
            show_message(
                self,
                "Recover Failed",
                "Failed to recover archived missionary.",
                kind="critical",
            )

    def _refresh_trash_page(self):
        trash_page = getattr(self.main_window, "trash_page", None)
        refresh = getattr(trash_page, "load_data", None)
        if callable(refresh):
            refresh()

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

    def _selected_missionary_ids(self):
        selected_rows = {
            item.row()
            for item in self.table.selectedItems()
        }

        ids = []

        for row in sorted(selected_rows):
            missionary_id = self._missionary_id_for_row(row)

            if missionary_id is not None and missionary_id not in ids:
                ids.append(missionary_id)

        return ids

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
        ids = self._selected_missionary_ids()

        if not ids:
            show_message(
                self,
                "No Selection",
                "Select at least one missionary "
                "from the table.",
            )

            return

        menu = create_menu("", self)

        advance_action = QAction(
            "Advance Stage",
            self,
        )
        archive_action = QAction(
            "Archive",
            self,
        )

        advance_action.triggered.connect(
            lambda checked=False: self._batch_advance_stage(ids)
        )
        archive_action.triggered.connect(
            lambda checked=False: self._batch_archive(ids)
        )

        menu.addAction(advance_action)
        menu.addAction(archive_action)
        self._batch_menu = menu

        menu.exec(
            self.batch_button.mapToGlobal(
                self.batch_button.rect().bottomLeft()
            )
        )

    def _batch_advance_stage(self, missionary_ids):
        from ui.dialogs.batch_stage_advance_dialog import (
            BatchStageAdvanceDialog,
        )

        dialog = BatchStageAdvanceDialog(
            missionary_ids,
            parent=self,
        )

        if dialog.exec() == QDialog.Accepted:
            self._refresh_after_batch(missionary_ids)

    def _batch_archive(self, missionary_ids):
        dialog = BatchArchiveDialog(
            len(missionary_ids),
            parent=self,
        )

        if dialog.exec() != QDialog.Accepted:
            return

        try:
            if dialog.archive_mode == "group":
                package_path = (
                    self.missionary_service
                    .archive_missionaries_as_group(
                        missionary_ids,
                        dialog.group_name,
                    )
                )
            else:
                package_path = None
                self.missionary_service.archive_missionaries(
                    missionary_ids
                )
        except Exception:
            show_message(
                self,
                "Archive Failed",
                "Failed to archive selected missionaries.",
                kind="critical",
            )
            return

        self._refresh_after_batch(missionary_ids)

        if package_path:
            show_message(
                self,
                "Archive Complete",
                f"Created archive package:\n{package_path}",
            )

    def _refresh_after_batch(self, missionary_ids):
        self.load_data()
        self._refresh_open_detail_if_selected(missionary_ids)

        if hasattr(self.main_window, "dashboard_page"):
            self.main_window.dashboard_page.load_data()

        for page_name in ("calendar_page", "reports_page"):
            page = getattr(self.main_window, page_name, None)
            load_data = getattr(page, "load_data", None)
            if callable(load_data):
                load_data()

    def _refresh_open_detail_if_selected(self, missionary_ids):
        detail_page = getattr(self.main_window, "detail_page", None)
        current = getattr(detail_page, "current_missionary", None)
        current_id = getattr(current, "id", None)
        if current_id not in set(missionary_ids or []):
            return

        reload_detail = getattr(detail_page, "_reload_missionary", None)
        if callable(reload_detail):
            reload_detail()

    def _create_group(self):
        selected_ids = self._selected_missionary_ids()

        dialog = CreateMissionaryGroupDialog(
            self.group_service,
            self._all_missionaries,
            parent=self,
            selected_missionary_ids=selected_ids,
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

        if group.get("group_type") == "TEMPORARY_AUTOMATION":
            names = group.get("missionary_names") or []
            detail = (
                "This temporary group was created by an automatic task and "
                "will be removed when that task is completed.\n\n"
            )
            detail += "\n".join(names) if names else "No missionaries linked."
            show_message(
                self,
                "Temporary Group",
                detail,
            )
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

    def retranslate_ui(self):
        self.export_button.setText(tr("export_menu"))
