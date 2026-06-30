import os
import json
import subprocess
import sys
import tempfile
import time

from datetime import date

from pathlib import Path

import fitz

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGridLayout,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QListWidgetItem,
    QFormLayout,
    QPushButton,
    QStackedWidget,
    QSizePolicy,
)

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    Qt,
    QSize,
    QDate,
)

from services.workflow_service import WorkflowService
from services.document_service import DocumentService
from services.missionary_service import MissionaryService
from services.secretary_work_service import SecretaryWorkService
from services.expiration_rules import add_years
from services.residency_service import ResidencyService
from services.document_image_export_service import (
    DocumentImageExportService,
)
from services.thumbnail_service import ThumbnailService
from services.missionary_detail_layout_service import MissionaryDetailLayoutService
from ui.dialogs.ocr_data_view_dialog import OcrDataViewDialog
from ui.dialogs.stage_advance_dialog import StageAdvanceDialog
from ui.dialogs.upload_session_dialog import UploadSessionDialog
from ui.dialogs.office_work_dialogs import TaskDialog
from ui.foundation import (
    BodyLabel,
    DialogFooter,
    MaskDialogBase,
    SectionTitle,
    StatCard,
    SubtitleLabel,
    create_button,
    create_card,
    create_info_badge,
    create_combo_box,
    create_date_picker,
    create_line_edit,
    create_list_widget,
    create_menu,
    create_plain_text_edit,
    create_scroll_area,
    create_text_edit,
    show_message,
    setup_dialog_shell,
    tune_fluent_scrollable,
)
from utils.constants import (
    DOCUMENTS,
    WORKFLOW_STATUSES,
    WORKFLOW_STAGES,
    requires_fbi_document,
    required_documents_for_missionary,
)
from utils.i18n import field_label
from utils.language_helper import ui_text as tr
from utils.logger import logger
from services.workflow_validator import WorkflowValidator
from services.workspace_service import WorkspaceService
from services.workspace_layout import (
    WORKSPACE_GRID_COLUMNS,
    validate_block_layout,
)
from ui.widgets.workspace_layout_editor import WorkspaceLayoutEditor
from ui.widgets.missionary_block_widgets import (
    build_document_card,
    build_empty_state_card,
    build_missing_stage_card,
    build_task_card,
    build_workflow_stage_card,
)

DATE_PLACEHOLDER = QDate(1900, 1, 1)
DATE_EDIT_MAX_WIDTH = 300
OVERVIEW_CONTENT_SPACING = 16
DETAIL_LAYOUT_CANVAS_WIDTH = 1180
DETAIL_LAYOUT_GRID_CELL_WIDTH = DETAIL_LAYOUT_CANVAS_WIDTH / WORKSPACE_GRID_COLUMNS
DETAIL_LAYOUT_GRID_ROW_HEIGHT = 150
DETAIL_LAYOUT_MIN_CARD_WIDTH = 220
DETAIL_LAYOUT_MIN_CARD_HEIGHT = 120
DETAIL_LAYOUT_RESIZE_MARGIN = 14
DETAIL_LAYOUT_CANVAS_PADDING = 8
DETAIL_LAYOUT_PREVIEW_ANIMATION_MS = 110
DETAIL_LAYOUT_COMMIT_ANIMATION_MS = 180
DETAIL_LAYOUT_REBOUND_ANIMATION_MS = 240


DETAIL_LAYOUT_LABELS = {
    "overview": "missionary_detail_tab_overview",
    "workflow": "missionary_detail_workflow_stages",
    "open_tasks": "missionary_detail_open_tasks",
    "documents": "missionary_detail_documents",
    "missing_documents": "missionary_detail_missing_documents",
    "details_summary": "missionary_detail_at_a_glance",
    "details_identity": "missionary_detail_identity",
    "details_credentials": "missionary_detail_credentials",
    "details_legal_timeline": "missionary_detail_legal_timeline",
    "details_residency": "missionary_detail_residency_timeline",
}

DETAIL_LAYOUT_TABS = {
    "overview": "missionary_detail_tab_overview",
    "details": "missionary_detail_tab_details",
}


class MissionaryDetailLayoutDialog(QDialog):
    def __init__(self, layout_payload, parent=None):
        super().__init__(parent)
        self.setObjectName("MissionaryDetailLayoutDialog")
        self.setWindowTitle(tr("missionary_detail_edit_layout"))
        self.resize(980, 700)
        self.layout_payload = json.loads(json.dumps(layout_payload or {}))

        root = QVBoxLayout()
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)
        self.setLayout(root)

        title = SubtitleLabel(tr("missionary_detail_edit_layout"))
        title.setObjectName("MissionaryDetailLayoutTitle")
        root.addWidget(title)

        helper = QLabel(tr("missionary_detail_edit_layout_hint"))
        helper.setObjectName("MutedText")
        helper.setWordWrap(True)
        root.addWidget(helper)

        self.current_layout_tab = "overview"
        self.tab_combo = create_combo_box("MissionaryDetailLayoutTabCombo")
        for tab_key, label_key in DETAIL_LAYOUT_TABS.items():
            self.tab_combo.addItem(tr(label_key), tab_key)
        self.tab_combo.currentIndexChanged.connect(self._switch_layout_tab)
        root.addWidget(self.tab_combo)

        self.editor = WorkspaceLayoutEditor(self._block_label)
        self.editor.setObjectName("MissionaryDetailLayoutEditor")
        self.editor.allow_structure_changes = False
        self.editor.set_workspace(self._layout_for_tab(self.current_layout_tab))
        self.editor.select_block(None)
        root.addWidget(self.editor, stretch=1)

        footer = DialogFooter()
        reset_btn = create_button(tr("missionary_detail_reset_layout"), "secondary")
        cancel_btn = create_button(tr("missionary_detail_cancel"), "secondary")
        save_btn = create_button(tr("settings_save"), "primary")
        reset_btn.clicked.connect(self._reset_to_default)
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept)
        footer.add_action(reset_btn)
        footer.add_action(cancel_btn)
        footer.add_action(save_btn)
        root.addWidget(footer)

    @staticmethod
    def _block_label(block_type):
        return tr(DETAIL_LAYOUT_LABELS.get(block_type, block_type))

    def updated_layout(self):
        self._store_current_tab()
        return self.layout_payload

    def _reset_to_default(self):
        self.layout_payload = MissionaryDetailLayoutService.default_layout()
        self.editor.set_workspace(self._layout_for_tab(self.current_layout_tab))
        self.editor.select_block(None)

    def _layout_for_tab(self, tab_key):
        return {
            "id": f"missionary_detail_{tab_key}",
            "name": tr(
                DETAIL_LAYOUT_TABS.get(
                    tab_key,
                    "missionary_detail_edit_layout",
                )
            ),
            "blocks": [
                json.loads(json.dumps(block))
                for block in self.layout_payload.get("blocks", [])
                if block.get("tab", "overview") == tab_key
            ],
        }

    def _store_current_tab(self):
        current = self.editor.workspace or {"blocks": []}
        current_blocks = []
        for block in current.get("blocks", []):
            next_block = json.loads(json.dumps(block))
            next_block["tab"] = self.current_layout_tab
            current_blocks.append(next_block)
        self.layout_payload["blocks"] = [
            block
            for block in self.layout_payload.get("blocks", [])
            if block.get("tab", "overview") != self.current_layout_tab
        ] + current_blocks

    def _switch_layout_tab(self, *args):
        _ = args
        next_tab = self.tab_combo.currentData() or "overview"
        if next_tab == self.current_layout_tab:
            return
        self._store_current_tab()
        self.current_layout_tab = next_tab
        self.editor.set_workspace(self._layout_for_tab(next_tab))
        self.editor.select_block(None)
WORKFLOW_LIST_MIN_HEIGHT = 220
DOCUMENTS_LIST_MIN_HEIGHT = 340
MISSING_LIST_MIN_HEIGHT = 260
TIMELINE_LIST_MIN_HEIGHT = 260
EMPTY_STATE_MIN_HEIGHT = 80
WORKFLOW_CARD_MIN_HEIGHT = 84
DOCUMENT_CARD_MIN_HEIGHT = 104
MISSING_CARD_MIN_HEIGHT = 84
MISSIONARY_DETAIL_SCROLL_STEP = 16
AUTO_DERIVED_VISA_SOURCE_LABEL = "Auto-derived from arrival date"
INTERPOL_PACKET_DOCUMENT_TYPES = [
    "TAM",
    "PASSPORT",
    "PAGO_INTERPOL",
    "CONSTANCIA_DE_CITA_INTERPOL",
]
FBI_INTERPOL_PACKET_DOCUMENT_TYPES = [
    "TAM",
    "PASSPORT",
    "FBI",
    "PAGO_INTERPOL",
    "CONSTANCIA_DE_CITA_INTERPOL",
]

STAGE_TRANSLATION_KEYS = {
    "INTERPOL": "missionary_detail_stage_interpol",
    "CARNET DE EXTRANJERIA": "missionary_detail_stage_carnet_de_extranjeria",
    "PRORROGA": "missionary_detail_stage_prorroga",
    "CANCELACION": "missionary_detail_stage_cancelacion",
}

WORKFLOW_STATUS_TRANSLATION_KEYS = {
    "NOT STARTED": "missionary_detail_status_not_started",
    "IN PROGRESS": "missionary_detail_status_in_progress",
    "WAITING": "missionary_detail_status_waiting",
    "COMPLETED": "missionary_detail_status_completed",
    "BLOCKED": "missionary_detail_status_blocked",
}

DOCUMENT_TRANSLATION_KEYS = {
    "PHOTO": "missionary_detail_doc_photo",
    "PASSPORT": "missionary_detail_doc_passport",
    "FBI": "missionary_detail_doc_fbi",
    "TAM": "missionary_detail_doc_tam",
    "PAGO_INTERPOL": "missionary_detail_doc_pago_interpol",
    "CONSTANCIA_DE_CITA_INTERPOL": "missionary_detail_doc_constancia_de_cita_interpol",
    "FICHA_DE_CANJE_INTERNACIONAL": "missionary_detail_doc_ficha_de_canje_internacional",
    "PAGO_CARNE_DE_EXTRANJERIA": "missionary_detail_doc_pago_carne_de_extranjeria",
    "CONSTANCIA_DE_CITA_BIOMETRICO": "missionary_detail_doc_constancia_de_cita_biometrico",
    "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA": "missionary_detail_doc_constancia_de_tramite_carne_de_extranjeria",
    "CITA_RECOJO": "missionary_detail_doc_cita_recojo",
    "CARNE_DE_EXTRANJERIA": "missionary_detail_doc_carne_de_extranjeria",
    "PAGO_PRORROGA": "missionary_detail_doc_pago_prorroga",
    "CARTA_MINJUS": "missionary_detail_doc_carta_minjus",
    "DECLARACION_JURADA": "missionary_detail_doc_declaracion_jurada",
    "CONSTANCIA_DE_PRORROGA": "missionary_detail_doc_constancia_de_prorroga",
    "APROBACION_DE_PRORROGA": "missionary_detail_doc_aprobacion_de_prorroga",
    "PAGO_CANCELACION_DE_RESIDENCIA": "missionary_detail_doc_pago_cancelacion_de_residencia",
    "CONSTANCIA_CANCELACION": "missionary_detail_doc_constancia_cancelacion",
    "OTHER": "missionary_detail_doc_other",
}

WORKFLOW_STATUS_TONES = {
    "NOT STARTED": "muted",
    "IN PROGRESS": "info",
    "WAITING": "success",
    "COMPLETED": "success",
    "BLOCKED": "danger",
}

EDITABLE_DATE_FIELDS = [
    "arrival_date",
    "visa_expiration",
    "date_of_birth",
    "passport_expiration",
    "residency_expiration",
    "carnet_issue_date",
    "cancelacion_date",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
]


def open_document_with_default_app(file_path):
    file_path = str(file_path)

    if sys.platform.startswith("win"):
        os.startfile(file_path)
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", file_path])
        return

    subprocess.Popen(["xdg-open", file_path])


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _set_scroll_step(widget, step=MISSIONARY_DETAIL_SCROLL_STEP):
    for bar_name in ("verticalScrollBar", "horizontalScrollBar"):
        bar_getter = getattr(widget, bar_name, None)
        if callable(bar_getter):
            bar = bar_getter()
            if bar is not None and hasattr(bar, "setSingleStep"):
                bar.setSingleStep(step)


def _stage_display_name(stage):
    if not stage:
        return tr("missionary_detail_not_assigned")
    return tr(STAGE_TRANSLATION_KEYS.get(stage, stage))


def _workflow_status_label(status):
    if not status:
        return tr("missionary_detail_unknown")
    return tr(
        WORKFLOW_STATUS_TRANSLATION_KEYS.get(
            status,
            status.title(),
        )
    )


def _document_label(document_type):
    if not document_type:
        return tr("missionary_detail_unknown")
    key = DOCUMENT_TRANSLATION_KEYS.get(document_type)
    if key:
        return tr(key)
    return DOCUMENTS.get(document_type, {}).get("label", document_type)


def _workflow_status_tone(status):
    return WORKFLOW_STATUS_TONES.get(status, "muted")


def _format_datetime(value):
    if not value:
        return None
    try:
        return value.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        return str(value)


def _parse_field_sources(field_sources):
    if not field_sources:
        return {}

    try:
        parsed = json.loads(field_sources)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._placeholder = tr("missionary_detail_not_set")
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setWordWrap(False)
        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )
        self.setText(text)

    def setText(self, text):
        self._full_text = "" if text is None else str(text)
        self.setToolTip(self._full_text)
        self._refresh_elided_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_elided_text()

    def _refresh_elided_text(self):
        if not self._full_text:
            super().setText(self._placeholder)
            return

        width = self.contentsRect().width()
        if width <= 0:
            width = self.sizeHint().width()

        display = self.fontMetrics().elidedText(
            self._full_text,
            Qt.ElideRight,
            max(0, width),
        )
        super().setText(display or self._full_text)


def _refresh_widget_style(widget):
    if widget is None:
        return
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class MissionaryDetailPage(QWidget):
    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("MissionaryDetailPage")

        self.main_window = main_window

        logger.info("Initializing MissionaryDetailPage")

        self.workflow_service = WorkflowService()

        self.document_service = DocumentService()

        self.missionary_service = MissionaryService()

        self.secretary_work_service = SecretaryWorkService()

        self.residency_service = ResidencyService()

        self.workflow_validator = WorkflowValidator()
        self.workspace_service = (
            getattr(main_window, "workspace_service", None)
            if main_window
            else None
        ) or WorkspaceService()
        self.detail_layout_service = MissionaryDetailLayoutService()

        self.thumb_service = ThumbnailService()

        self.image_export_service = DocumentImageExportService()

        self._document_data = []
        self._date_edits = {}
        self._text_edits = {}
        self._date_empty_overlays = {}
        self._date_source_labels = {}
        self._credential_source_labels = {}
        self._date_empty_on_load = set()
        self._residency_timeline_labels = {}
        self._translated_labels = []
        self._layout_editing = False
        self._layout_edit_payload = None
        self._layout_preview_payload = None
        self._layout_drag_state = None
        self._layout_drag_targets = set()
        self._layout_drag_accepts = {}
        self._layout_animation_group = None

        self.setup_ui()

    def _build_detail_card(
        self,
        title,
        subtitle=None,
        title_key=None,
        subtitle_key=None,
    ):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        card.setLayout(layout)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("SectionHeader")
        layout.addWidget(title_lbl)
        if title_key:
            self._translated_labels.append((title_lbl, title_key))

        if subtitle:
            subtitle_lbl = QLabel(subtitle)
            subtitle_lbl.setObjectName("MutedText")
            subtitle_lbl.setWordWrap(True)
            layout.addWidget(subtitle_lbl)
            if subtitle_key:
                self._translated_labels.append((subtitle_lbl, subtitle_key))

        return card, layout

    def _build_field_block(
        self,
        label_text,
        value_widget,
        source_widget=None,
        reserve_source_space=False,
    ):
        field_widget = QWidget()
        field_layout = QVBoxLayout()
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(3)
        field_widget.setLayout(field_layout)

        label = QLabel(label_text)
        label.setObjectName("MutedText")
        field_layout.addWidget(label)

        field_layout.addWidget(value_widget)

        if source_widget is not None:
            field_layout.addWidget(source_widget)
        elif reserve_source_space:
            spacer = QWidget()
            spacer.setFixedHeight(16)
            field_layout.addWidget(spacer)

        return field_widget

    def _build_value_label(self, text=None, *, elided=False):
        text = tr("missionary_detail_not_set") if text is None else text
        label = ElidedLabel(text) if elided else QLabel(text)
        label.setObjectName("ReadOnlyValue")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if not elided:
            label.setWordWrap(True)
        label.setProperty(
            "state",
            "empty" if text == tr("missionary_detail_not_set") else "filled",
        )
        return label

    def _build_source_label(self):
        lbl = create_info_badge("")
        lbl.setObjectName("SourceBadge")
        lbl.setProperty("source_kind", "document")
        lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        lbl.setVisible(False)
        return lbl

    def _build_badge_chip(self, text, object_name="SummaryBadge"):
        badge = QLabel(text)
        badge.setObjectName(object_name)
        badge.setProperty("tone", "subtle")
        badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        badge.setTextInteractionFlags(Qt.TextSelectableByMouse)
        badge.adjustSize()
        return badge

    def _build_date_picker_shell(self, picker):
        shell = QWidget()
        shell_layout = QGridLayout()
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setHorizontalSpacing(0)
        shell_layout.setVerticalSpacing(0)
        shell.setLayout(shell_layout)
        shell.setFixedHeight(34)
        shell.setFixedWidth(DATE_EDIT_MAX_WIDTH)
        shell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        overlay = QLabel(tr("missionary_detail_not_set"))
        overlay.setObjectName("DateEmptyOverlay")
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        overlay.setVisible(False)
        overlay.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        overlay.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        shell_layout.addWidget(picker, 0, 0, alignment=Qt.AlignLeft)
        shell_layout.addWidget(overlay, 0, 0, alignment=Qt.AlignLeft)

        self._date_empty_overlays[picker] = overlay
        return shell

    def _configure_detail_date_picker(self, picker):
        picker.setObjectName("MissionaryDetailDatePicker")
        picker.setDate(DATE_PLACEHOLDER)
        picker.setFixedWidth(DATE_EDIT_MAX_WIDTH)
        if hasattr(picker, "setMinimumDate"):
            picker.setMinimumDate(DATE_PLACEHOLDER)
        if hasattr(picker, "setSpecialValueText"):
            picker.setSpecialValueText(tr("missionary_detail_not_set"))
        if hasattr(picker, "setDisplayFormat"):
            picker.setDisplayFormat("MMM d, yyyy")
        if hasattr(picker, "setSizePolicy"):
            picker.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        if hasattr(picker, "dateChanged"):
            picker.dateChanged.connect(
                lambda *_args, p=picker: self._sync_date_picker_state(p)
            )

    def _set_fluent_date_empty_text(self, picker, is_empty):
        if (
            hasattr(picker, "getDate")
            and hasattr(picker, "setText")
            and not hasattr(picker, "calendarPopup")
        ):
            if is_empty:
                picker.setText(tr("missionary_detail_not_set"))
            else:
                qd = picker.getDate()
                date_format = (
                    picker.getDateFormat()
                    if hasattr(picker, "getDateFormat")
                    else "MMM d, yyyy"
                )
                picker.setText(qd.toString(date_format))
            _refresh_widget_style(picker)
            return True

        buttons = [
            child
            for child in picker.children()
            if child.objectName() == "pickerButton"
            and hasattr(child, "setText")
        ]
        if len(buttons) < 3:
            return False

        if is_empty:
            buttons[0].setText(tr("missionary_detail_not_set"))
            buttons[1].setText("")
            buttons[2].setText("")
        else:
            qd = (
                picker.getDate()
                if hasattr(picker, "getDate")
                else picker.date()
            )
            buttons[0].setText(qd.toString("MMMM"))
            buttons[1].setText(str(qd.day()))
            buttons[2].setText(str(qd.year()))

        for button in buttons:
            button.adjustSize()
            _refresh_widget_style(button)
        return True

    def _sync_date_picker_state(self, picker):
        qd = (
            picker.getDate()
            if hasattr(picker, "getDate")
            else picker.date()
        )
        self._set_date_picker_state(picker, qd == DATE_PLACEHOLDER)

    def _set_value_text(self, widget, text, empty_text=None):
        if widget is None:
            return
        empty_text = empty_text or tr("missionary_detail_not_set")
        value = empty_text if text in {None, ""} else str(text)
        if hasattr(widget, "setText"):
            widget.setText(value)
        widget.setProperty("state", "empty" if value == empty_text else "filled")
        _refresh_widget_style(widget)

    def _set_source_badge(self, widget, text, kind="document"):
        if widget is None:
            return
        display = str(text or "").strip()
        widget.setProperty("source_kind", kind)
        if display:
            if display == AUTO_DERIVED_VISA_SOURCE_LABEL:
                display = tr("missionary_detail_derived")
            widget.setText(display)
            widget.setVisible(True)
        else:
            widget.setText("")
            widget.setVisible(False)
        widget.adjustSize()
        _refresh_widget_style(widget)

    def _set_date_picker_state(self, picker, is_empty):
        if picker is None:
            return
        picker.setProperty("state", "empty" if is_empty else "filled")
        overlay = self._date_empty_overlays.get(picker)
        handled_by_fluent = self._set_fluent_date_empty_text(
            picker,
            is_empty,
        )
        if overlay is not None:
            if handled_by_fluent:
                overlay.setVisible(False)
            else:
                overlay.setVisible(is_empty)
        _refresh_widget_style(picker)

    def _update_summary_strip(self, missionary):
        if not missionary:
            return

        birthdate = getattr(missionary, "date_of_birth", None)
        folder_path = getattr(missionary, "folder_path", None)
        folder_state = (
            tr("missionary_detail_set")
            if folder_path
            else tr("missionary_detail_not_set")
        )
        empty = tr("missionary_detail_not_set")

        summary_values = {
            "summary_name_chip": tr(
                "missionary_detail_name_chip",
                value=getattr(missionary, "full_name", "—") or "—",
            ),
            "summary_stage_chip": tr(
                "missionary_detail_stage_chip",
                value=_stage_display_name(
                    getattr(missionary, "current_stage", None)
                ),
            ),
            "summary_nationality_chip": tr(
                "missionary_detail_nationality_chip",
                value=getattr(missionary, "nationality", None) or empty,
            ),
            "summary_passport_chip": tr(
                "missionary_detail_passport_chip",
                value=getattr(missionary, "passport_number", None) or empty,
            ),
            "summary_carnet_chip": tr(
                "missionary_detail_carnet_chip",
                value=getattr(missionary, "carnet_number", None) or empty,
            ),
            "summary_birthdate_chip": (
                tr(
                    "missionary_detail_birthdate_chip",
                    value=birthdate.strftime("%b %d, %Y"),
                )
                if birthdate
                else tr("missionary_detail_birthdate_chip", value=empty)
            ),
            "summary_folder_chip": tr(
                "missionary_detail_folder_chip",
                value=folder_state,
            ),
        }

        for attr, value in summary_values.items():
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "setText"):
                widget.setText(value)
                widget.adjustSize()

    # ==========================================
    # UI SETUP
    # ==========================================

    def setup_ui(self):
        main_layout = QVBoxLayout()

        main_layout.setContentsMargins(0, 0, 0, 0)

        main_layout.setSpacing(0)

        self.setLayout(main_layout)

        # ==========================================
        # Page Header
        # ==========================================

        header = create_card(object_name="MissionaryDetailTopBar")
        header.setObjectName("MissionaryDetailTopBar")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(
            12, 10, 16, 10
        )

        header_layout.setSpacing(12)

        header.setLayout(header_layout)

        name_stage = QVBoxLayout()

        name_stage.setSpacing(4)

        self.name_label = QLabel("-")

        self.name_label.setObjectName("MissionaryDetailTitle")

        self.stage_badge = QLabel("")

        self.stage_badge.setObjectName("StageBadge")

        name_stage.addWidget(self.name_label)

        name_stage.addWidget(
            self.stage_badge,
            alignment=Qt.AlignLeft,
        )

        header_layout.addLayout(name_stage)

        header_layout.addStretch()

        self.advance_button = create_button(
            tr("missionary_detail_advance_stage"),
            "success",
        )

        self.advance_button.setObjectName(
            "AdvanceButton"
        )

        self.advance_button.clicked.connect(
            self._advance_stage
        )

        self.edit_layout_button = create_button(
            tr("missionary_detail_edit_layout"),
            "secondary",
        )
        self.edit_layout_button.clicked.connect(self._edit_layout)

        self.save_layout_button = create_button(
            tr("settings_save"),
            "primary",
        )
        self.save_layout_button.clicked.connect(self._save_layout_edit)
        self.save_layout_button.setVisible(False)

        self.cancel_layout_button = create_button(
            tr("missionary_detail_cancel"),
            "secondary",
        )
        self.cancel_layout_button.clicked.connect(self._cancel_layout_edit)
        self.cancel_layout_button.setVisible(False)

        self.reset_layout_button = create_button(
            tr("missionary_detail_reset_layout"),
            "secondary",
        )
        self.reset_layout_button.clicked.connect(self._reset_layout_edit)
        self.reset_layout_button.setVisible(False)

        self.actions_button = create_button(
            tr("missionary_detail_actions"),
            "secondary",
        )

        self.actions_menu = create_menu(
            "",
            self.actions_button,
        )
        self.print_interpol_packet_action = QAction(
            tr("missionary_detail_print_interpol_packet"),
            self.actions_menu,
        )
        self.actions_menu.addAction(
            self.print_interpol_packet_action
        )
        self.print_interpol_packet_action.triggered.connect(
            self._print_interpol_packet
        )
        self.workspace_menu = create_menu(
            tr("missionary_detail_open_workspace"),
            self.actions_menu,
        )
        self.actions_menu.addMenu(self.workspace_menu)
        self.refresh_workspace_actions()
        self.actions_button.setMenu(self.actions_menu)

        self.delete_button = create_button(
            tr("missionary_detail_delete_missionary"),
            "danger",
        )

        self.delete_button.clicked.connect(
            self.delete_missionary
        )

        header_layout.addWidget(self.advance_button)

        header_layout.addWidget(self.edit_layout_button)

        header_layout.addWidget(self.reset_layout_button)

        header_layout.addWidget(self.cancel_layout_button)

        header_layout.addWidget(self.save_layout_button)

        header_layout.addWidget(self.actions_button)

        header_layout.addWidget(self.delete_button)

        main_layout.addWidget(header)

        self.layout_edit_banner = QFrame()
        self.layout_edit_banner.setObjectName("MissionaryDetailLayoutEditBanner")
        self.layout_edit_banner.setAttribute(Qt.WA_StyledBackground, True)
        self.layout_edit_banner.setVisible(False)
        layout_edit_banner_layout = QHBoxLayout()
        layout_edit_banner_layout.setContentsMargins(16, 10, 16, 10)
        layout_edit_banner_layout.setSpacing(10)
        self.layout_edit_banner.setLayout(layout_edit_banner_layout)

        self.layout_edit_banner_title = QLabel(
            tr("missionary_detail_layout_editing_title")
        )
        self.layout_edit_banner_title.setObjectName(
            "MissionaryDetailLayoutEditBannerTitle"
        )
        self.layout_edit_banner_hint = QLabel(
            tr("missionary_detail_layout_editing_hint")
        )
        self.layout_edit_banner_hint.setObjectName(
            "MissionaryDetailLayoutEditBannerHint"
        )
        self.layout_edit_banner_hint.setWordWrap(True)
        layout_edit_banner_layout.addWidget(self.layout_edit_banner_title)
        layout_edit_banner_layout.addWidget(
            self.layout_edit_banner_hint,
            stretch=1,
        )
        main_layout.addWidget(self.layout_edit_banner)

        # ==========================================
        # Auto-advance banner (hidden by default)
        # ==========================================

        self.advance_banner = create_card(
            object_name="SuccessBanner"
        )
        self.advance_banner.setObjectName("SuccessBanner")

        self.advance_banner.setVisible(False)

        banner_layout = QHBoxLayout()

        banner_layout.setContentsMargins(
            18, 10, 18, 10
        )

        banner_layout.setSpacing(12)

        self.advance_banner.setLayout(
            banner_layout
        )

        banner_icon = QLabel("OK")

        banner_icon.setObjectName("SuccessIcon")

        self.banner_text = QLabel(
            tr("missionary_detail_advance_ready_generic")
        )

        self.banner_text.setObjectName("SuccessBannerText")

        self.banner_now_btn = create_button(
            tr("missionary_detail_advance_now"),
            "success",
            fixed_height=30,
        )

        self.banner_now_btn.clicked.connect(
            self._advance_stage
        )

        banner_layout.addWidget(banner_icon)

        banner_layout.addWidget(self.banner_text)

        banner_layout.addStretch()

        banner_layout.addWidget(self.banner_now_btn)

        main_layout.addWidget(self.advance_banner)

        # ==========================================
        # Static tabs
        # ==========================================

        self.tab_stack = QStackedWidget()
        self._tab_route_indexes = {}
        self.tab_buttons = {}
        self.tab_button_group = QButtonGroup(self)
        self.tab_button_group.setExclusive(True)
        self.tab_stack.setObjectName("StaticTabStack")

        self.tab_bar = QFrame()
        self.tab_bar.setObjectName("MissionaryDetailTopTabs")
        self.tab_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.tab_bar_layout = QHBoxLayout()
        self.tab_bar_layout.setContentsMargins(12, 0, 16, 0)
        self.tab_bar_layout.setSpacing(8)
        self.tab_bar.setLayout(self.tab_bar_layout)
        main_layout.addWidget(self.tab_bar)

        self._build_overview_tab()

        self._build_details_tab_dashboard()

        self._build_notes_tab()

        self._build_timeline_tab()

        self.tab_bar_layout.addStretch()
        self._select_static_tab("overview")

        main_layout.addWidget(
            self.tab_stack, stretch=1
        )

        # Connections
        self.workflow_list.itemDoubleClicked.connect(
            self.change_workflow_status
        )

    def _add_static_tab(self, route_key, title, widget):
        index = self.tab_stack.addWidget(widget)
        self._tab_route_indexes[route_key] = index
        button = QPushButton(title)
        button.setObjectName("MissionaryDetailTopTab")
        button.setCheckable(True)
        button.setFixedHeight(35)
        button.clicked.connect(
            lambda checked=False, key=route_key:
            self._select_static_tab(key)
        )
        self.tab_button_group.addButton(button)
        self.tab_buttons[route_key] = button
        self.tab_bar_layout.addWidget(button)
        return index

    def _select_static_tab(self, route_key):
        index = self._tab_route_indexes.get(route_key)
        if index is not None:
            self.tab_stack.setCurrentIndex(index)
        for tab_key, button in self.tab_buttons.items():
            active = tab_key == route_key
            button.setChecked(active)
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _build_overview_tab(self):
        overview_tab = QWidget()

        self._add_static_tab(
            "overview",
            tr("missionary_detail_tab_overview"),
            overview_tab,
        )

        tab_layout = QVBoxLayout()

        tab_layout.setContentsMargins(0, 0, 0, 0)

        overview_tab.setLayout(tab_layout)

        scroll = create_scroll_area(single_direction=True)
        scroll.setObjectName("PageSurface")
        tune_fluent_scrollable(scroll)

        content = QWidget()

        content.setObjectName("PageSurface")

        content_layout = QVBoxLayout()

        content_layout.setContentsMargins(
            20, 18, 20, 20
        )

        content_layout.setSpacing(OVERVIEW_CONTENT_SPACING)

        content.setLayout(content_layout)

        self.overview_layout_canvas = QWidget()
        self.overview_layout_canvas.setObjectName("MissionaryDetailLayoutCanvas")
        self.overview_layout_canvas.setMinimumWidth(DETAIL_LAYOUT_CANVAS_WIDTH)
        content_layout.addWidget(self.overview_layout_canvas)

        self._overview_sections = {
            "overview": self._build_summary_section(),
            "workflow": self._build_workflow_section(),
            "open_tasks": self._build_open_tasks_section(),
            "documents": self._build_documents_overview_section(),
            "missing_documents": self._build_missing_documents_overview_section(),
        }
        self._apply_overview_layout()

        content_layout.addStretch()

        scroll.setWidget(content)

        tab_layout.addWidget(scroll)

    def _apply_overview_layout(self):
        self._apply_layout_to_canvas(
            self.overview_layout_canvas,
            self._overview_sections,
            "overview",
        )

    def _apply_details_layout(self):
        self._apply_layout_to_canvas(
            self.details_layout_canvas,
            self._details_sections,
            "details",
        )

    def _apply_layout_to_canvas(self, canvas, sections, tab_key):
        layout_payload = self._current_detail_layout_payload()
        max_bottom = 0
        used_sections = set()
        geometry_updates = []
        for block in layout_payload.get("blocks", []):
            if block.get("visible") is False:
                continue
            if block.get("tab", "overview") != tab_key:
                continue
            section_key = block.get("type") or block.get("id")
            section = sections.get(section_key)
            if section is None:
                continue
            self._mark_layout_section(section, section_key, tab_key)
            rect = self._free_rect_for_block(block)
            max_bottom = max(max_bottom, rect.bottom())
            used_sections.add(section_key)
            section.setParent(canvas)
            geometry_updates.append((section, rect))
            section.show()

        next_y = max_bottom + OVERVIEW_CONTENT_SPACING
        for section_key, section in sections.items():
            if section_key in used_sections:
                continue
            self._mark_layout_section(section, section_key, tab_key)
            rect = QRect(
                DETAIL_LAYOUT_CANVAS_PADDING,
                max(DETAIL_LAYOUT_CANVAS_PADDING, next_y),
                DETAIL_LAYOUT_CANVAS_WIDTH - (DETAIL_LAYOUT_CANVAS_PADDING * 2),
                DETAIL_LAYOUT_GRID_ROW_HEIGHT,
            )
            section.setParent(canvas)
            section.show()
            next_y = rect.bottom() + OVERVIEW_CONTENT_SPACING
            max_bottom = max(max_bottom, rect.bottom())
            geometry_updates.append((section, rect))

        canvas.setMinimumHeight(
            max(max_bottom + DETAIL_LAYOUT_CANVAS_PADDING, 320)
        )
        self._apply_layout_section_geometries(geometry_updates)
        self._refresh_layout_drag_targets()

    def _current_detail_layout_payload(self):
        if (
            getattr(self, "_layout_editing", False)
            and getattr(self, "_layout_preview_payload", None)
        ):
            return self._layout_preview_payload
        if (
            getattr(self, "_layout_editing", False)
            and getattr(self, "_layout_edit_payload", None)
        ):
            return self._layout_edit_payload
        return self.detail_layout_service.get_layout()

    def _apply_layout_section_geometries(self, geometry_updates):
        if not geometry_updates:
            return
        if not getattr(self, "_layout_editing", False):
            for section, rect in geometry_updates:
                section.setGeometry(rect)
            return
        if not hasattr(self, "_layout_animation_group"):
            for section, rect in geometry_updates:
                section.setGeometry(rect)
            return
        duration = getattr(
            self,
            "_layout_animation_duration",
            DETAIL_LAYOUT_PREVIEW_ANIMATION_MS,
        )
        easing = getattr(
            self,
            "_layout_animation_easing",
            QEasingCurve.OutCubic,
        )
        self._animate_layout_sections(
            geometry_updates,
            duration,
            easing,
        )

    def _animate_layout_sections(self, geometry_updates, duration, easing):
        changes = []
        for section, rect in geometry_updates:
            if section.geometry() == rect:
                continue
            if not section.isVisible() or section.geometry() == QRect(0, 0, 640, 480):
                section.setGeometry(rect)
                continue
            changes.append((section, rect))
        if not changes:
            return

        group = getattr(self, "_layout_animation_group", None)
        if group is not None:
            group.stop()
        group = QParallelAnimationGroup(self)
        self._layout_animation_group = group
        for section, rect in changes:
            animation = QPropertyAnimation(section, b"geometry", group)
            animation.setDuration(duration)
            animation.setEasingCurve(easing)
            animation.setStartValue(section.geometry())
            animation.setEndValue(rect)
            group.addAnimation(animation)
        group.finished.connect(
            lambda: setattr(self, "_layout_animation_group", None)
        )
        group.start()

    def _stop_layout_animation(self):
        group = getattr(self, "_layout_animation_group", None)
        if group is not None:
            group.stop()
            self._layout_animation_group = None

    def _free_rect_for_block(self, block):
        free_layout = block.get("free_layout")
        if isinstance(free_layout, dict):
            rect = QRect(
                self._as_int(
                    free_layout.get("x"),
                    DETAIL_LAYOUT_CANVAS_PADDING,
                ),
                self._as_int(
                    free_layout.get("y"),
                    DETAIL_LAYOUT_CANVAS_PADDING,
                ),
                self._as_int(
                    free_layout.get("width"),
                    DETAIL_LAYOUT_MIN_CARD_WIDTH,
                ),
                self._as_int(
                    free_layout.get("height"),
                    DETAIL_LAYOUT_MIN_CARD_HEIGHT,
                ),
            )
            return self._bounded_free_rect(rect)

        layout = validate_block_layout(block)
        rect = QRect(
            int(layout["col"] * DETAIL_LAYOUT_GRID_CELL_WIDTH)
            + DETAIL_LAYOUT_CANVAS_PADDING,
            int(layout["row"] * DETAIL_LAYOUT_GRID_ROW_HEIGHT)
            + DETAIL_LAYOUT_CANVAS_PADDING,
            int(
                layout["col_span"] * DETAIL_LAYOUT_GRID_CELL_WIDTH
                - OVERVIEW_CONTENT_SPACING
            ),
            int(
                layout["row_span"] * DETAIL_LAYOUT_GRID_ROW_HEIGHT
                - OVERVIEW_CONTENT_SPACING
            ),
        )
        rect = self._bounded_free_rect(rect)
        block["free_layout"] = self._free_layout_from_rect(rect)
        return rect

    def _bounded_free_rect(self, rect):
        width = max(DETAIL_LAYOUT_MIN_CARD_WIDTH, int(rect.width()))
        height = max(DETAIL_LAYOUT_MIN_CARD_HEIGHT, int(rect.height()))
        max_x = max(
            DETAIL_LAYOUT_CANVAS_PADDING,
            DETAIL_LAYOUT_CANVAS_WIDTH - width - DETAIL_LAYOUT_CANVAS_PADDING,
        )
        x = max(DETAIL_LAYOUT_CANVAS_PADDING, min(int(rect.x()), max_x))
        y = max(DETAIL_LAYOUT_CANVAS_PADDING, int(rect.y()))
        return QRect(x, y, width, height)

    def _free_layout_from_rect(self, rect):
        return {
            "x": int(rect.x()),
            "y": int(rect.y()),
            "width": int(rect.width()),
            "height": int(rect.height()),
        }

    def _as_int(self, value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _mark_layout_section(self, section, section_key, tab_key):
        section.setProperty("detail_layout_section_key", section_key)
        section.setProperty("detail_layout_tab_key", tab_key)
        section.setProperty(
            "layout_editing",
            getattr(self, "_layout_editing", False),
        )
        self._refresh_widget_style(section)

    def _refresh_widget_style(self, widget):
        if widget is None:
            return
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _all_layout_sections(self):
        sections = {}
        for attr_name in ("_overview_sections", "_details_sections"):
            sections.update(getattr(self, attr_name, {}) or {})
        return sections

    def _refresh_layout_drag_targets(self):
        if not hasattr(self, "_layout_drag_targets"):
            return
        for widget in list(self._layout_drag_targets):
            try:
                widget.removeEventFilter(self)
                widget.setAcceptDrops(
                    self._layout_drag_accepts.get(widget, False)
                )
                widget.unsetCursor()
            except RuntimeError:
                pass
        self._layout_drag_targets.clear()
        self._layout_drag_accepts.clear()

        for section in self._all_layout_sections().values():
            section.setProperty("layout_editing", self._layout_editing)
            self._refresh_widget_style(section)

        if not self._layout_editing:
            return

        for section in self._all_layout_sections().values():
            widgets = [section] + section.findChildren(QWidget)
            for widget in widgets:
                self._layout_drag_targets.add(widget)
                widget.installEventFilter(self)
                widget.setCursor(Qt.OpenHandCursor)

    def _layout_section_key_for_widget(self, widget):
        cursor = widget
        while cursor is not None:
            section_key = cursor.property("detail_layout_section_key")
            if section_key:
                return section_key
            cursor = cursor.parentWidget()
        return None

    def _layout_tab_key_for_section(self, section_key):
        for block in (self._layout_edit_payload or {}).get("blocks", []):
            if (block.get("type") or block.get("id")) == section_key:
                return block.get("tab", "overview")
        return "overview"

    def _event_global_pos(self, event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def _event_local_pos_for_section(self, obj, event, section):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        return obj.mapTo(section, pos)

    def _layout_resize_handle(self, section, pos):
        margin = DETAIL_LAYOUT_RESIZE_MARGIN
        left = pos.x() <= margin
        right = pos.x() >= section.width() - margin
        top = pos.y() <= margin
        bottom = pos.y() >= section.height() - margin
        if top and left:
            return "nw"
        if top and right:
            return "ne"
        if bottom and left:
            return "sw"
        if bottom and right:
            return "se"
        if left:
            return "w"
        if right:
            return "e"
        if top:
            return "n"
        if bottom:
            return "s"
        return None

    def _cursor_for_layout_handle(self, handle):
        if handle in {"nw", "se"}:
            return Qt.SizeFDiagCursor
        if handle in {"ne", "sw"}:
            return Qt.SizeBDiagCursor
        if handle in {"e", "w"}:
            return Qt.SizeHorCursor
        if handle in {"n", "s"}:
            return Qt.SizeVerCursor
        return Qt.OpenHandCursor

    def eventFilter(self, obj, event):
        if (
            not getattr(self, "_layout_editing", False)
            or obj not in getattr(self, "_layout_drag_targets", set())
        ):
            return super().eventFilter(obj, event)

        section_key = self._layout_section_key_for_widget(obj)
        if not section_key:
            return super().eventFilter(obj, event)
        section = self._all_layout_sections().get(section_key)
        if section is None:
            return super().eventFilter(obj, event)

        event_type = event.type()
        if event_type == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                local_pos = self._event_local_pos_for_section(
                    obj,
                    event,
                    section,
                )
                handle = self._layout_resize_handle(section, local_pos)
                self._layout_drag_state = {
                    "key": section_key,
                    "mode": handle or "move",
                    "global_pos": self._event_global_pos(event),
                    "start_rect": QRect(section.geometry()),
                    "base_payload": json.loads(
                        json.dumps(self._layout_edit_payload or {})
                    ),
                    "moved": False,
                }
                section.raise_()
                obj.setCursor(
                    self._cursor_for_layout_handle(self._layout_drag_state["mode"])
                )
                event.accept()
                return True
            return False

        if event_type == QEvent.MouseMove:
            if self._layout_drag_state and event.buttons() & Qt.LeftButton:
                next_rect = self._layout_rect_for_drag(event)
                if next_rect is not None:
                    start_rect = self._layout_drag_state["start_rect"]
                    if (
                        abs(next_rect.x() - start_rect.x())
                        + abs(next_rect.y() - start_rect.y())
                        + abs(next_rect.width() - start_rect.width())
                        + abs(next_rect.height() - start_rect.height())
                    ) > 3:
                        self._layout_drag_state["moved"] = True
                    self._preview_free_layout(
                        self._layout_drag_state["key"],
                        next_rect,
                    )
                    event.accept()
                    return True
            local_pos = self._event_local_pos_for_section(obj, event, section)
            handle = self._layout_resize_handle(section, local_pos)
            obj.setCursor(self._cursor_for_layout_handle(handle))
            return False

        if event_type == QEvent.MouseButtonRelease:
            if self._layout_drag_state:
                if self._layout_drag_state.get("moved"):
                    self._commit_layout_preview()
                else:
                    self._rebound_layout_preview()
                return True
            return False

        if event_type == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            if self._layout_drag_state or self._layout_preview_payload:
                self._rebound_layout_preview()
                event.accept()
                return True
            return False

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if (
            getattr(self, "_layout_editing", False)
            and event.key() == Qt.Key_Escape
            and (
                getattr(self, "_layout_drag_state", None)
                or getattr(self, "_layout_preview_payload", None)
            )
        ):
            self._rebound_layout_preview()
            event.accept()
            return
        super().keyPressEvent(event)

    def _layout_rect_for_drag(self, event):
        state = self._layout_drag_state
        if not state:
            return None
        delta = self._event_global_pos(event) - state["global_pos"]
        rect = QRect(state["start_rect"])
        mode = state["mode"]
        if mode == "move":
            rect.moveTo(rect.x() + delta.x(), rect.y() + delta.y())
            return self._bounded_free_rect(rect)

        if "e" in mode:
            rect.setRight(rect.right() + delta.x())
        if "s" in mode:
            rect.setBottom(rect.bottom() + delta.y())
        if "w" in mode:
            rect.setLeft(rect.left() + delta.x())
        if "n" in mode:
            rect.setTop(rect.top() + delta.y())
        if rect.width() < DETAIL_LAYOUT_MIN_CARD_WIDTH:
            if "w" in mode:
                rect.setLeft(rect.right() - DETAIL_LAYOUT_MIN_CARD_WIDTH)
            else:
                rect.setWidth(DETAIL_LAYOUT_MIN_CARD_WIDTH)
        if rect.height() < DETAIL_LAYOUT_MIN_CARD_HEIGHT:
            if "n" in mode:
                rect.setTop(rect.bottom() - DETAIL_LAYOUT_MIN_CARD_HEIGHT)
            else:
                rect.setHeight(DETAIL_LAYOUT_MIN_CARD_HEIGHT)
        return self._bounded_free_rect(rect)

    def _preview_free_layout(self, section_key, rect):
        source_payload = (
            self._layout_drag_state.get("base_payload")
            if self._layout_drag_state
            else self._layout_edit_payload
        )
        if not source_payload:
            return False
        self._layout_preview_payload = json.loads(json.dumps(source_payload))
        block = self._layout_block_for_section(
            section_key,
            self._layout_preview_payload,
        )
        if block is None:
            return False
        rect = self._bounded_free_rect(rect)
        block["free_layout"] = self._free_layout_from_rect(rect)
        self._push_overlapping_free_layouts(
            block.get("tab", "overview"),
            section_key,
            self._layout_preview_payload,
        )
        self._apply_current_detail_layouts(
            duration=DETAIL_LAYOUT_PREVIEW_ANIMATION_MS,
            easing=QEasingCurve.OutCubic,
        )
        return True

    def _layout_block_for_section(self, section_key, payload=None):
        payload = payload or self._layout_edit_payload or {}
        for block in payload.get("blocks", []):
            if (block.get("type") or block.get("id")) == section_key:
                return block
        return None

    def _push_overlapping_free_layouts(
        self,
        tab_key,
        moving_section_key,
        payload=None,
    ):
        payload = payload or self._layout_preview_payload or self._layout_edit_payload
        if not payload:
            return
        tab_blocks = [
            block
            for block in payload.get("blocks", [])
            if block.get("tab", "overview") == tab_key
        ]
        rects = {
            (block.get("type") or block.get("id")): self._free_rect_for_block(block)
            for block in tab_blocks
        }
        moving_rect = rects.get(moving_section_key)
        if moving_rect is None:
            return

        displaced = []
        for block in tab_blocks:
            section_key = block.get("type") or block.get("id")
            if section_key == moving_section_key:
                continue
            rect = rects.get(section_key)
            if rect is None:
                continue
            overlaps_x = not (
                rect.right() < moving_rect.left()
                or moving_rect.right() < rect.left()
            )
            if overlaps_x and rect.intersects(moving_rect):
                displaced.append((rect.y(), section_key, block, rect))

        next_y = moving_rect.bottom() + OVERVIEW_CONTENT_SPACING
        for _, _, block, rect in sorted(displaced):
            rect.moveTop(next_y)
            bounded = self._bounded_free_rect(rect)
            block["free_layout"] = self._free_layout_from_rect(bounded)
            next_y = bounded.bottom() + OVERVIEW_CONTENT_SPACING

    def _commit_layout_preview(self):
        if self._layout_preview_payload:
            self._layout_edit_payload = self._layout_preview_payload
        self._layout_preview_payload = None
        self._layout_drag_state = None
        self._apply_current_detail_layouts(
            duration=DETAIL_LAYOUT_COMMIT_ANIMATION_MS,
            easing=QEasingCurve.OutCubic,
        )

    def _rebound_layout_preview(self):
        self._layout_preview_payload = None
        self._layout_drag_state = None
        self._apply_current_detail_layouts(
            duration=DETAIL_LAYOUT_REBOUND_ANIMATION_MS,
            easing=QEasingCurve.OutBack,
        )

    def _apply_current_detail_layouts(
        self,
        duration=DETAIL_LAYOUT_PREVIEW_ANIMATION_MS,
        easing=QEasingCurve.OutCubic,
    ):
        self._layout_animation_duration = duration
        self._layout_animation_easing = easing
        if hasattr(self, "overview_layout_canvas"):
            self._apply_overview_layout()
        if hasattr(self, "details_layout_canvas"):
            self._apply_details_layout()

    def _clear_grid_items(self, grid):
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _build_documents_overview_section(self):
        section = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        section.setLayout(layout)

        self.documents_section_title = SectionTitle(
            tr("missionary_detail_documents")
        )
        layout.addWidget(self.documents_section_title)

        self.docs_helper = QLabel(
            tr("missionary_detail_documents_hint")
        )
        self.docs_helper.setObjectName("MutedText")
        self.docs_helper.setWordWrap(True)
        layout.addWidget(self.docs_helper)

        self.upload_button = create_button(
            tr("missionary_detail_upload_document"),
            "primary",
            fixed_height=30,
        )
        self.upload_button.setMinimumWidth(150)
        self.upload_button.setSizePolicy(
            QSizePolicy.Fixed,
            QSizePolicy.Fixed,
        )

        self.upload_button.clicked.connect(
            self.upload_document
        )

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addWidget(self.upload_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.documents_list = create_list_widget()
        self.documents_list.setIconSize(
            QSize(60, 75)
        )
        self.documents_list.setSpacing(8)
        self.documents_list.setMinimumHeight(
            DOCUMENTS_LIST_MIN_HEIGHT
        )
        tune_fluent_scrollable(self.documents_list)
        _set_scroll_step(self.documents_list)
        self.documents_list.setContextMenuPolicy(
            Qt.CustomContextMenu
        )
        self.documents_list.customContextMenuRequested.connect(
            self._show_doc_context_menu
        )
        self.documents_list.itemDoubleClicked.connect(
            self._open_document_viewer
        )
        layout.addWidget(self.documents_list, stretch=1)
        return section

    def _build_missing_documents_overview_section(self):
        section = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        section.setLayout(layout)

        self.missing_documents_section_title = SectionTitle(
            tr("missionary_detail_missing_documents")
        )
        layout.addWidget(self.missing_documents_section_title)

        self.missing_helper = QLabel(
            tr("missionary_detail_missing_documents_hint")
        )
        self.missing_helper.setObjectName("MutedText")
        self.missing_helper.setWordWrap(True)
        layout.addWidget(self.missing_helper)

        self.missing_documents_list = create_list_widget()
        self.missing_documents_list.setSpacing(8)
        self.missing_documents_list.setMinimumHeight(
            MISSING_LIST_MIN_HEIGHT
        )
        tune_fluent_scrollable(self.missing_documents_list)
        _set_scroll_step(self.missing_documents_list)
        layout.addWidget(self.missing_documents_list, stretch=1)
        return section

    def _build_summary_section(self):
        card = create_card()

        layout = QVBoxLayout()
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(16)
        card.setLayout(layout)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(3)

        self.summary_title_label = QLabel(
            tr("missionary_detail_overview_title")
        )
        self.summary_title_label.setObjectName("PanelTitle")

        title_stack.addWidget(self.summary_title_label)

        header_row.addLayout(title_stack)
        header_row.addStretch()

        self.summary_stage_chip = QLabel(
            tr("missionary_detail_no_missionary_loaded")
        )
        self.summary_stage_chip.setObjectName("StageBadge")
        header_row.addWidget(self.summary_stage_chip)

        layout.addLayout(header_row)

        metrics_grid = QGridLayout()
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(12)
        metrics_grid.setVerticalSpacing(12)

        self.summary_current_stage_card = StatCard(
            "—",
            tr("missionary_detail_current_stage"),
            subtitle=tr("missionary_detail_current_stage_subtitle"),
            color="#0EA5AC",
        )
        self.summary_complete_card = StatCard(
            "0",
            tr("missionary_detail_required_docs_complete"),
            subtitle=tr("missionary_detail_current_stage_docs_subtitle"),
            color="#059669",
        )
        self.summary_missing_card = StatCard(
            "0",
            tr("missionary_detail_required_docs_missing"),
            subtitle=tr("missionary_detail_required_docs_missing_subtitle"),
            color="#DC2626",
        )
        self.summary_upload_card = StatCard(
            "—",
            tr("missionary_detail_last_upload"),
            subtitle=tr("missionary_detail_last_upload_subtitle"),
            color="#7A6EEC",
        )

        metrics_grid.addWidget(self.summary_current_stage_card, 0, 0)
        metrics_grid.addWidget(self.summary_complete_card, 0, 1)
        metrics_grid.addWidget(self.summary_missing_card, 1, 0)
        metrics_grid.addWidget(self.summary_upload_card, 1, 1)

        layout.addLayout(metrics_grid)

        action_card = create_card()
        action_layout = QVBoxLayout()
        action_layout.setContentsMargins(18, 16, 18, 16)
        action_layout.setSpacing(8)
        action_card.setLayout(action_layout)

        self.summary_action_title = QLabel(
            tr("missionary_detail_recommended_next_step")
        )
        self.summary_action_title.setObjectName("SectionHeader")

        self.summary_next_action_label = QLabel(
            tr("missionary_detail_select_missionary_next_step")
        )
        self.summary_next_action_label.setWordWrap(True)

        self.summary_activity_label = QLabel("")
        self.summary_activity_label.setObjectName("MutedText")
        self.summary_activity_label.setWordWrap(True)

        self.summary_tip_label = QLabel(
            tr("missionary_detail_overview_default_tip")
        )
        self.summary_tip_label.setObjectName("MutedText")
        self.summary_tip_label.setWordWrap(True)

        action_layout.addWidget(self.summary_action_title)
        action_layout.addWidget(self.summary_next_action_label)
        action_layout.addWidget(self.summary_activity_label)
        action_layout.addWidget(self.summary_tip_label)

        layout.addWidget(action_card)

        return card

    def _build_workflow_section(self):
        card = create_card()

        layout = QVBoxLayout()
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        card.setLayout(layout)

        self.workflow_section_title = SectionTitle(
            tr("missionary_detail_workflow_stages")
        )
        layout.addWidget(self.workflow_section_title)

        self.workflow_helper = QLabel(
            tr("missionary_detail_workflow_hint")
        )
        self.workflow_helper.setObjectName("MutedText")
        self.workflow_helper.setWordWrap(True)
        layout.addWidget(self.workflow_helper)

        self.workflow_list = create_list_widget()
        self.workflow_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.workflow_list.itemDoubleClicked.connect(
            self.change_workflow_status
        )
        self.workflow_list.setSpacing(8)
        self.workflow_list.setMinimumHeight(
            WORKFLOW_LIST_MIN_HEIGHT
        )
        tune_fluent_scrollable(self.workflow_list)
        _set_scroll_step(self.workflow_list)
        layout.addWidget(self.workflow_list)

        return card

    def _build_details_tab(self):
        details_outer = QWidget()

        self._add_static_tab("details", "Details", details_outer)

        outer_layout = QVBoxLayout()

        outer_layout.setContentsMargins(0, 0, 0, 0)

        details_outer.setLayout(outer_layout)

        scroll = create_scroll_area(single_direction=True)
        tune_fluent_scrollable(scroll)

        details_content = QWidget()

        details_content.setObjectName("PageSurface")

        details_layout = QVBoxLayout()

        details_layout.setContentsMargins(
            20, 18, 20, 20
        )

        details_layout.setSpacing(0)

        details_content.setLayout(details_layout)

        card = create_card()

        form = QFormLayout()

        form.setContentsMargins(20, 18, 20, 20)

        form.setSpacing(14)

        form.setLabelAlignment(Qt.AlignRight)

        card.setLayout(form)

        def make_field():
            lbl = QLabel("-")
            lbl.setObjectName("BodyText")
            return lbl

        def row_label(text):
            lbl = QLabel(text)
            lbl.setObjectName("MutedText")
            return lbl

        self.nationality_label = make_field()
        self.passport_label = make_field()
        self.carnet_number_input = create_line_edit("Carnet Number")
        self._text_edits["carnet_number"] = self.carnet_number_input
        self.tramite_usuario_input = create_line_edit("Tramite Usuario")
        self._text_edits["tramite_usuario"] = self.tramite_usuario_input
        self.tramite_contrasena_input = create_line_edit("Tramite Contrasena")
        self._text_edits["tramite_contrasena"] = self.tramite_contrasena_input
        self.folder_label = make_field()
        self.folder_label.setWordWrap(True)

        form.addRow(
            row_label("Nationality:"),
            self.nationality_label,
        )
        form.addRow(
            row_label("Passport Number:"),
            self.passport_label,
        )
        form.addRow(
            row_label("Carnet Number:"),
            self.carnet_number_input,
        )

        self.birthdate_picker = create_date_picker()
        self.birthdate_picker.setDate(DATE_PLACEHOLDER)
        self.birthdate_picker.setMaximumWidth(DATE_EDIT_MAX_WIDTH)
        self._date_edits["date_of_birth"] = self.birthdate_picker

        birthdate_source_lbl = QLabel("")
        birthdate_source_lbl.setObjectName("MiniMutedText")
        self._date_source_labels["date_of_birth"] = birthdate_source_lbl

        birthdate_widget = QWidget()
        birthdate_layout = QVBoxLayout()
        birthdate_layout.setContentsMargins(0, 0, 0, 0)
        birthdate_layout.setSpacing(2)
        birthdate_widget.setLayout(birthdate_layout)
        birthdate_layout.addWidget(self.birthdate_picker)
        birthdate_layout.addWidget(birthdate_source_lbl)

        form.addRow(
            row_label(f"{field_label('date_of_birth')}:"),
            birthdate_widget,
        )

        credential_rows = [
            (
                "tramite_usuario",
                "Trámite Usuario:",
                self.tramite_usuario_input,
            ),
            (
                "tramite_contrasena",
                "Trámite Contraseña:",
                self.tramite_contrasena_input,
            ),
        ]
        for field_key, label_text, value_label in credential_rows:
            source_lbl = QLabel("")
            source_lbl.setObjectName("MiniMutedText")
            self._credential_source_labels[field_key] = source_lbl

            field_widget = QWidget()
            fw_layout = QVBoxLayout()
            fw_layout.setContentsMargins(0, 0, 0, 0)
            fw_layout.setSpacing(2)
            field_widget.setLayout(fw_layout)
            fw_layout.addWidget(value_label)
            fw_layout.addWidget(source_lbl)

            form.addRow(
                row_label(label_text),
                field_widget,
            )

        for field_key in EDITABLE_DATE_FIELDS:
            if field_key == "date_of_birth":
                continue
            date_picker = create_date_picker()
            date_picker.setDate(DATE_PLACEHOLDER)
            date_picker.setMaximumWidth(DATE_EDIT_MAX_WIDTH)
            self._date_edits[field_key] = date_picker

            source_lbl = QLabel("")
            source_lbl.setObjectName("MiniMutedText")
            self._date_source_labels[field_key] = source_lbl

            field_widget = QWidget()
            fw_layout = QVBoxLayout()
            fw_layout.setContentsMargins(0, 0, 0, 0)
            fw_layout.setSpacing(2)
            field_widget.setLayout(fw_layout)
            fw_layout.addWidget(date_picker)
            fw_layout.addWidget(source_lbl)

            form.addRow(
                row_label(f"{field_label(field_key)}:"),
                field_widget,
            )

        form.addRow(
            row_label("Folder Path:"),
            self.folder_label,
        )

        self.save_dates_btn = create_button(tr("save_details"), "primary")
        self.save_dates_btn.setFixedWidth(160)
        self.save_dates_btn.clicked.connect(self._save_dates)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.save_dates_btn)
        details_layout.addWidget(card)
        details_layout.addWidget(
            self._build_residency_timeline_card()
        )
        details_layout.addLayout(btn_row)

        details_layout.addStretch()

        scroll.setWidget(details_content)

        outer_layout.addWidget(scroll)

    def _build_details_tab_dashboard(self):
        details_outer = QWidget()

        self._add_static_tab(
            "details",
            tr("missionary_detail_tab_details"),
            details_outer,
        )

        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        details_outer.setLayout(outer_layout)

        scroll = create_scroll_area(single_direction=True)
        tune_fluent_scrollable(scroll)

        details_content = QWidget()
        details_content.setObjectName("PageSurface")

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(20, 18, 20, 20)
        content_layout.setSpacing(14)
        details_content.setLayout(content_layout)

        summary_card, summary_layout = self._build_detail_card(
            tr("missionary_detail_at_a_glance"),
            tr("missionary_detail_at_a_glance_subtitle"),
            title_key="missionary_detail_at_a_glance",
            subtitle_key="missionary_detail_at_a_glance_subtitle",
        )
        summary_layout.setSpacing(8)
        self.summary_chip_grid = QGridLayout()
        self.summary_chip_grid.setContentsMargins(0, 0, 0, 0)
        self.summary_chip_grid.setHorizontalSpacing(10)
        self.summary_chip_grid.setVerticalSpacing(8)
        summary_layout.addLayout(self.summary_chip_grid)

        self.summary_name_chip = self._build_badge_chip(
            tr("missionary_detail_name_chip", value="—")
        )
        self.summary_stage_chip = self._build_badge_chip(
            tr("missionary_detail_stage_chip", value="—")
        )
        self.summary_nationality_chip = self._build_badge_chip(
            tr("missionary_detail_nationality_chip", value="—")
        )
        self.summary_passport_chip = self._build_badge_chip(
            tr("missionary_detail_passport_chip", value="—")
        )
        self.summary_carnet_chip = self._build_badge_chip(
            tr("missionary_detail_carnet_chip", value="—")
        )
        self.summary_birthdate_chip = self._build_badge_chip(
            tr("missionary_detail_birthdate_chip", value="—")
        )
        self.summary_folder_chip = self._build_badge_chip(
            tr(
                "missionary_detail_folder_chip",
                value=tr("missionary_detail_not_set"),
            )
        )

        summary_chips = [
            self.summary_name_chip,
            self.summary_stage_chip,
            self.summary_nationality_chip,
            self.summary_passport_chip,
            self.summary_carnet_chip,
            self.summary_birthdate_chip,
            self.summary_folder_chip,
        ]
        for index, chip in enumerate(summary_chips):
            self.summary_chip_grid.addWidget(
                chip,
                index // 6,
                index % 6,
                alignment=Qt.AlignLeft,
            )
        self.summary_chip_grid.setColumnStretch(len(summary_chips), 1)

        self.nationality_label = self._build_value_label()
        self.passport_label = self._build_value_label()
        self.carnet_number_input = create_line_edit(field_label("carnet_number"))
        self._text_edits["carnet_number"] = self.carnet_number_input
        self.tramite_usuario_input = create_line_edit(
            field_label("tramite_usuario")
        )
        self._text_edits["tramite_usuario"] = self.tramite_usuario_input
        self.tramite_contrasena_input = create_line_edit(
            field_label("tramite_contrasena")
        )
        self._text_edits["tramite_contrasena"] = self.tramite_contrasena_input
        self.folder_label = self._build_value_label(elided=True)

        self.birthdate_picker = create_date_picker()
        self._configure_detail_date_picker(self.birthdate_picker)
        self._date_edits["date_of_birth"] = self.birthdate_picker
        birthdate_shell = self._build_date_picker_shell(
            self.birthdate_picker
        )
        birthdate_source_lbl = self._build_source_label()
        self._date_source_labels["date_of_birth"] = birthdate_source_lbl

        identity_card, identity_layout = self._build_detail_card(
            tr("missionary_detail_identity"),
            tr("missionary_detail_identity_subtitle"),
            title_key="missionary_detail_identity",
            subtitle_key="missionary_detail_identity_subtitle",
        )
        identity_grid = QGridLayout()
        identity_grid.setContentsMargins(0, 0, 0, 0)
        identity_grid.setHorizontalSpacing(10)
        identity_grid.setVerticalSpacing(8)
        identity_layout.addLayout(identity_grid)

        identity_grid.addWidget(
            self._build_field_block(
                field_label("nationality"),
                self.nationality_label,
            ),
            0,
            0,
        )
        identity_grid.addWidget(
            self._build_field_block(
                field_label("passport_number"),
                self.passport_label,
            ),
            0,
            1,
        )
        identity_grid.addWidget(
            self._build_field_block(
                field_label("carnet_number"),
                self.carnet_number_input,
            ),
            1,
            0,
        )
        identity_grid.addWidget(
            self._build_field_block(
                field_label("date_of_birth"),
                birthdate_shell,
                birthdate_source_lbl,
            ),
            2,
            0,
        )

        folder_widget = QWidget()
        folder_layout = QVBoxLayout()
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(6)
        folder_widget.setLayout(folder_layout)
        folder_layout.addWidget(self.folder_label)

        folder_action_row = QWidget()
        folder_action_layout = QHBoxLayout()
        folder_action_layout.setContentsMargins(0, 0, 0, 0)
        folder_action_layout.setSpacing(8)
        folder_action_row.setLayout(folder_action_layout)
        self.folder_open_btn = create_button(
            tr("missionary_detail_open_folder"),
            "subtle",
            fixed_height=28,
        )
        self.folder_open_btn.setEnabled(False)
        self.folder_open_btn.clicked.connect(self._open_folder_path)
        folder_action_layout.addWidget(self.folder_open_btn)
        folder_action_layout.addStretch()
        folder_layout.addWidget(folder_action_row)

        identity_grid.addWidget(
            self._build_field_block(
                tr("missionary_detail_folder_path"),
                folder_widget,
            ),
            2,
            1,
        )

        credentials_card, credentials_layout = self._build_detail_card(
            tr("missionary_detail_credentials"),
            tr("missionary_detail_credentials_subtitle"),
            title_key="missionary_detail_credentials",
            subtitle_key="missionary_detail_credentials_subtitle",
        )
        credentials_grid = QGridLayout()
        credentials_grid.setContentsMargins(0, 0, 0, 0)
        credentials_grid.setHorizontalSpacing(10)
        credentials_grid.setVerticalSpacing(8)
        credentials_layout.addLayout(credentials_grid)

        for col, (field_key, label_text, value_label) in enumerate(
            [
                (
                    "tramite_usuario",
                    field_label("tramite_usuario"),
                    self.tramite_usuario_input,
                ),
                (
                    "tramite_contrasena",
                    field_label("tramite_contrasena"),
                    self.tramite_contrasena_input,
                ),
            ]
        ):
            source_lbl = self._build_source_label()
            self._credential_source_labels[field_key] = source_lbl
            credentials_grid.addWidget(
                self._build_field_block(
                    label_text,
                    value_label,
                    source_lbl,
                ),
                0,
                col,
            )

        timeline_card, timeline_layout = self._build_detail_card(
            tr("missionary_detail_legal_timeline"),
            tr("missionary_detail_legal_timeline_subtitle"),
            title_key="missionary_detail_legal_timeline",
            subtitle_key="missionary_detail_legal_timeline_subtitle",
        )
        timeline_grid = QGridLayout()
        timeline_grid.setContentsMargins(0, 0, 0, 0)
        timeline_grid.setHorizontalSpacing(10)
        timeline_grid.setVerticalSpacing(8)
        timeline_layout.addLayout(timeline_grid)

        for idx, field_key in enumerate(
            [key for key in EDITABLE_DATE_FIELDS if key != "date_of_birth"]
        ):
            date_picker = create_date_picker()
            self._configure_detail_date_picker(date_picker)
            self._date_edits[field_key] = date_picker
            date_shell = self._build_date_picker_shell(date_picker)

            source_lbl = self._build_source_label()
            self._date_source_labels[field_key] = source_lbl

            timeline_grid.addWidget(
                self._build_field_block(
                field_label(field_key),
                date_shell,
                source_lbl,
                reserve_source_space=True,
            ),
                idx // 2,
                idx % 2,
            )

        residency_card = self._build_residency_timeline_card()

        self.details_layout_canvas = QWidget()
        self.details_layout_canvas.setObjectName("MissionaryDetailLayoutCanvas")
        self.details_layout_canvas.setMinimumWidth(DETAIL_LAYOUT_CANVAS_WIDTH)
        content_layout.addWidget(self.details_layout_canvas)

        self._details_sections = {
            "details_summary": summary_card,
            "details_identity": identity_card,
            "details_legal_timeline": timeline_card,
            "details_credentials": credentials_card,
            "details_residency": residency_card,
        }
        self._apply_details_layout()

        self.save_dates_btn = create_button(tr("save_details"), "primary")
        self.save_dates_btn.setFixedWidth(160)
        self.save_dates_btn.clicked.connect(self._save_dates)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.save_dates_btn)
        content_layout.addLayout(btn_row)

        content_layout.addStretch()

        scroll.setWidget(details_content)
        outer_layout.addWidget(scroll)

    def _build_residency_timeline_card(self):
        card = create_card()

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        card.setLayout(layout)

        self.residency_timeline_title = QLabel(
            tr("missionary_detail_residency_timeline")
        )
        self.residency_timeline_title.setObjectName("SectionHeader")
        layout.addWidget(self.residency_timeline_title)

        self.residency_timeline_hint = QLabel(
            tr("missionary_detail_residency_timeline_hint")
        )
        self.residency_timeline_hint.setObjectName("MutedText")
        self.residency_timeline_hint.setWordWrap(True)
        layout.addWidget(self.residency_timeline_hint)

        self._residency_timeline_labels = {}
        for key, label_key in [
            ("initial", "missionary_detail_initial_residency"),
            ("prorroga_1", "missionary_detail_prorroga_1"),
            ("prorroga_2", "missionary_detail_prorroga_2"),
        ]:
            row = QWidget()
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row.setLayout(row_layout)

            label = QLabel(tr(label_key))
            label.setObjectName("MiniMutedText")
            value_wrap = QWidget()
            value_layout = QVBoxLayout()
            value_layout.setContentsMargins(0, 0, 0, 0)
            value_layout.setSpacing(2)
            value_wrap.setLayout(value_layout)

            status = create_info_badge(tr("missionary_detail_pending"))
            status.setObjectName("SummaryBadge")
            status.setProperty("tone", "subtle")

            target = QLabel(tr("missionary_detail_target_not_set"))
            target.setObjectName("ReadOnlyValue")
            target.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            target.setWordWrap(True)

            row_layout.addWidget(label)
            row_layout.addStretch()
            row_layout.addWidget(value_wrap)
            value_layout.addWidget(status, alignment=Qt.AlignRight)
            value_layout.addWidget(target, alignment=Qt.AlignRight)
            layout.addWidget(row)
            self._residency_timeline_labels[key] = {
                "label": label,
                "label_key": label_key,
                "status": status,
                "target": target,
            }

        return card

    def _build_open_tasks_section(self):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        card.setLayout(layout)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.open_tasks_title = QLabel(tr("missionary_detail_open_tasks"))
        self.open_tasks_title.setObjectName("PanelTitle")
        header.addWidget(self.open_tasks_title)
        header.addStretch()

        add_btn = create_button(
            tr("missionary_detail_add_task"),
            "primary",
            fixed_height=30,
        )
        self.add_task_btn = add_btn
        add_btn.clicked.connect(self._add_missionary_task)
        header.addWidget(add_btn)

        office_btn = create_button(
            tr("missionary_detail_open_office_work"),
            "secondary",
            fixed_height=30,
        )
        self.office_work_btn = office_btn
        office_btn.clicked.connect(self._open_office_work)
        header.addWidget(office_btn)

        layout.addLayout(header)

        self.open_tasks_list = create_list_widget()
        self.open_tasks_list.setSpacing(8)
        self.open_tasks_list.setMinimumHeight(160)
        tune_fluent_scrollable(self.open_tasks_list)
        _set_scroll_step(self.open_tasks_list)
        layout.addWidget(self.open_tasks_list)

        return card

    def _build_notes_tab(self):
        notes_tab = QWidget()

        self._add_static_tab(
            "notes",
            tr("missionary_detail_tab_notes"),
            notes_tab,
        )

        notes_layout = QVBoxLayout()

        notes_layout.setContentsMargins(
            20, 18, 20, 20
        )

        notes_layout.setSpacing(12)

        notes_tab.setLayout(notes_layout)

        notes_tab.setObjectName("PageSurface")

        self.notes_hint = QLabel(
            tr("missionary_detail_notes_hint")
        )

        self.notes_hint.setObjectName("MutedText")

        self.notes_hint.setWordWrap(True)

        notes_layout.addWidget(self.notes_hint)

        self.notes_text = create_text_edit()

        self.notes_text.setPlaceholderText(
            tr("missionary_detail_notes_placeholder")
        )

        self.notes_text.setObjectName("NotesEditor")

        notes_layout.addWidget(
            self.notes_text, stretch=1
        )

        self.save_notes_btn = create_button(
            tr("missionary_detail_save_notes"),
            "primary",
        )

        self.save_notes_btn.setFixedWidth(140)

        self.save_notes_btn.clicked.connect(
            self._save_notes
        )

        notes_layout.addWidget(
            self.save_notes_btn,
            alignment=Qt.AlignRight,
        )

    def _update_advance_banner(self):
        if not hasattr(self, "current_missionary"):
            self.advance_banner.setVisible(False)
            return

        stage = (
            self.current_missionary.current_stage
        )

        if not stage:
            self.advance_banner.setVisible(False)
            return

        missing = (
            self.workflow_validator
            .get_missing_documents(
                self.current_missionary.id, stage
            )
        )

        if not missing:
            # Determine next stage label
            if stage in WORKFLOW_STAGES:
                idx = WORKFLOW_STAGES.index(stage)

                next_stage = (
                    WORKFLOW_STAGES[idx + 1]
                    if idx + 1 < len(WORKFLOW_STAGES)
                    else None
                )

            else:
                next_stage = None

            if next_stage:
                msg = tr(
                    "missionary_detail_advance_ready_next",
                    stage=_stage_display_name(stage),
                    next_stage=_stage_display_name(next_stage),
                )

            else:
                msg = tr(
                    "missionary_detail_advance_ready_stage",
                    stage=_stage_display_name(stage),
                )

            self.banner_text.setText(msg)

            self.advance_banner.setVisible(True)

        else:
            self.advance_banner.setVisible(False)

    # ==========================================
    # ADVANCE STAGE
    # ==========================================

    def _advance_stage(self):
        if not hasattr(self, "current_missionary"):
            return

        dialog = StageAdvanceDialog(
            self.current_missionary, parent=self
        )

        if dialog.exec() == StageAdvanceDialog.Accepted:
            self._reload_missionary()
            self._refresh_stage_related_pages()

    # ==========================================
    # UPLOAD DOCUMENT — full OCR pipeline
    # ==========================================

    def upload_document(self):
        if not hasattr(self, "current_missionary"):
            return

        dialog = UploadSessionDialog(
            self.current_missionary,
            parent=self,
        )
        dialog.appointment_dates_updated.connect(
            self._refresh_calendar_after_appointment_upload
        )
        dialog.exec()

        if dialog.saved_any():
            self._reload_missionary()
            self._refresh_missionaries_table()

        return

    # ==========================================
    # BATCH UPLOAD
    # ==========================================

    def _batch_upload(self):
        if not hasattr(self, "current_missionary"):
            return

        dialog = UploadSessionDialog(
            self.current_missionary,
            parent=self,
        )
        dialog.appointment_dates_updated.connect(
            self._refresh_calendar_after_appointment_upload
        )
        dialog.exec()

        if dialog.saved_any():
            self._reload_missionary()
            self._refresh_missionaries_table()

        return

    def _refresh_calendar_after_appointment_upload(self, missionary_id, fields):
        if not fields:
            return

        current_id = getattr(
            getattr(self, "current_missionary", None),
            "id",
            None,
        )
        if current_id == missionary_id:
            self._reload_missionary()

        calendar_page = getattr(self.main_window, "calendar_page", None)
        load_data = getattr(calendar_page, "load_data", None)
        if callable(load_data):
            load_data()

    def _refresh_missionaries_table(self):
        main_window = getattr(self, "main_window", None)
        if main_window is None:
            return

        missionaries_page = getattr(
            main_window,
            "missionaries_page",
            None,
        )

        if missionaries_page is None:
            stack = getattr(main_window, "stack", None)
            widget = getattr(stack, "widget", None)
            if callable(widget):
                try:
                    missionaries_page = widget(1)
                except Exception:
                    missionaries_page = None

        load_data = getattr(missionaries_page, "load_data", None)
        if callable(load_data):
            load_data()

    def _refresh_stage_related_pages(self):
        main_window = getattr(self, "main_window", None)
        if main_window is None:
            return

        self._refresh_missionaries_table()

        for page_name in (
            "dashboard_page",
            "calendar_page",
            "reports_page",
        ):
            page = getattr(main_window, page_name, None)
            load_data = getattr(page, "load_data", None)
            if callable(load_data):
                load_data()

    def _open_folder_path(self):
        if not hasattr(self, "current_missionary"):
            return

        folder_path = getattr(self.current_missionary, "folder_path", None)
        if not folder_path:
            show_message(
                self,
                tr("missionary_detail_open_folder"),
                tr("missionary_detail_open_folder_missing"),
                kind="warning",
            )
            return

        path = Path(folder_path)
        if not path.exists():
            show_message(
                self,
                tr("missionary_detail_open_folder"),
                tr(
                    "missionary_detail_folder_not_found",
                    folder_path=folder_path,
                ),
                kind="warning",
            )
            return

        try:
            open_document_with_default_app(path)
        except Exception:
            logger.exception("Failed to open folder path")
            show_message(
                self,
                tr("missionary_detail_open_folder"),
                tr("missionary_detail_open_folder_failed"),
                kind="critical",
            )

    def _update_field_sources(self, missionary):
        sources = _parse_field_sources(missionary.field_sources)

        for field_key, source_lbl in self._date_source_labels.items():
            info = sources.get(field_key)
            if info and info.get("label"):
                kind = (
                    "auto"
                    if (
                        info.get("label")
                        == AUTO_DERIVED_VISA_SOURCE_LABEL
                        or info.get("document_type") == "TAM"
                    )
                    else "document"
                )
                self._set_source_badge(
                    source_lbl,
                    info["label"],
                    kind=kind,
                )
            else:
                self._set_source_badge(source_lbl, "")

        for field_key, source_lbl in self._credential_source_labels.items():
            info = sources.get(field_key)
            if info and info.get("label"):
                self._set_source_badge(
                    source_lbl,
                    info["label"],
                    kind="document",
                )
            else:
                self._set_source_badge(source_lbl, "")

    def _save_dates(self):
        if not hasattr(self, "current_missionary"):
            return

        updates = {}
        sources = _parse_field_sources(
            getattr(self.current_missionary, "field_sources", None)
        )
        current_arrival = getattr(
            self.current_missionary,
            "arrival_date",
            None,
        )
        current_visa = getattr(
            self.current_missionary,
            "visa_expiration",
            None,
        )
        current_visa_source = sources.get("visa_expiration", {})
        current_visa_is_auto = (
            current_visa_source.get("label")
            == AUTO_DERIVED_VISA_SOURCE_LABEL
            or current_visa_source.get("document_type") == "TAM"
        )

        for field_key, date_edit in self._date_edits.items():
            qd = (
                date_edit.getDate()
                if hasattr(date_edit, "getDate")
                else date_edit.date()
            )
            if (
                field_key in self._date_empty_on_load
                and qd == DATE_PLACEHOLDER
            ):
                continue
            if qd == DATE_PLACEHOLDER:
                continue
            updates[field_key] = date(
                qd.year(), qd.month(), qd.day()
            )

        for field_key, text_edit in self._text_edits.items():
            value = text_edit.text().strip()
            current_value = (
                getattr(self.current_missionary, field_key, None) or ""
            ).strip()
            if value != current_value:
                updates[field_key] = value

        arrival_date = updates.get("arrival_date", current_arrival)
        visa_date = updates.get("visa_expiration", current_visa)

        if arrival_date:
            derived_visa = add_years(arrival_date, 1)
            if derived_visa:
                old_derived_visa = (
                    add_years(current_arrival, 1)
                    if current_arrival
                    else None
                )
                current_visa_was_auto = (
                    current_visa_is_auto
                    or (
                        current_visa is not None
                        and old_derived_visa is not None
                        and current_visa == old_derived_visa
                    )
                    or current_visa is None
                )

                if arrival_date != current_arrival:
                    if current_visa_was_auto:
                        if visa_date in {None, current_visa, old_derived_visa}:
                            updates["visa_expiration"] = derived_visa
                            sources["visa_expiration"] = {
                                "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                            }
                        else:
                            updates["visa_expiration"] = visa_date
                            if visa_date == derived_visa:
                                sources["visa_expiration"] = {
                                    "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                                }
                            else:
                                sources.pop("visa_expiration", None)
                    else:
                        updates["visa_expiration"] = visa_date
                        if visa_date == derived_visa:
                            sources["visa_expiration"] = {
                                "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                            }
                        else:
                            sources.pop("visa_expiration", None)
                else:
                    if visa_date == derived_visa:
                        sources["visa_expiration"] = {
                            "label": AUTO_DERIVED_VISA_SOURCE_LABEL,
                        }
                    elif visa_date != current_visa:
                        sources.pop("visa_expiration", None)

        if sources:
            updates["field_sources"] = json.dumps(sources)

        if not updates:
            return

        try:
            self.missionary_service.update_fields(
                self.current_missionary.id,
                updates,
            )
            show_message(
                self,
                tr("save_details"),
                tr("details_saved"),
            )
            self._reload_missionary()
            self._refresh_missionaries_table()
        except Exception:
            logger.exception("Failed to save dates")
            show_message(
                self,
                tr("save_details"),
                tr("details_save_failed"),
                kind="critical",
            )

    def retranslate_ui(self):
        self._set_pivot_text("overview", tr("missionary_detail_tab_overview"))
        self._set_pivot_text("details", tr("missionary_detail_tab_details"))
        self._set_pivot_text("notes", tr("missionary_detail_tab_notes"))
        self._set_pivot_text("timeline", tr("missionary_detail_tab_timeline"))

        if hasattr(self, "advance_button"):
            self.advance_button.setText(tr("missionary_detail_advance_stage"))
        if hasattr(self, "edit_layout_button"):
            self.edit_layout_button.setText(tr("missionary_detail_edit_layout"))
        if hasattr(self, "save_layout_button"):
            self.save_layout_button.setText(tr("settings_save"))
        if hasattr(self, "cancel_layout_button"):
            self.cancel_layout_button.setText(tr("missionary_detail_cancel"))
        if hasattr(self, "reset_layout_button"):
            self.reset_layout_button.setText(tr("missionary_detail_reset_layout"))
        if hasattr(self, "layout_edit_banner_title"):
            self.layout_edit_banner_title.setText(
                tr("missionary_detail_layout_editing_title")
            )
        if hasattr(self, "layout_edit_banner_hint"):
            self.layout_edit_banner_hint.setText(
                tr("missionary_detail_layout_editing_hint")
            )
        if hasattr(self, "actions_button"):
            self.actions_button.setText(tr("missionary_detail_actions"))
        if hasattr(self, "print_interpol_packet_action"):
            self.print_interpol_packet_action.setText(
                tr("missionary_detail_print_interpol_packet")
            )
        if hasattr(self, "workspace_menu"):
            self.workspace_menu.setTitle(tr("missionary_detail_open_workspace"))
            self.refresh_workspace_actions()
        if hasattr(self, "delete_button"):
            self.delete_button.setText(tr("missionary_detail_delete_missionary"))
        if hasattr(self, "banner_now_btn"):
            self.banner_now_btn.setText(tr("missionary_detail_advance_now"))
        if hasattr(self, "docs_helper"):
            self.docs_helper.setText(tr("missionary_detail_documents_hint"))
        if hasattr(self, "upload_button"):
            self.upload_button.setText(tr("missionary_detail_upload_document"))
        if hasattr(self, "missing_helper"):
            self.missing_helper.setText(
                tr("missionary_detail_missing_documents_hint")
            )
        self._set_section_title(
            getattr(self, "documents_section_title", None),
            tr("missionary_detail_documents"),
        )
        self._set_section_title(
            getattr(self, "missing_documents_section_title", None),
            tr("missionary_detail_missing_documents"),
        )
        self._set_section_title(
            getattr(self, "workflow_section_title", None),
            tr("missionary_detail_workflow_stages"),
        )
        if hasattr(self, "summary_title_label"):
            self.summary_title_label.setText(
                tr("missionary_detail_overview_title")
            )
        for label, key in getattr(self, "_translated_labels", []):
            label.setText(tr(key))
        if hasattr(self, "summary_current_stage_card"):
            self.summary_current_stage_card.setTitle(
                tr("missionary_detail_current_stage")
            )
            self.summary_current_stage_card.setSubtitle(
                tr("missionary_detail_current_stage_subtitle")
            )
        if hasattr(self, "summary_complete_card"):
            self.summary_complete_card.setTitle(
                tr("missionary_detail_required_docs_complete")
            )
            self.summary_complete_card.setSubtitle(
                tr("missionary_detail_current_stage_docs_subtitle")
            )
        if hasattr(self, "summary_missing_card"):
            self.summary_missing_card.setTitle(
                tr("missionary_detail_required_docs_missing")
            )
            self.summary_missing_card.setSubtitle(
                tr("missionary_detail_required_docs_missing_subtitle")
            )
        if hasattr(self, "summary_upload_card"):
            self.summary_upload_card.setTitle(tr("missionary_detail_last_upload"))
            self.summary_upload_card.setSubtitle(
                tr("missionary_detail_last_upload_subtitle")
            )
        if hasattr(self, "summary_action_title"):
            self.summary_action_title.setText(
                tr("missionary_detail_recommended_next_step")
            )
        if hasattr(self, "workflow_helper"):
            self.workflow_helper.setText(tr("missionary_detail_workflow_hint"))
        if hasattr(self, "folder_open_btn"):
            self.folder_open_btn.setText(tr("missionary_detail_open_folder"))
        if hasattr(self, "residency_timeline_title"):
            self.residency_timeline_title.setText(
                tr("missionary_detail_residency_timeline")
            )
        if hasattr(self, "residency_timeline_hint"):
            self.residency_timeline_hint.setText(
                tr("missionary_detail_residency_timeline_hint")
            )
        for widgets in getattr(self, "_residency_timeline_labels", {}).values():
            label = widgets.get("label")
            label_key = widgets.get("label_key")
            if label is not None and label_key:
                label.setText(tr(label_key))
        if hasattr(self, "open_tasks_title"):
            self.open_tasks_title.setText(tr("missionary_detail_open_tasks"))
        if hasattr(self, "add_task_btn"):
            self.add_task_btn.setText(tr("missionary_detail_add_task"))
        if hasattr(self, "office_work_btn"):
            self.office_work_btn.setText(
                tr("missionary_detail_open_office_work")
            )
        if hasattr(self, "notes_hint"):
            self.notes_hint.setText(tr("missionary_detail_notes_hint"))
        if hasattr(self, "notes_text"):
            self.notes_text.setPlaceholderText(
                tr("missionary_detail_notes_placeholder")
            )
        if hasattr(self, "save_notes_btn"):
            self.save_notes_btn.setText(tr("missionary_detail_save_notes"))
        if hasattr(self, "save_dates_btn"):
            self.save_dates_btn.setText(tr("save_details"))
        if hasattr(self, "current_missionary"):
            self.load_missionary(self.current_missionary)

    def _set_pivot_text(self, route_key, text):
        if self.tabs is None:
            return
        for method_name in ("setItemText", "setText"):
            method = getattr(self.tabs, method_name, None)
            if callable(method):
                try:
                    method(route_key, text)
                    return
                except TypeError:
                    continue

    def _set_section_title(self, section, text):
        if section is None:
            return
        labels = section.findChildren(QLabel)
        if labels:
            labels[0].setText(text)

    def _show_doc_context_menu(self, pos):
        item = self.documents_list.itemAt(pos)

        if not item:
            return

        doc_id = item.data(Qt.UserRole)

        if doc_id is None:
            return

        menu = create_menu("", self)

        view_action = menu.addAction(tr("missionary_detail_view_document"))

        notes_action = menu.addAction(
            tr("missionary_detail_view_edit_notes")
        )

        ocr_action = menu.addAction(
            tr("view_extracted_data")
        )

        delete_action = menu.addAction(
            tr("delete_document")
        )

        open_action = menu.addAction(tr("missionary_detail_open_externally"))

        action = menu.exec(
            self.documents_list.mapToGlobal(pos)
        )

        if action == view_action:
            self._open_document_viewer(doc_id)

        elif action == notes_action:
            self._open_document_notes(doc_id)

        elif action == ocr_action:
            self._open_ocr_data(doc_id)

        elif action == delete_action:
            self._delete_document(doc_id)

        elif action == open_action:
            self._open_document_file(doc_id)

    def _show_actions_menu(self, checked=False):
        menu = create_menu("", self)
        print_interpol_action = menu.addAction(
            tr("missionary_detail_print_interpol_packet")
        )

        action = menu.exec(
            self.actions_button.mapToGlobal(
                self.actions_button.rect().bottomLeft()
            )
        )

        if action == print_interpol_action:
            self._print_interpol_packet()

    def _edit_layout(self, checked=False):
        _ = checked
        if self._layout_editing:
            return
        self._layout_edit_payload = json.loads(
            json.dumps(self.detail_layout_service.get_layout())
        )
        self._layout_preview_payload = None
        self._layout_editing = True
        self._set_layout_edit_controls_visible(True)
        self._apply_current_detail_layouts()

    def _save_layout_edit(self, checked=False):
        _ = checked
        if not self._layout_editing or not self._layout_edit_payload:
            return
        if self._layout_preview_payload:
            self._layout_edit_payload = self._layout_preview_payload
            self._layout_preview_payload = None
        self.detail_layout_service.save_layout(self._layout_edit_payload)
        self._finish_layout_editing(
            duration=DETAIL_LAYOUT_COMMIT_ANIMATION_MS,
            easing=QEasingCurve.OutCubic,
        )
        show_message(
            self,
            tr("missionary_detail_edit_layout"),
            tr("missionary_detail_layout_saved"),
        )

    def _cancel_layout_edit(self, checked=False):
        _ = checked
        if not self._layout_editing:
            return
        self._finish_layout_editing(
            duration=DETAIL_LAYOUT_REBOUND_ANIMATION_MS,
            easing=QEasingCurve.OutBack,
        )

    def _reset_layout_edit(self, checked=False):
        _ = checked
        if not self._layout_editing:
            return
        self._layout_edit_payload = MissionaryDetailLayoutService.default_layout()
        self._layout_preview_payload = None
        self._layout_drag_state = None
        self._apply_current_detail_layouts(
            duration=DETAIL_LAYOUT_REBOUND_ANIMATION_MS,
            easing=QEasingCurve.OutBack,
        )

    def _finish_layout_editing(
        self,
        duration=DETAIL_LAYOUT_PREVIEW_ANIMATION_MS,
        easing=QEasingCurve.OutCubic,
    ):
        self._layout_editing = False
        self._layout_edit_payload = None
        self._layout_preview_payload = None
        self._layout_drag_state = None
        self._set_layout_edit_controls_visible(False)
        self._apply_current_detail_layouts(duration=duration, easing=easing)
        self._refresh_layout_drag_targets()

    def _set_layout_edit_controls_visible(self, editing):
        self.edit_layout_button.setVisible(not editing)
        self.save_layout_button.setVisible(editing)
        self.cancel_layout_button.setVisible(editing)
        self.reset_layout_button.setVisible(editing)
        if hasattr(self, "layout_edit_banner"):
            self.layout_edit_banner.setVisible(editing)
        self.actions_button.setVisible(not editing)
        self.advance_button.setVisible(not editing)
        self.delete_button.setVisible(not editing)

    def refresh_workspace_actions(self):
        if not hasattr(self, "workspace_menu"):
            return
        self.workspace_menu.clear()
        workspaces = self.workspace_service.list_workspaces()
        if not workspaces:
            empty_action = QAction(
                tr("workspace_no_workspaces"),
                self.workspace_menu,
            )
            self.workspace_menu.addAction(empty_action)
            empty_action.setEnabled(False)
            return
        for workspace in workspaces:
            action = QAction(
                workspace.get("name") or tr("workspace_title"),
                self.workspace_menu,
            )
            self.workspace_menu.addAction(action)
            action.setData(workspace.get("id"))
            action.triggered.connect(
                lambda checked=False, workspace_id=workspace.get("id"): (
                    self._open_workspace(workspace_id)
                )
            )

    def _open_workspace(self, workspace_id):
        if not hasattr(self, "current_missionary"):
            return
        workspace = self.workspace_service.get_workspace(workspace_id)
        if not workspace:
            return
        opener = getattr(self.main_window, "open_missionary_workspace", None)
        if callable(opener) and opener(self.current_missionary, workspace):
            return

        from ui.dialogs.missionary_workspace_dialog import (
            MissionaryWorkspaceDialog,
        )

        dialog = MissionaryWorkspaceDialog(
            self.current_missionary,
            workspace,
            parent=self,
            on_refresh=lambda: self.load_missionary(self.current_missionary),
        )
        dialog.exec()

    def _print_interpol_packet(self, checked=False):
        if not hasattr(self, "current_missionary"):
            return

        packet_docs, missing_labels = self._collect_interpol_packet_docs()

        if missing_labels:
            missing_text = "\n".join(
                f"- {label}" for label in missing_labels
            )
            response = show_message(
                self,
                tr("missionary_detail_missing_packet_title"),
                tr(
                    "missionary_detail_missing_packet_message",
                    missing=missing_text,
                ),
                kind="warning",
                buttons="yes_no",
            )

            if response not in {1, 16384}:
                return

        if not packet_docs:
            show_message(
                self,
                tr("missionary_detail_no_documents_to_print_title"),
                tr("missionary_detail_no_documents_to_print"),
                kind="warning",
            )
            return

        try:
            temp_path = self._create_interpol_packet_temp_path()

            self._build_interpol_packet_pdf(packet_docs, temp_path)
            self._open_packet_in_default_pdf_viewer(temp_path)

        except Exception:
            logger.exception("Failed to print Interpol packet")
            show_message(
                self,
                tr("missionary_detail_print_failed_title"),
                tr("missionary_detail_print_failed"),
                kind="critical",
            )

    def _collect_interpol_packet_docs(self):
        documents = self.document_service.get_documents(
            self.current_missionary.id
        )
        packet_document_types = self._interpol_packet_document_types()
        docs_by_type = {}

        for doc in documents:
            if getattr(doc, "status", "ACTIVE") != "ACTIVE":
                continue

            doc_type = getattr(doc, "document_type", None)
            if doc_type not in packet_document_types:
                continue

            existing = docs_by_type.get(doc_type)
            if existing is None or self._doc_is_newer(doc, existing):
                docs_by_type[doc_type] = doc

        packet_docs = []
        missing_labels = []

        for doc_type in packet_document_types:
            label = _document_label(doc_type)
            doc = docs_by_type.get(doc_type)
            file_path = Path(getattr(doc, "file_path", "")) if doc else None

            if doc is None or not file_path or not file_path.exists():
                missing_labels.append(label)
                continue

            packet_docs.append(
                {
                    "label": label,
                    "file_path": str(file_path),
                }
            )

        return packet_docs, missing_labels

    def _interpol_packet_document_types(self):
        if requires_fbi_document(self.current_missionary):
            return FBI_INTERPOL_PACKET_DOCUMENT_TYPES

        return INTERPOL_PACKET_DOCUMENT_TYPES

    def _doc_is_newer(self, candidate, existing):
        candidate_uploaded = getattr(candidate, "uploaded_at", None)
        existing_uploaded = getattr(existing, "uploaded_at", None)

        if candidate_uploaded and existing_uploaded:
            if candidate_uploaded != existing_uploaded:
                return candidate_uploaded > existing_uploaded
        elif candidate_uploaded and not existing_uploaded:
            return True
        elif existing_uploaded and not candidate_uploaded:
            return False

        return getattr(candidate, "id", 0) > getattr(existing, "id", 0)

    def _create_interpol_packet_temp_path(self):
        packet_dir = (
            Path(tempfile.gettempdir())
            / "MissionLegalApp"
            / "print_packets"
        )
        packet_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_old_packet_files(packet_dir)

        missionary_name = getattr(
            self.current_missionary,
            "full_name",
            "missionary",
        )
        safe_name = "".join(
            char if char.isalnum() else "_"
            for char in missionary_name
        ).strip("_")
        safe_name = safe_name or "missionary"

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        return str(
            packet_dir
            / f"interpol_packet_{safe_name}_{timestamp}.pdf"
        )

    def _cleanup_old_packet_files(self, packet_dir):
        cutoff = time.time() - (24 * 60 * 60)

        try:
            for file_path in packet_dir.glob("interpol_packet_*.pdf"):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                except Exception:
                    logger.warning(
                        "Could not clean up old packet file: %s",
                        file_path,
                    )
        except Exception:
            logger.warning("Could not scan packet temp directory")

    def _build_interpol_packet_pdf(self, packet_docs, output_path):
        packet = fitz.open()

        try:
            for doc in packet_docs:
                source_path = doc["file_path"]
                source = fitz.open(source_path)

                try:
                    if source.is_pdf:
                        packet.insert_pdf(source)
                    else:
                        image_pdf = fitz.open(
                            "pdf",
                            source.convert_to_pdf(),
                        )
                        try:
                            packet.insert_pdf(image_pdf)
                        finally:
                            image_pdf.close()
                finally:
                    source.close()

            if packet.page_count == 0:
                raise ValueError("Interpol packet has no printable pages")

            self._add_print_open_action(packet)
            packet.save(output_path)

        finally:
            packet.close()

    def _add_print_open_action(self, packet):
        js = (
            "this.print({"
            "bUI: true, "
            "bSilent: false, "
            "bShrinkToFit: true"
            "});"
        )
        js_hex = js.encode("utf-16-be").hex()
        js_xref = packet.get_new_xref()
        packet.update_object(
            js_xref,
            f"<< /S /JavaScript /JS <FEFF{js_hex}> >>",
        )
        packet.xref_set_key(
            packet.pdf_catalog(),
            "OpenAction",
            f"{js_xref} 0 R",
        )

    def _open_packet_in_default_pdf_viewer(self, packet_path):
        logger.info(
            "Opening Interpol packet in default PDF viewer: %s",
            packet_path,
        )
        open_document_with_default_app(packet_path)

    def _find_doc_data(self, doc_id):
        return next(
            (
                d
                for d in self._document_data
                if d["id"] == doc_id
            ),
            None,
        )

    def _open_ocr_data(self, doc_id):
        doc = self._find_doc_data(doc_id)
        if not doc:
            return
        dialog = OcrDataViewDialog(
            doc.get("ocr_raw_data"),
            doc.get("ocr_confirmed_data"),
            parent=self,
        )
        dialog.exec()

    def _open_document_notes(self, doc_id):
        doc = self._find_doc_data(doc_id)

        if not doc:
            return

        dialog = DocumentNotesDialog(
            doc, self.document_service, parent=self
        )

        if dialog.exec():
            # Refresh so updated notes appear
            doc["notes"] = dialog.get_notes()

    def _open_document_file(self, doc_id):
        doc = self._find_doc_data(doc_id)

        if not doc:
            return

        try:
            file_path = doc["file_path"]

            if not Path(file_path).exists():
                show_message(
                    self,
                    tr("missionary_detail_file_not_found_title"),
                    tr(
                        "missionary_detail_cannot_open_file",
                        file_path=file_path,
                    ),
                    kind="warning",
                )

                return

            open_document_with_default_app(file_path)

        except Exception:
            logger.exception("Failed to open file")

    def _open_document_viewer(self, doc_id):
        doc = self._find_doc_data(doc_id)

        if not doc:
            return

        try:
            file_path = doc.get("file_path")

            if not file_path or not Path(
                file_path
            ).exists():
                show_message(
                    self,
                    tr("missionary_detail_file_not_found_title"),
                    tr("missionary_detail_cannot_open_document"),
                    kind="warning",
                )

                return

            from ui.dialogs.document_viewer_dialog import (
                DocumentViewerDialog,
            )

            dialog = DocumentViewerDialog(
                file_path, parent=self
            )

            dialog.exec()

        except Exception:
            logger.exception(
                "Document viewer failed"
            )

    def _delete_document(self, doc_id):
        doc = self._find_doc_data(doc_id)

        if not doc:
            return

        response = show_message(
            self,
            tr("delete_document_title"),
            tr("delete_document_confirm"),
            kind="question",
            buttons="yes_no",
        )

        if response not in {1, 16384}:
            return

        try:
            deleted = self.document_service.delete_document_by_id(
                doc_id
            )

            if not deleted:
                show_message(
                    self,
                    tr("delete_document_title"),
                    tr("delete_document_failed"),
                    kind="warning",
                )
                return

            self._reload_missionary()

        except Exception:
            logger.exception("Failed to delete document")
            show_message(
                self,
                tr("delete_document_title"),
                tr("delete_document_failed"),
                kind="critical",
            )

    def load_missionary(self, missionary):
        self.current_missionary = missionary

        logger.info(
            f"Loading missionary details for "
            f"{missionary.full_name}"
        )

        self.name_label.setText(missionary.full_name)
        stage = missionary.current_stage or "-"
        self.stage_badge.setText(
            f"  {_stage_display_name(stage) if stage != '-' else stage}  "
        )
        self._update_summary_strip(missionary)

        self._set_value_text(
            self.nationality_label,
            missionary.nationality,
        )
        self._set_value_text(
            self.passport_label,
            missionary.passport_number,
        )
        if hasattr(self, "carnet_number_input"):
            self.carnet_number_input.setText(
                getattr(missionary, "carnet_number", None) or ""
            )
        if hasattr(self, "tramite_usuario_input"):
            self.tramite_usuario_input.setText(
                getattr(missionary, "tramite_usuario", None) or ""
            )
        if hasattr(self, "tramite_contrasena_input"):
            self.tramite_contrasena_input.setText(
                getattr(missionary, "tramite_contrasena", None) or ""
            )
        self._set_value_text(
            self.folder_label,
            missionary.folder_path,
        )

        self._date_empty_on_load = set()
        sources = _parse_field_sources(
            getattr(missionary, "field_sources", None)
        )
        for field_key, date_edit in self._date_edits.items():
            value = getattr(missionary, field_key, None)
            if value:
                date_edit.setDate(
                    QDate(value.year, value.month, value.day)
                )
                self._set_date_picker_state(date_edit, False)
            else:
                date_edit.setDate(DATE_PLACEHOLDER)
                self._date_empty_on_load.add(field_key)
                self._set_date_picker_state(date_edit, True)

        arrival_date = getattr(missionary, "arrival_date", None)
        visa_source = sources.get("visa_expiration", {})
        visa_is_manual = (
            visa_source.get("label")
            and visa_source.get("label")
            != AUTO_DERIVED_VISA_SOURCE_LABEL
            and visa_source.get("document_type") != "TAM"
        )
        visa_edit = self._date_edits.get("visa_expiration")
        if (
            arrival_date
            and visa_edit is not None
            and not getattr(missionary, "visa_expiration", None)
            and not visa_is_manual
        ):
            derived_visa = add_years(arrival_date, 1)
            if derived_visa:
                visa_edit.setDate(
                    QDate(
                        derived_visa.year,
                        derived_visa.month,
                        derived_visa.day,
                    )
                )
                self._set_date_picker_state(visa_edit, False)
                self._date_empty_on_load.discard("visa_expiration")

        self._update_field_sources(missionary)
        self._refresh_residency_timeline(missionary.id)

        folder_path = missionary.folder_path or ""
        self.folder_label.setToolTip(folder_path)
        if hasattr(self, "folder_open_btn"):
            self.folder_open_btn.setEnabled(bool(folder_path))

        self.notes_text.setPlainText(
            missionary.notes or ""
        )

        workflows = self.workflow_service.get_workflows(
            missionary.id
        )
        documents = self.document_service.get_documents(
            missionary.id
        )

        self.load_workflow_stages(workflows)
        self.load_open_tasks()
        self.load_documents(documents)
        self.load_missing_documents(documents)
        self._refresh_overview_summary(workflows, documents)
        self._load_timeline()
        self._update_advance_banner()

    def _refresh_residency_timeline(self, missionary_id):
        if not self._residency_timeline_labels:
            return

        rows = self.residency_service.get_residency_timeline(
            missionary_id
        )
        key_map = {
            ("INITIAL_RESIDENCY", 0): "initial",
            ("PRORROGA", 1): "prorroga_1",
            ("PRORROGA", 2): "prorroga_2",
        }

        for row in rows:
            key = key_map.get(
                (
                    row.get("event_type"),
                    row.get("sequence_number"),
                )
            )
            widgets = self._residency_timeline_labels.get(key)
            if not widgets:
                continue

            target = self.format_date(
                row.get("target_expiration")
            )
            status = row.get("status") or "PENDING"
            if status == "APPROVED":
                status_text = tr("missionary_detail_approved")
                target_text = tr(
                    "missionary_detail_expires",
                    target=target,
                )
                document_id = row.get("document_id")
                if document_id:
                    target_text += (
                        " - "
                        + tr(
                            "missionary_detail_document_number",
                            document_id=document_id,
                        )
                    )
            else:
                status_text = tr("missionary_detail_pending")
                target_text = tr(
                    "missionary_detail_target",
                    target=target,
                )

            widgets["status"].setText(status_text)
            widgets["target"].setText(target_text)

    def load_workflow_stages(self, workflows=None):
        self.workflow_list.clear()

        if not hasattr(self, "current_missionary"):
            return

        if workflows is None:
            workflows = self.workflow_service.get_workflows(
                self.current_missionary.id
            )

        workflow_map = {
            wf.stage_name: wf
            for wf in workflows
        }
        current_stage = getattr(
            self.current_missionary,
            "current_stage",
            None,
        )

        for stage_name in WORKFLOW_STAGES:
            wf = workflow_map.get(stage_name)
            if wf is None:
                continue

            item = QListWidgetItem()
            widget = self._build_workflow_stage_widget(
                wf,
                is_current=(stage_name == current_stage),
            )
            item.setData(Qt.UserRole, wf.id)
            item.setSizeHint(widget.sizeHint())
            self.workflow_list.addItem(item)
            self.workflow_list.setItemWidget(item, widget)

        if self.workflow_list.count() == 0:
            empty = QListWidgetItem(
                tr("missionary_detail_no_workflow_stages")
            )
            empty.setFlags(
                empty.flags() & ~Qt.ItemIsSelectable
            )
            self.workflow_list.addItem(empty)

    def load_documents(self, documents=None):
        self.documents_list.clear()
        self._document_data = []

        if not hasattr(self, "current_missionary"):
            return

        if documents is None:
            documents = self.document_service.get_documents(
                self.current_missionary.id
            )

        def _doc_sort_key(doc):
            uploaded_at = getattr(doc, "uploaded_at", None)
            if uploaded_at:
                try:
                    uploaded_value = uploaded_at.timestamp()
                except Exception:
                    uploaded_value = 0
            else:
                uploaded_value = -1
            return (
                uploaded_value,
                (doc.document_type or "").lower(),
                (doc.file_name or "").lower(),
            )

        documents = sorted(
            documents,
            key=_doc_sort_key,
            reverse=True,
        )

        if not documents:
            empty = QListWidgetItem()
            widget = self._build_empty_state_card(
                tr("missionary_detail_no_documents"),
                tr("missionary_detail_no_documents_hint"),
            )
            empty.setSizeHint(widget.sizeHint())
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            self.documents_list.addItem(empty)
            self.documents_list.setItemWidget(empty, widget)
            return

        for doc in documents:
            label = _document_label(doc.document_type)

            item = QListWidgetItem()
            item.setData(Qt.UserRole, doc.id)

            try:
                pixmap = self.thumb_service.get_pixmap(
                    doc.file_path
                )
            except Exception:
                pixmap = None

            widget = self._build_document_item_widget(
                doc,
                label,
                pixmap,
            )
            item.setSizeHint(widget.sizeHint())
            self.documents_list.addItem(item)
            self.documents_list.setItemWidget(item, widget)

            self._document_data.append({
                "id": doc.id,
                "document_type": doc.document_type,
                "label": label,
                "file_path": doc.file_path,
                "file_name": doc.file_name,
                "notes": doc.notes or "",
                "ocr_raw_data": doc.ocr_raw_data,
                "ocr_confirmed_data": doc.ocr_confirmed_data,
            })

    def load_open_tasks(self):
        if not hasattr(self, "open_tasks_list"):
            return

        self.open_tasks_list.clear()

        if not hasattr(self, "current_missionary"):
            return

        tasks = self.secretary_work_service.list_tasks(
            missionary_id=self.current_missionary.id,
        )

        if not tasks:
            empty = QListWidgetItem()
            widget = self._build_empty_state_card(
                tr("missionary_detail_no_open_tasks"),
                tr("missionary_detail_no_open_tasks_hint"),
            )
            empty.setSizeHint(widget.sizeHint())
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            self.open_tasks_list.addItem(empty)
            self.open_tasks_list.setItemWidget(empty, widget)
            return

        for task in tasks:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, task["id"])
            widget = self._build_open_task_widget(task)
            item.setSizeHint(widget.sizeHint())
            self.open_tasks_list.addItem(item)
            self.open_tasks_list.setItemWidget(item, widget)

    def _build_open_task_widget(self, task):
        return build_task_card(
            task,
            on_done=lambda task_data: self._complete_missionary_task(task_data["id"]),
            on_edit=self._edit_missionary_task,
        )

    def _add_missionary_task(self):
        if not hasattr(self, "current_missionary"):
            return

        dialog = TaskDialog(
            self.secretary_work_service,
            defaults={"missionary_id": self.current_missionary.id},
            parent=self,
        )
        if dialog.exec():
            self._refresh_task_views()

    def _edit_missionary_task(self, task):
        dialog = TaskDialog(
            self.secretary_work_service,
            task=task,
            parent=self,
        )
        if dialog.exec():
            self._refresh_task_views()

    def _complete_missionary_task(self, task_id):
        self.secretary_work_service.complete_task(task_id)
        self._refresh_task_views()

    def _refresh_task_views(self):
        self.load_open_tasks()
        office_work_page = getattr(
            self.main_window,
            "office_work_page",
            None,
        )
        if office_work_page is not None and hasattr(office_work_page, "load_data"):
            office_work_page.load_data()
        calendar_page = getattr(
            self.main_window,
            "calendar_page",
            None,
        )
        if calendar_page is not None and hasattr(calendar_page, "load_data"):
            calendar_page.load_data()

    def _open_office_work(self):
        if hasattr(self.main_window, "set_current_key"):
            self.main_window.set_current_key("office_work")
            return
        if hasattr(self.main_window, "stack"):
            self.main_window.stack.setCurrentIndex(3)

    def load_missing_documents(self, documents=None):
        self.missing_documents_list.clear()

        if not hasattr(self, "current_missionary"):
            return

        if documents is None:
            documents = self.document_service.get_documents(
                self.current_missionary.id
            )

        uploaded_types = {
            doc.document_type
            for doc in documents
        }
        current_stage = getattr(
            self.current_missionary,
            "current_stage",
            None,
        )

        missing_groups = []

        general_missing = [
            doc_key
            for doc_key, config in DOCUMENTS.items()
            if config.get("required")
            and config.get("stage") is None
            and doc_key not in uploaded_types
            and doc_key != "OTHER"
        ]
        if general_missing:
            missing_groups.append((
                "Always required",
                general_missing,
                True,
            ))

        stage_order = []
        if current_stage in WORKFLOW_STAGES:
            stage_order.append(current_stage)
        stage_order.extend(
            stage
            for stage in WORKFLOW_STAGES
            if stage != current_stage
        )

        seen = set()
        for stage_name in stage_order:
            missing = [
                doc_key
                for doc_key in required_documents_for_missionary(
                    stage_name,
                    self.current_missionary,
                )
                if doc_key not in uploaded_types
            ]
            if missing:
                missing_groups.append((
                    stage_name,
                    missing,
                    stage_name == current_stage,
                ))
                seen.add(stage_name)

        if not missing_groups:
            empty = QListWidgetItem()
            widget = self._build_empty_state_card(
                tr("missionary_detail_all_required_uploaded"),
                tr("missionary_detail_all_required_uploaded_hint"),
                tone="success",
            )
            empty.setSizeHint(widget.sizeHint())
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            self.missing_documents_list.addItem(empty)
            self.missing_documents_list.setItemWidget(empty, widget)
            return

        for stage_name, missing_docs, is_current in missing_groups:
            item = QListWidgetItem()
            widget = self._build_missing_stage_widget(
                stage_name,
                missing_docs,
                is_current=is_current,
            )
            item.setSizeHint(widget.sizeHint())
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.missing_documents_list.addItem(item)
            self.missing_documents_list.setItemWidget(item, widget)

    def _refresh_overview_summary(self, workflows=None, documents=None):
        if not hasattr(self, "current_missionary"):
            return

        stage = getattr(self.current_missionary, "current_stage", None)
        stage_display = _stage_display_name(stage)
        self.summary_stage_chip.setText(stage_display)
        self.summary_current_stage_card.setValue(stage_display)

        if documents is None:
            documents = self.document_service.get_documents(
                self.current_missionary.id
            )

        uploaded_types = {
            doc.document_type
            for doc in documents
        }
        required_docs = list(
            dict.fromkeys(
                [
                    doc_key
                    for doc_key, config in DOCUMENTS.items()
                    if config.get("required")
                    and config.get("stage") is None
                    and doc_key != "OTHER"
                ]
                + list(
                    required_documents_for_missionary(
                        stage,
                        self.current_missionary,
                    )
                )
            )
        )
        missing_current = [
            doc_key
            for doc_key in required_docs
            if doc_key not in uploaded_types
        ]

        complete_count = len(required_docs) - len(missing_current)
        total_count = len(required_docs)

        self.summary_complete_card.setValue(
            f"{complete_count}/{total_count}"
        )
        self.summary_missing_card.setValue(
            str(len(missing_current))
        )

        latest_upload = None
        for doc in documents:
            uploaded_at = getattr(doc, "uploaded_at", None)
            if uploaded_at and (
                latest_upload is None or uploaded_at > latest_upload
            ):
                latest_upload = uploaded_at

        self.summary_upload_card.setValue(
            latest_upload.strftime("%b %d, %Y")
            if latest_upload
            else tr("missionary_detail_no_uploads_yet")
        )

        latest_activity = self._find_latest_activity()

        if missing_current:
            next_doc = _document_label(missing_current[0])
            next_text = tr(
                "missionary_detail_next_upload",
                document=next_doc,
            )
        elif stage and stage in WORKFLOW_STAGES:
            next_index = WORKFLOW_STAGES.index(stage) + 1
            if next_index < len(WORKFLOW_STAGES):
                next_text = tr(
                    "missionary_detail_next_review_advance",
                    stage=stage_display,
                    next_stage=_stage_display_name(
                        WORKFLOW_STAGES[next_index]
                    ),
                )
            else:
                next_text = tr("missionary_detail_next_complete")
        else:
            next_text = tr("missionary_detail_next_assign_stage")

        self.summary_next_action_label.setText(next_text)
        self.summary_activity_label.setText(
            tr(
                "missionary_detail_last_update",
                activity=(
                    _format_datetime(latest_activity)
                    or tr("missionary_detail_no_activity_yet")
                ),
                upload=(
                    _format_datetime(latest_upload)
                    if latest_upload
                    else tr("missionary_detail_no_uploads_yet")
                ),
            )
        )

        if missing_current:
            tip = tr("missionary_detail_tip_missing")
        else:
            tip = tr("missionary_detail_tip_ready")
        self.summary_tip_label.setText(tip)

    def _find_latest_activity(self):
        if not hasattr(self, "current_missionary"):
            return None

        latest = getattr(self.current_missionary, "created_at", None)

        try:
            from database.db import SessionLocal
            from database.models.stage_history import StageHistory

            session = SessionLocal()
            try:
                history = (
                    session.query(StageHistory)
                    .filter_by(
                        missionary_id=self.current_missionary.id
                    )
                    .order_by(StageHistory.created_at.desc())
                    .first()
                )
                if history and history.created_at:
                    latest = (
                        history.created_at
                        if latest is None or history.created_at > latest
                        else latest
                    )
            finally:
                session.close()
        except Exception:
            logger.exception("Failed to collect latest activity")

        return latest

    def _build_empty_state_card(self, title, text, tone="muted"):
        return build_empty_state_card(
            title,
            text,
            min_height=EMPTY_STATE_MIN_HEIGHT,
            tone=tone,
        )

    def _build_workflow_stage_widget(self, workflow, is_current=False):
        return build_workflow_stage_card(
            workflow,
            hint=self._workflow_stage_hint(workflow, is_current),
            is_current=is_current,
            on_update=lambda workflow_data: self.change_workflow_status(workflow_data.id),
        )
        card = create_card()
        card.setMinimumHeight(WORKFLOW_CARD_MIN_HEIGHT)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        card.setLayout(layout)

        indicator = QLabel("●")
        indicator.setFixedWidth(16)
        indicator.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title = QLabel(_stage_display_name(workflow.stage_name))

        status = QLabel(_workflow_status_label(workflow.status))

        title_row.addWidget(title)
        title_row.addWidget(status)
        title_row.addStretch()

        hint = QLabel(
            self._workflow_stage_hint(workflow, is_current)
        )
        hint.setWordWrap(True)

        copy.addLayout(title_row)
        copy.addWidget(hint)

        action_button = create_button(
            tr("missionary_detail_update_status"),
            "subtle",
            fixed_height=28,
        )
        action_button.clicked.connect(
            lambda checked=False, workflow_id=workflow.id: self.change_workflow_status(workflow_id)
        )

        layout.addWidget(indicator)
        layout.addLayout(copy, stretch=1)
        layout.addWidget(action_button)
        return card

    def _workflow_stage_hint(self, workflow, is_current=False):
        missing = []
        current_stage = getattr(
            self.current_missionary,
            "current_stage",
            None,
        )
        if workflow.stage_name == current_stage:
            missing = self.workflow_validator.get_missing_documents(
                self.current_missionary.id,
                current_stage,
            )
        if workflow.status == "WAITING":
            return tr("missionary_detail_workflow_waiting_hint")
        if workflow.status == "COMPLETED":
            return tr("missionary_detail_workflow_completed_hint")
        if workflow.status == "BLOCKED":
            return tr("missionary_detail_workflow_blocked_hint")
        if is_current and missing:
            return tr(
                "missionary_detail_workflow_missing_hint",
                count=len(missing),
            )
        if is_current:
            return tr("missionary_detail_workflow_active_hint")
        return tr("missionary_detail_workflow_update_hint")

    def _build_document_item_widget(self, doc, label, pixmap=None):
        return build_document_card(
            doc,
            label=label,
            pixmap=pixmap,
            on_view=lambda doc_data: self._open_document_viewer(doc_data.id),
            on_notes=lambda doc_data: self._open_document_notes(doc_data.id),
            on_open=lambda doc_data: self._open_document_file(doc_data.id),
            on_delete=lambda doc_data: self._delete_document(doc_data.id),
        )

    def _build_missing_stage_widget(self, stage_name, missing_docs, is_current=False):
        return build_missing_stage_card(
            stage_name,
            missing_docs,
            is_current=is_current,
            summary_text=self._missing_stage_summary(stage_name, len(missing_docs)),
            reason_for_doc=self._missing_doc_reason,
        )
        card = create_card()
        card.setMinimumHeight(MISSING_CARD_MIN_HEIGHT)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        card.setLayout(layout)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        title_text = (
            tr("missionary_detail_always_required")
            if stage_name == "Always required"
            else tr(
                "missionary_detail_required_for_stage",
                stage=_stage_display_name(stage_name),
            )
        )
        title = QLabel(title_text)
        title.setObjectName("MissingStageTitle")

        if stage_name == "Always required":
            badge_text = tr("missionary_detail_highest_priority")
        elif is_current:
            badge_text = tr("missionary_detail_current_priority")
        else:
            badge_text = tr("missionary_detail_upcoming")

        badge = QLabel(badge_text)
        badge.setObjectName("WarningBadge")

        header.addWidget(title)
        header.addWidget(badge)
        header.addStretch()

        layout.addLayout(header)

        summary = QLabel(
            self._missing_stage_summary(stage_name, len(missing_docs))
        )
        summary.setObjectName("MutedText")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        for doc_key in missing_docs:
            doc_label = _document_label(doc_key)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            icon = QLabel("✕")
            icon.setObjectName("DangerText")
            icon.setFixedWidth(18)

            copy = QVBoxLayout()
            copy.setContentsMargins(0, 0, 0, 0)
            copy.setSpacing(2)

            label = QLabel(doc_label)
            label.setWordWrap(True)

            hint = QLabel(self._missing_doc_reason(doc_key, stage_name))
            hint.setWordWrap(True)

            copy.addWidget(label)
            copy.addWidget(hint)

            row.addWidget(icon)
            row.addLayout(copy, stretch=1)
            layout.addLayout(row)

        return card

    def _missing_stage_summary(self, stage_name, count):
        if stage_name == "Always required":
            return tr(
                "missionary_detail_missing_general_summary",
                count=count,
            )
        return tr(
            "missionary_detail_missing_stage_summary",
            count=count,
        )

    def _missing_doc_reason(self, doc_key, stage_name):
        config = DOCUMENTS.get(doc_key, {})
        ocr_fields = config.get("ocr_fields", [])
        if stage_name == "Always required":
            base = tr("missionary_detail_missing_identity_reason")
        else:
            base = tr(
                "missionary_detail_missing_stage_reason",
                stage=_stage_display_name(stage_name),
            )
        if ocr_fields:
            return base + tr("missionary_detail_missing_ocr_suffix")
        return base

    def _show_workflow_context_menu(self, pos):
        item = self.workflow_list.itemAt(pos)
        if not item:
            return

        workflow_id = item.data(Qt.UserRole)
        if workflow_id is None:
            return

        menu = create_menu("", self)
        update_action = menu.addAction(tr("missionary_detail_update_status"))
        action = menu.exec(self.workflow_list.mapToGlobal(pos))

        if action == update_action:
            self.change_workflow_status(workflow_id)

    def change_workflow_status(self, item_or_id):
        if hasattr(item_or_id, "data"):
            workflow_id = item_or_id.data(Qt.UserRole)
        else:
            workflow_id = item_or_id

        if workflow_id is None:
            return

        dialog = WorkflowStatusDialog(parent=self)

        if not dialog.exec():
            return

        selected_status = dialog.selected_status()

        self.workflow_service.update_workflow_status(
            workflow_id, selected_status
        )

        if hasattr(self, "current_missionary"):
            self._reload_missionary()
            self._refresh_stage_related_pages()

    # ==========================================
    # TIMELINE
    # ==========================================

    def _build_timeline_tab(self):
        timeline_tab = QWidget()

        self._add_static_tab(
            "timeline",
            tr("missionary_detail_tab_timeline"),
            timeline_tab,
        )

        timeline_layout = QVBoxLayout()

        timeline_layout.setContentsMargins(
            20, 18, 20, 20
        )

        timeline_layout.setSpacing(12)

        timeline_tab.setLayout(timeline_layout)

        timeline_tab.setObjectName("PageSurface")

        self.timeline_list = create_list_widget()

        self.timeline_list.setObjectName("TimelineList")
        self.timeline_list.setSpacing(6)
        self.timeline_list.setMinimumHeight(
            TIMELINE_LIST_MIN_HEIGHT
        )
        tune_fluent_scrollable(self.timeline_list)

        timeline_layout.addWidget(
            self.timeline_list
        )

    def _load_timeline(self):
        self.timeline_list.clear()

        if not hasattr(self, "current_missionary"):
            return

        try:
            from database.db import SessionLocal

            from database.models.stage_history import (
                StageHistory,
            )

            session = SessionLocal()

            try:
                history = (
                    session.query(StageHistory)
                    .filter_by(
                        missionary_id=self.current_missionary.id
                    )
                    .order_by(
                        StageHistory.created_at.desc()
                    )
                    .all()
                )

                if not history:
                    empty = QListWidgetItem(
                        tr("missionary_detail_no_stage_transitions")
                    )

                    self.timeline_list.addItem(empty)

                    return

                for h in history:
                    date_str = (
                        h.created_at.strftime(
                            "%b %d, %Y %H:%M"
                        )
                        if h.created_at
                        else ""
                    )

                    from_str = (
                        _stage_display_name(h.from_stage)
                        if h.from_stage
                        else tr("missionary_detail_started")
                    )

                    text = (
                        f"{date_str}\n"
                        f"{from_str} \u2192 {_stage_display_name(h.to_stage)}"
                    )

                    item = QListWidgetItem(text)

                    self.timeline_list.addItem(item)

            finally:
                session.close()

        except Exception:
            logger.exception(
                "Failed to load timeline"
            )

    # ==========================================
    # NOTES
    # ==========================================

    def _save_notes(self):
        if not hasattr(self, "current_missionary"):
            return

        notes = self.notes_text.toPlainText()

        try:
            self.missionary_service.update_fields(
                self.current_missionary.id,
                {"notes": notes},
            )

            logger.info(
                f"Saved notes for "
                f"{self.current_missionary.full_name}"
            )

            show_message(
                self,
                tr("missionary_detail_saved_title"),
                tr("missionary_detail_notes_saved"),
            )

        except Exception:
            logger.exception(
                "Failed to save notes"
            )

            show_message(
                self,
                tr("missionary_detail_error_title"),
                tr("missionary_detail_notes_save_failed"),
                kind="critical",
            )

    # ==========================================
    # DELETE MISSIONARY
    # ==========================================

    def delete_missionary(self):
        if not hasattr(self, "current_missionary"):
            return

        response = show_message(
            self,
            tr("missionary_detail_confirm_delete_title"),
            tr("missionary_detail_confirm_delete"),
            kind="question",
            buttons="yes_no",
        )

        if response not in {1, 16384}:
            return

        self.missionary_service.delete_missionary(
            self.current_missionary.id
        )

        missionaries_page = (
            self.main_window.stack.widget(1)
        )

        missionaries_page.load_data()

        self.main_window.stack.setCurrentIndex(1)

    # ==========================================
    # HELPERS
    # ==========================================

    def _reload_missionary(self):
        from database.db import SessionLocal
        from database.models.missionary import (
            Missionary as MissionaryModel,
        )

        session = SessionLocal()

        try:
            refreshed = (
                session.query(MissionaryModel)
                .filter_by(
                    id=self.current_missionary.id
                )
                .first()
            )

            if refreshed:
                self.load_missionary(refreshed)

        finally:
            session.close()

    def format_date(self, date_value):
        if not date_value:
            return "-"

        return date_value.strftime("%B %d, %Y")


class WorkflowStatusDialog(MaskDialogBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(tr("missionary_detail_change_status_title"))
        self.surface = setup_dialog_shell(
            self,
            surface_width=420,
            use_masked_shell=True,
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        self.surface.setLayout(layout)

        title = SubtitleLabel(
            tr("missionary_detail_change_workflow_status")
        )
        layout.addWidget(title)

        helper = BodyLabel(
            tr("missionary_detail_change_workflow_status_hint")
        )
        helper.setWordWrap(True)
        layout.addWidget(helper)

        self.status_combo = create_combo_box()
        for status in WORKFLOW_STATUSES:
            self.status_combo.addItem(
                _workflow_status_label(status),
                status,
            )
        layout.addWidget(self.status_combo)

        cancel_btn = create_button(
            tr("missionary_detail_cancel"),
            "secondary",
        )
        cancel_btn.clicked.connect(self.reject)

        save_btn = create_button(
            tr("missionary_detail_update_status"),
            "primary",
        )
        save_btn.clicked.connect(self.accept)

        footer = DialogFooter()
        footer.add_action(cancel_btn)
        footer.add_action(save_btn)
        layout.addWidget(footer)

    def selected_status(self):
        status = self.status_combo.currentData()
        return status or self.status_combo.currentText()


class DocumentNotesDialog(MaskDialogBase):
    def __init__(self, doc_data, doc_service, parent=None):
        super().__init__(parent)

        self.doc_data = doc_data

        self.doc_service = doc_service

        self.setWindowTitle(
            tr(
                "missionary_detail_notes_window_title",
                document=doc_data["label"],
            )
        )

        self.surface = setup_dialog_shell(
            self,
            surface_width=460,
            surface_min_height=320,
            use_masked_shell=True,
        )

        layout = QVBoxLayout()

        layout.setContentsMargins(20, 20, 20, 16)

        layout.setSpacing(12)

        self.surface.setLayout(layout)

        title = SubtitleLabel(
            tr(
                "missionary_detail_notes_for_document",
                document=doc_data["label"],
            )
        )

        layout.addWidget(title)

        file_label = BodyLabel(
            tr(
                "missionary_detail_file_label",
                file_name=doc_data["file_name"],
            )
        )

        file_label.setObjectName("MutedText")

        layout.addWidget(file_label)

        self.text_edit = create_plain_text_edit()

        self.text_edit.setPlainText(
            doc_data.get("notes", "")
        )

        self.text_edit.setPlaceholderText(
            tr("missionary_detail_document_notes_placeholder")
        )

        self.text_edit.setObjectName("DocumentNotesEditor")

        layout.addWidget(self.text_edit, stretch=1)

        cancel_btn = create_button(
            tr("missionary_detail_cancel"),
            "secondary",
        )

        cancel_btn.clicked.connect(self.reject)

        save_btn = create_button(
            tr("missionary_detail_save_document_notes"),
            "primary",
        )

        save_btn.clicked.connect(self._save)

        footer = DialogFooter()
        footer.add_action(cancel_btn)
        footer.add_action(save_btn)

        layout.addWidget(footer)

    def _save(self):
        notes = self.text_edit.toPlainText()

        try:
            self.doc_service.update_document_notes(
                self.doc_data["id"], notes
            )

        except Exception:
            pass

        self.accept()

    def get_notes(self):
        return self.text_edit.toPlainText()
