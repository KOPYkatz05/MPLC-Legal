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
    QGridLayout,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QListWidgetItem,
    QFormLayout,
    QStackedWidget,
    QSizePolicy,
)

from PySide6.QtCore import Qt, QSize, QDate

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
    create_pivot,
    create_scroll_area,
    create_text_edit,
    divider,
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
from utils.i18n import tr, field_label
from utils.logger import logger
from services.workflow_validator import WorkflowValidator

DATE_PLACEHOLDER = QDate(1900, 1, 1)
DATE_EDIT_MAX_WIDTH = 300
OVERVIEW_CONTENT_SPACING = 16
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

STAGE_DISPLAY_NAMES = {
    "INTERPOL": "Interpol",
    "CARNET DE EXTRANJERIA": "Carnet de Extranjeria",
    "PRORROGA": "Prorroga",
    "CANCELACION": "Cancelacion",
}

WORKFLOW_STATUS_LABELS = {
    "NOT STARTED": "Not started",
    "IN PROGRESS": "In progress",
    "WAITING": "Ready to advance",
    "COMPLETED": "Completed",
    "BLOCKED": "Blocked",
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
    return STAGE_DISPLAY_NAMES.get(stage, stage or "Not assigned")


def _workflow_status_label(status):
    return WORKFLOW_STATUS_LABELS.get(status, status.title() if status else "Unknown")


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
        self._placeholder = "Not set"
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

        self.setup_ui()

    def _build_detail_card(self, title, subtitle=None):
        card = create_card()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        card.setLayout(layout)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("SectionHeader")
        layout.addWidget(title_lbl)

        if subtitle:
            subtitle_lbl = QLabel(subtitle)
            subtitle_lbl.setObjectName("MutedText")
            subtitle_lbl.setWordWrap(True)
            layout.addWidget(subtitle_lbl)

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

    def _build_value_label(self, text="Not set", *, elided=False):
        label = ElidedLabel(text) if elided else QLabel(text)
        label.setObjectName("ReadOnlyValue")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if not elided:
            label.setWordWrap(True)
        label.setProperty("state", "empty" if text == "Not set" else "filled")
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

        overlay = QLabel("Not set")
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
            picker.setSpecialValueText("Not set")
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
                picker.setText("Not set")
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
            buttons[0].setText("Not set")
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

    def _set_value_text(self, widget, text, empty_text="Not set"):
        if widget is None:
            return
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
                display = "Derived"
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
        folder_state = "Set" if folder_path else "Not set"

        summary_values = {
            "summary_name_chip": f"Name: {getattr(missionary, 'full_name', '—') or '—'}",
            "summary_stage_chip": f"Stage: {_stage_display_name(getattr(missionary, 'current_stage', None))}",
            "summary_nationality_chip": f"Nationality: {getattr(missionary, 'nationality', None) or 'Not set'}",
            "summary_passport_chip": f"Passport: {getattr(missionary, 'passport_number', None) or 'Not set'}",
            "summary_carnet_chip": f"Carnet: {getattr(missionary, 'carnet_number', None) or 'Not set'}",
            "summary_birthdate_chip": (
                f"Birthdate: {birthdate.strftime('%b %d, %Y')}"
                if birthdate
                else "Birthdate: Not set"
            ),
            "summary_folder_chip": f"Folder: {folder_state}",
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

        header = create_card(object_name="PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(
            32, 18, 32, 18
        )

        header_layout.setSpacing(12)

        header.setLayout(header_layout)

        name_stage = QVBoxLayout()

        name_stage.setSpacing(4)

        self.name_label = QLabel("—")

        self.name_label.setObjectName("PageTitle")

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
            "→ Advance Stage",
            "success",
        )

        self.advance_button.setObjectName(
            "AdvanceButton"
        )

        self.advance_button.clicked.connect(
            self._advance_stage
        )

        self.actions_button = create_button(
            "Actions",
            "secondary",
        )

        self.actions_menu = create_menu(
            "",
            self.actions_button,
        )
        self.print_interpol_packet_action = QAction(
            "Print Interpol Packet",
            self.actions_menu,
        )
        self.actions_menu.addAction(
            self.print_interpol_packet_action
        )
        self.print_interpol_packet_action.triggered.connect(
            self._print_interpol_packet
        )
        self.actions_button.setMenu(self.actions_menu)

        self.delete_button = create_button(
            "Delete Missionary",
            "danger",
        )

        self.delete_button.clicked.connect(
            self.delete_missionary
        )

        header_layout.addWidget(self.advance_button)

        header_layout.addWidget(self.actions_button)

        header_layout.addWidget(self.delete_button)

        main_layout.addWidget(header)

        main_layout.addWidget(divider())

        # ==========================================
        # Auto-advance banner (hidden by default)
        # ==========================================

        self.advance_banner = create_card(
            object_name="SuccessBanner"
        )

        self.advance_banner.setVisible(False)

        banner_layout = QHBoxLayout()

        banner_layout.setContentsMargins(
            32, 10, 32, 10
        )

        banner_layout.setSpacing(12)

        self.advance_banner.setLayout(
            banner_layout
        )

        banner_icon = QLabel("✓")

        banner_icon.setObjectName("SuccessIcon")

        self.banner_text = QLabel(
            "All required documents uploaded — "
            "ready to advance to the next stage."
        )

        self.banner_text.setObjectName("SuccessBannerText")

        banner_now_btn = create_button(
            "Advance Now",
            "success",
            fixed_height=30,
        )

        banner_now_btn.clicked.connect(
            self._advance_stage
        )

        banner_layout.addWidget(banner_icon)

        banner_layout.addWidget(self.banner_text)

        banner_layout.addStretch()

        banner_layout.addWidget(banner_now_btn)

        main_layout.addWidget(self.advance_banner)

        # ==========================================
        # Static tabs
        # ==========================================

        self.tabs = create_pivot()
        self.tab_stack = QStackedWidget()
        self._tab_route_indexes = {}
        self.tab_stack.setObjectName("StaticTabStack")

        if self.tabs is not None:
            self.tabs.setObjectName("StaticTabs")
            self.tabs.currentItemChanged.connect(
                self._select_static_tab
            )
            main_layout.addWidget(self.tabs)

        self._build_overview_tab()

        self._build_details_tab_dashboard()

        self._build_notes_tab()

        self._build_timeline_tab()

        if self.tabs is not None:
            self.tabs.setCurrentItem("overview")

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
        if self.tabs is not None:
            self.tabs.addItem(route_key, title)
        return index

    def _select_static_tab(self, route_key):
        index = self._tab_route_indexes.get(route_key)
        if index is not None:
            self.tab_stack.setCurrentIndex(index)

    def _build_overview_tab(self):
        overview_tab = QWidget()

        self._add_static_tab("overview", "Overview", overview_tab)

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
            32, 24, 32, 24
        )

        content_layout.setSpacing(OVERVIEW_CONTENT_SPACING)

        content.setLayout(content_layout)

        content_layout.addWidget(
            self._build_summary_section()
        )

        content_layout.addWidget(
            self._build_workflow_section()
        )

        content_layout.addWidget(
            self._build_open_tasks_section()
        )

        # ---- Documents section ----
        content_layout.addWidget(
            SectionTitle("Documents")
        )

        docs_helper = QLabel(
            "Start here if you need to add files. Upload one document, or batch upload several files."
        )
        docs_helper.setObjectName("MutedText")
        docs_helper.setWordWrap(True)
        content_layout.addWidget(docs_helper)

        self.upload_button = create_button(
            "Upload Document",
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

        content_layout.addLayout(button_row)

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

        content_layout.addWidget(
            self.documents_list
        )

        # ---- Missing documents section ----
        content_layout.addWidget(
            SectionTitle("Missing Documents")
        )

        missing_helper = QLabel(
            "These are the files still needed to move the missionary forward. The top item is the highest priority."
        )
        missing_helper.setObjectName("MutedText")
        missing_helper.setWordWrap(True)
        content_layout.addWidget(missing_helper)

        self.missing_documents_list = create_list_widget()
        self.missing_documents_list.setSpacing(8)
        self.missing_documents_list.setMinimumHeight(
            MISSING_LIST_MIN_HEIGHT
        )
        tune_fluent_scrollable(self.missing_documents_list)
        _set_scroll_step(self.missing_documents_list)

        content_layout.addWidget(
            self.missing_documents_list
        )

        content_layout.addStretch()

        scroll.setWidget(content)

        tab_layout.addWidget(scroll)

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

        title = QLabel("Overview at a glance")
        title.setObjectName("PanelTitle")

        title_stack.addWidget(title)

        header_row.addLayout(title_stack)
        header_row.addStretch()

        self.summary_stage_chip = QLabel("No missionary loaded")
        self.summary_stage_chip.setObjectName("StageBadge")
        header_row.addWidget(self.summary_stage_chip)

        layout.addLayout(header_row)

        metrics_grid = QGridLayout()
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(12)
        metrics_grid.setVerticalSpacing(12)

        self.summary_current_stage_card = StatCard(
            "—",
            "Current stage",
            subtitle="Where this missionary is right now",
            color="#2563EB",
        )
        self.summary_complete_card = StatCard(
            "0",
            "Required docs complete",
            subtitle="For the current stage",
            color="#059669",
        )
        self.summary_missing_card = StatCard(
            "0",
            "Required docs missing",
            subtitle="Needs attention before advancing",
            color="#DC2626",
        )
        self.summary_upload_card = StatCard(
            "—",
            "Last upload",
            subtitle="Most recent file added",
            color="#7C3AED",
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

        action_title = QLabel("Recommended next step")
        action_title.setObjectName("SectionHeader")

        self.summary_next_action_label = QLabel(
            "Select a missionary to see the next step."
        )
        self.summary_next_action_label.setWordWrap(True)

        self.summary_activity_label = QLabel("")
        self.summary_activity_label.setObjectName("MutedText")
        self.summary_activity_label.setWordWrap(True)

        self.summary_tip_label = QLabel(
            "Tip: start with the missing documents in the current stage. If you are unsure, upload one file at a time and review the status after each upload."
        )
        self.summary_tip_label.setObjectName("MutedText")
        self.summary_tip_label.setWordWrap(True)

        action_layout.addWidget(action_title)
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

        layout.addWidget(SectionTitle("Workflow stages"))

        helper = QLabel(
            "The current stage is highlighted. Use the update button if a stage status needs to change."
        )
        helper.setObjectName("MutedText")
        helper.setWordWrap(True)
        layout.addWidget(helper)

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
            32, 24, 32, 24
        )

        details_layout.setSpacing(0)

        details_content.setLayout(details_layout)

        card = create_card()

        form = QFormLayout()

        form.setContentsMargins(24, 20, 24, 20)

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
        self.tramite_usuario_label = make_field()
        self.tramite_contrasena_label = make_field()
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
                self.tramite_usuario_label,
            ),
            (
                "tramite_contrasena",
                "Trámite Contraseña:",
                self.tramite_contrasena_label,
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

        self.save_dates_btn = create_button(tr("save_dates"), "primary")
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

        self._add_static_tab("details", "Details", details_outer)

        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        details_outer.setLayout(outer_layout)

        scroll = create_scroll_area(single_direction=True)
        tune_fluent_scrollable(scroll)

        details_content = QWidget()
        details_content.setObjectName("PageSurface")

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(32, 24, 32, 24)
        content_layout.setSpacing(14)
        details_content.setLayout(content_layout)

        summary_card, summary_layout = self._build_detail_card(
            "At a glance",
            "Quick scan of the most important facts.",
        )
        summary_layout.setSpacing(8)
        self.summary_chip_grid = QGridLayout()
        self.summary_chip_grid.setContentsMargins(0, 0, 0, 0)
        self.summary_chip_grid.setHorizontalSpacing(10)
        self.summary_chip_grid.setVerticalSpacing(8)
        summary_layout.addLayout(self.summary_chip_grid)

        self.summary_name_chip = self._build_badge_chip("Name: —")
        self.summary_stage_chip = self._build_badge_chip("Stage: —")
        self.summary_nationality_chip = self._build_badge_chip("Nationality: —")
        self.summary_passport_chip = self._build_badge_chip("Passport: —")
        self.summary_carnet_chip = self._build_badge_chip("Carnet: —")
        self.summary_birthdate_chip = self._build_badge_chip("Birthdate: —")
        self.summary_folder_chip = self._build_badge_chip("Folder: Not set")

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

        content_layout.addWidget(summary_card)

        self.nationality_label = self._build_value_label()
        self.passport_label = self._build_value_label()
        self.carnet_number_input = create_line_edit("Carnet Number")
        self._text_edits["carnet_number"] = self.carnet_number_input
        self.tramite_usuario_label = self._build_value_label()
        self.tramite_contrasena_label = self._build_value_label()
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
            "Identity",
            "Read-only identity values and the folder link.",
        )
        identity_grid = QGridLayout()
        identity_grid.setContentsMargins(0, 0, 0, 0)
        identity_grid.setHorizontalSpacing(10)
        identity_grid.setVerticalSpacing(8)
        identity_layout.addLayout(identity_grid)

        identity_grid.addWidget(
            self._build_field_block("Nationality", self.nationality_label),
            0,
            0,
        )
        identity_grid.addWidget(
            self._build_field_block(
                "Passport Number",
                self.passport_label,
            ),
            0,
            1,
        )
        identity_grid.addWidget(
            self._build_field_block(
                "Carnet Number",
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
            "Open Folder",
            "subtle",
            fixed_height=28,
        )
        self.folder_open_btn.setEnabled(False)
        self.folder_open_btn.clicked.connect(self._open_folder_path)
        folder_action_layout.addWidget(self.folder_open_btn)
        folder_action_layout.addStretch()
        folder_layout.addWidget(folder_action_row)

        identity_grid.addWidget(
            self._build_field_block("Folder Path", folder_widget),
            2,
            1,
        )

        credentials_card, credentials_layout = self._build_detail_card(
            "Credentials",
            "Usually manual; document uploads can still populate these fields.",
        )
        credentials_grid = QGridLayout()
        credentials_grid.setContentsMargins(0, 0, 0, 0)
        credentials_grid.setHorizontalSpacing(10)
        credentials_grid.setVerticalSpacing(8)
        credentials_layout.addLayout(credentials_grid)

        for col, (field_key, label_text, value_label) in enumerate(
            [
                ("tramite_usuario", "Tramite Usuario", self.tramite_usuario_label),
                (
                    "tramite_contrasena",
                    "Tramite Contrasena",
                    self.tramite_contrasena_label,
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
            "Legal timeline",
            "Editable dates with a compact source badge when populated from a document.",
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

        columns = QWidget()
        columns_layout = QHBoxLayout()
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(16)
        columns.setLayout(columns_layout)

        left_column = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)
        left_column.setLayout(left_layout)
        left_layout.addWidget(identity_card)
        left_layout.addStretch()

        right_column = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)
        right_column.setLayout(right_layout)
        right_layout.addWidget(timeline_card)
        right_layout.addWidget(credentials_card)
        right_layout.addWidget(self._build_residency_timeline_card())
        right_layout.addStretch()

        columns_layout.addWidget(left_column, 1)
        columns_layout.addWidget(right_column, 1)
        content_layout.addWidget(columns)

        self.save_dates_btn = create_button(tr("save_dates"), "primary")
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

        title = QLabel("Residency timeline")
        title.setObjectName("SectionHeader")
        layout.addWidget(title)

        hint = QLabel(
            "Current residency expiration is derived from the original "
            "arrival date and approved prorrogas."
        )
        hint.setObjectName("MutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._residency_timeline_labels = {}
        for key, label_text in [
            ("initial", "Initial residency"),
            ("prorroga_1", "Prorroga 1"),
            ("prorroga_2", "Prorroga 2"),
        ]:
            row = QWidget()
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row.setLayout(row_layout)

            label = QLabel(label_text)
            label.setObjectName("MiniMutedText")
            value_wrap = QWidget()
            value_layout = QVBoxLayout()
            value_layout.setContentsMargins(0, 0, 0, 0)
            value_layout.setSpacing(2)
            value_wrap.setLayout(value_layout)

            status = create_info_badge("Pending")
            status.setObjectName("SummaryBadge")
            status.setProperty("tone", "subtle")

            target = QLabel("Target: Not set")
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

        title = QLabel("Open Tasks")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch()

        add_btn = create_button(
            "Add Task",
            "primary",
            fixed_height=30,
        )
        add_btn.clicked.connect(self._add_missionary_task)
        header.addWidget(add_btn)

        office_btn = create_button(
            "Open Office Work",
            "secondary",
            fixed_height=30,
        )
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

        self._add_static_tab("notes", "Notes", notes_tab)

        notes_layout = QVBoxLayout()

        notes_layout.setContentsMargins(
            32, 24, 32, 24
        )

        notes_layout.setSpacing(12)

        notes_tab.setLayout(notes_layout)

        notes_tab.setObjectName("PageSurface")

        hint = QLabel(
            "Use this space to record status "
            "updates, reminders, or any notes "
            "about this missionary's legal process."
        )

        hint.setObjectName("MutedText")

        hint.setWordWrap(True)

        notes_layout.addWidget(hint)

        self.notes_text = create_text_edit()

        self.notes_text.setPlaceholderText(
            "Enter notes here..."
        )

        self.notes_text.setObjectName("NotesEditor")

        notes_layout.addWidget(
            self.notes_text, stretch=1
        )

        save_notes_btn = create_button("Save Notes", "primary")

        save_notes_btn.setFixedWidth(140)

        save_notes_btn.clicked.connect(
            self._save_notes
        )

        notes_layout.addWidget(
            save_notes_btn,
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
                msg = (
                    f"All required documents for "
                    f"{stage} are uploaded — "
                    f"ready to advance to "
                    f"{next_stage}."
                )

            else:
                msg = (
                    f"All required documents for "
                    f"{stage} are uploaded."
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
                "Open Folder",
                "This missionary does not have a folder path yet.",
                kind="warning",
            )
            return

        path = Path(folder_path)
        if not path.exists():
            show_message(
                self,
                "Open Folder",
                f"Folder not found:\n{folder_path}",
                kind="warning",
            )
            return

        try:
            open_document_with_default_app(path)
        except Exception:
            logger.exception("Failed to open folder path")
            show_message(
                self,
                "Open Folder",
                "Could not open the folder path.",
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
                tr("save_dates"),
                tr("dates_saved"),
            )
            self._reload_missionary()
        except Exception:
            logger.exception("Failed to save dates")
            show_message(
                self,
                tr("save_dates"),
                tr("dates_save_failed"),
                kind="critical",
            )

    def retranslate_ui(self):
        if hasattr(self, "save_dates_btn"):
            self.save_dates_btn.setText(tr("save_dates"))

    def _show_doc_context_menu(self, pos):
        item = self.documents_list.itemAt(pos)

        if not item:
            return

        doc_id = item.data(Qt.UserRole)

        if doc_id is None:
            return

        menu = create_menu("", self)

        view_action = menu.addAction("View Document")

        notes_action = menu.addAction(
            "View / Edit Notes"
        )

        ocr_action = menu.addAction(
            tr("view_extracted_data")
        )

        delete_action = menu.addAction(
            tr("delete_document")
        )

        open_action = menu.addAction("Open Externally")

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
            "Print Interpol Packet"
        )

        action = menu.exec(
            self.actions_button.mapToGlobal(
                self.actions_button.rect().bottomLeft()
            )
        )

        if action == print_interpol_action:
            self._print_interpol_packet()

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
                "Missing Packet Documents",
                (
                    "Some Interpol packet documents are missing:\n\n"
                    f"{missing_text}\n\n"
                    "Do you want to continue and print the available documents?"
                ),
                kind="warning",
                buttons="yes_no",
            )

            if response not in {1, 16384}:
                return

        if not packet_docs:
            show_message(
                self,
                "No Documents to Print",
                "No Interpol packet documents are available to print.",
                kind="warning",
            )
            return

        try:
            temp_path = self._create_interpol_packet_temp_path()

            self._build_interpol_packet_pdf(packet_docs, temp_path)
            self._open_packet_in_acrobat_print_viewer(temp_path)

        except Exception:
            logger.exception("Failed to print Interpol packet")
            show_message(
                self,
                "Print Failed",
                "The Interpol packet could not be prepared for printing.",
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
            label = DOCUMENTS.get(doc_type, {}).get(
                "label",
                doc_type,
            )
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

            self._add_acrobat_print_open_action(packet)
            packet.save(output_path)

        finally:
            packet.close()

    def _add_acrobat_print_open_action(self, packet):
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

    def _open_packet_in_acrobat_print_viewer(self, packet_path):
        acrobat_path = self._find_acrobat_executable()

        if acrobat_path is None:
            show_message(
                self,
                "Adobe Acrobat Not Found",
                (
                    "Adobe Acrobat could not be found on this computer. "
                    "Install Acrobat or set the correct Acrobat path before "
                    "printing the Interpol packet."
                ),
                kind="warning",
            )
            return

        logger.info(
            "Opening Interpol packet in Acrobat print UI: %s",
            packet_path,
        )
        subprocess.Popen(
            [
                str(acrobat_path),
                "/n",
                str(packet_path),
            ],
            cwd=str(Path(packet_path).parent),
        )

    def _find_acrobat_executable(self):
        candidates = [
            Path(
                r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe"
            ),
            Path(
                r"C:\Program Files (x86)\Adobe\Acrobat DC\Acrobat\x86\Acrobat\Acrobat.exe"
            ),
            Path(os.environ.get("ProgramFiles", ""))
            / "Adobe"
            / "Acrobat DC"
            / "Acrobat"
            / "Acrobat.exe",
            Path(os.environ.get("ProgramFiles", ""))
            / "Adobe"
            / "Acrobat"
            / "Acrobat.exe",
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "Adobe"
            / "Acrobat DC"
            / "Acrobat"
            / "Acrobat.exe",
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "Adobe"
            / "Acrobat Reader DC"
            / "Reader"
            / "AcroRd32.exe",
            Path(os.environ.get("ProgramFiles", ""))
            / "Adobe"
            / "Acrobat Reader DC"
            / "Reader"
            / "AcroRd32.exe",
        ]

        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate

        search_roots = [
            Path(os.environ.get("ProgramFiles", "")) / "Adobe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Adobe",
        ]

        for root in search_roots:
            if not root.exists():
                continue
            for executable_name in ("Acrobat.exe", "AcroRd32.exe"):
                try:
                    match = next(root.rglob(executable_name), None)
                except Exception:
                    match = None
                if match and match.exists():
                    return match

        return None

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
                    "File Not Found",
                    f"Cannot open file:\n{file_path}",
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
                    "File Not Found",
                    "Cannot open document file.",
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
        self.stage_badge.setText(f"  {stage}  ")
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
        self._set_value_text(
            self.tramite_usuario_label,
            getattr(missionary, "tramite_usuario", None),
        )
        self._set_value_text(
            self.tramite_contrasena_label,
            getattr(missionary, "tramite_contrasena", None),
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
                status_text = "Approved"
                target_text = f"Expires: {target}"
                document_id = row.get("document_id")
                if document_id:
                    target_text += f" - Document #{document_id}"
            else:
                status_text = "Pending"
                target_text = f"Target: {target}"

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
                "No workflow stages available."
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
                "No documents uploaded yet.",
                "Use Upload Document to add the first file, or Batch Upload if you already have several files ready.",
            )
            empty.setSizeHint(widget.sizeHint())
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            self.documents_list.addItem(empty)
            self.documents_list.setItemWidget(empty, widget)
            return

        for doc in documents:
            doc_config = DOCUMENTS.get(doc.document_type, {})
            label = doc_config.get(
                "label", doc.document_type
            )

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
                "No open tasks for this missionary.",
                "Use Add Task when there is office work to track.",
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
        card = create_card()
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        card.setLayout(layout)

        if task.get("is_group_task"):
            accent = QFrame()
            accent.setFixedWidth(4)
            accent.setStyleSheet(
                "QFrame { background-color: #7C3AED; border-radius: 2px; }"
            )
            layout.addWidget(accent)

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(4)

        title = QLabel(task.get("title", "Untitled task"))
        title.setObjectName("StrongText")
        copy.addWidget(title)

        status_label = (
            "Waiting"
            if task.get("status") == "WAITING"
            else "To Do"
        )
        meta_parts = [
            task.get("priority", "NORMAL").title(),
            status_label,
        ]
        if task.get("due_date"):
            meta_parts.append(task["due_date"].strftime("%b %d, %Y"))
        else:
            meta_parts.append("No due date")
        if task.get("waiting_reason_label"):
            meta_parts.append(task["waiting_reason_label"])
        if task.get("is_group_task"):
            shared_label = f"Shared with {task.get('missionary_count', 0)} missionaries"
            if task.get("group_scope_label"):
                shared_label = f"{shared_label} - {task['group_scope_label']}"
            meta_parts.append(shared_label)
        meta = QLabel("  |  ".join(meta_parts))
        meta.setObjectName("MutedText")
        meta.setWordWrap(True)
        copy.addWidget(meta)
        layout.addLayout(copy, stretch=1)

        done_btn = create_button("Done", "success", fixed_height=28)
        done_btn.clicked.connect(
            lambda _=None, task_id=task["id"]: self._complete_missionary_task(task_id)
        )
        layout.addWidget(done_btn)

        edit_btn = create_button("Edit", "secondary", fixed_height=28)
        edit_btn.clicked.connect(
            lambda _=None, task_data=task: self._edit_missionary_task(task_data)
        )
        layout.addWidget(edit_btn)

        return card

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
                "All required documents are uploaded.",
                "This missionary is clear to move forward once any final review is done.",
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
            else "No uploads yet"
        )

        latest_activity = self._find_latest_activity()

        if missing_current:
            next_doc = DOCUMENTS.get(
                missing_current[0], {}
            ).get("label", missing_current[0])
            next_text = (
                f"Next step: upload {next_doc}."
            )
        elif stage and stage in WORKFLOW_STAGES:
            next_index = WORKFLOW_STAGES.index(stage) + 1
            if next_index < len(WORKFLOW_STAGES):
                next_text = (
                    f"Next step: review the {stage_display} requirements, then advance to {_stage_display_name(WORKFLOW_STAGES[next_index])}."
                )
            else:
                next_text = (
                    "Next step: all stages are complete. Review the notes and finalize the record."
                )
        else:
            next_text = (
                "Next step: assign a workflow stage and start uploading the required documents."
            )

        self.summary_next_action_label.setText(next_text)
        self.summary_activity_label.setText(
            "Last update: "
            + (_format_datetime(latest_activity) or "No activity yet")
            + (
                f" | Last upload: {_format_datetime(latest_upload)}"
                if latest_upload
                else " | Last upload: No uploads yet"
            )
        )

        if missing_current:
            tip = (
                "Tip: start with the missing documents shown below. If you are unsure, upload one file at a time and review the status after each upload."
            )
        else:
            tip = (
                "Tip: everything required for the current stage is uploaded. Use Advance Stage when you are ready."
            )
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
        card = create_card()
        card.setMinimumHeight(EMPTY_STATE_MIN_HEIGHT)
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        card.setLayout(layout)

        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)

        text_lbl = QLabel(text)
        text_lbl.setWordWrap(True)

        layout.addWidget(title_lbl)
        layout.addWidget(text_lbl)
        return card

    def _build_workflow_stage_widget(self, workflow, is_current=False):
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
            "Update status",
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
            return "Everything required for this stage is uploaded. You can advance now."
        if workflow.status == "COMPLETED":
            return "This stage has already been completed."
        if workflow.status == "BLOCKED":
            return "This stage still needs attention before it can move forward."
        if is_current and missing:
            return (
                f"{len(missing)} required document(s) are still missing for this stage."
            )
        if is_current:
            return "This is the active stage."
        return "Use this row if you need to update the stage status."

    def _build_document_item_widget(self, doc, label, pixmap=None):
        card = create_card()
        card.setMinimumHeight(DOCUMENT_CARD_MIN_HEIGHT)
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        card.setLayout(layout)

        thumb = QLabel()
        thumb.setObjectName("DocumentThumb")
        thumb.setFixedSize(54, 64)
        thumb.setAlignment(Qt.AlignCenter)

        if pixmap and not pixmap.isNull():
            thumb.setPixmap(
                pixmap.scaled(
                    48, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        else:
            thumb.setText("DOC")

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title = QLabel(label)

        status = QLabel("Uploaded")

        title_row.addWidget(title)
        title_row.addWidget(status)
        title_row.addStretch()

        file_name = QLabel(doc.file_name)
        file_name.setWordWrap(True)

        meta_text = []
        uploaded_at = getattr(doc, "uploaded_at", None)
        if uploaded_at:
            meta_text.append(f"Uploaded {uploaded_at.strftime('%b %d, %Y')}")
        if doc.workflow_stage:
            meta_text.append(
                f"Stage: {_stage_display_name(doc.workflow_stage)}"
            )
        if not meta_text:
            meta_text.append("Added to the missionary record")

        meta = QLabel("  \u2022  ".join(meta_text))
        meta.setWordWrap(True)

        copy.addLayout(title_row)
        copy.addWidget(file_name)
        copy.addWidget(meta)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        view_btn = create_button("View", "primary", fixed_height=28)
        view_btn.clicked.connect(
            lambda checked=False, doc_id=doc.id: self._open_document_viewer(doc_id)
        )
        notes_btn = create_button("Notes", "secondary", fixed_height=28)
        notes_btn.clicked.connect(
            lambda checked=False, doc_id=doc.id: self._open_document_notes(doc_id)
        )
        open_btn = create_button("Open", "subtle", fixed_height=28)
        open_btn.clicked.connect(
            lambda checked=False, doc_id=doc.id: self._open_document_file(doc_id)
        )
        delete_btn = create_button(
            tr("delete_document"),
            "danger",
            fixed_height=28,
        )
        delete_btn.clicked.connect(
            lambda checked=False, doc_id=doc.id: self._delete_document(doc_id)
        )

        actions.addStretch()
        actions.addWidget(view_btn)
        actions.addWidget(notes_btn)
        actions.addWidget(open_btn)
        actions.addWidget(delete_btn)

        layout.addWidget(thumb)
        layout.addLayout(copy, stretch=1)
        layout.addLayout(actions)
        return card

    def _build_missing_stage_widget(self, stage_name, missing_docs, is_current=False):
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
            "Always required"
            if stage_name == "Always required"
            else f"Required for {_stage_display_name(stage_name)}"
        )
        title = QLabel(title_text)
        title.setObjectName("MissingStageTitle")

        if stage_name == "Always required":
            badge_text = "Highest priority"
        elif is_current:
            badge_text = "Current priority"
        else:
            badge_text = "Upcoming"

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
            doc_label = DOCUMENTS.get(doc_key, {}).get(
                "label", doc_key
            )
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
            return f"{count} general document(s) are still needed for the case."
        return f"{count} document(s) are still needed before this stage can move forward."

    def _missing_doc_reason(self, doc_key, stage_name):
        config = DOCUMENTS.get(doc_key, {})
        ocr_fields = config.get("ocr_fields", [])
        if stage_name == "Always required":
            base = "Needed for identity checks and the full case record."
        else:
            base = f"Required before {_stage_display_name(stage_name)} can be completed."
        if ocr_fields:
            return base + " It also helps fill in the missionary record automatically."
        return base

    def _show_workflow_context_menu(self, pos):
        item = self.workflow_list.itemAt(pos)
        if not item:
            return

        workflow_id = item.data(Qt.UserRole)
        if workflow_id is None:
            return

        menu = create_menu("", self)
        update_action = menu.addAction("Update status")
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

        self._add_static_tab("timeline", "Timeline", timeline_tab)

        timeline_layout = QVBoxLayout()

        timeline_layout.setContentsMargins(
            32, 24, 32, 24
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
                        "No stage transitions recorded."
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
                        h.from_stage or "Started"
                    )

                    text = (
                        f"{date_str}\n"
                        f"{from_str} \u2192 {h.to_stage}"
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
                "Saved",
                "Notes saved successfully.",
            )

        except Exception:
            logger.exception(
                "Failed to save notes"
            )

            show_message(
                self,
                "Error",
                "Failed to save notes.",
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
            "Confirm Delete",
            "Are you sure you want to delete "
            "this missionary?\n\n"
            "The missionary will be moved to "
            "TRASH.",
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

        self.setWindowTitle("Change Status")
        self.surface = setup_dialog_shell(
            self,
            surface_width=420,
            use_masked_shell=True,
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        self.surface.setLayout(layout)

        title = SubtitleLabel("Change workflow status")
        layout.addWidget(title)

        helper = BodyLabel(
            "Choose the status that best describes what is happening "
            "with this workflow stage."
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

        cancel_btn = create_button("Cancel", "secondary")
        cancel_btn.clicked.connect(self.reject)

        save_btn = create_button("Update Status", "primary")
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
            f"Notes — {doc_data['label']}"
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

        title = SubtitleLabel(f"Notes for {doc_data['label']}")

        layout.addWidget(title)

        file_label = BodyLabel(
            f"File: {doc_data['file_name']}"
        )

        file_label.setObjectName("MutedText")

        layout.addWidget(file_label)

        self.text_edit = create_plain_text_edit()

        self.text_edit.setPlainText(
            doc_data.get("notes", "")
        )

        self.text_edit.setPlaceholderText(
            "Enter notes for this document..."
        )

        self.text_edit.setObjectName("DocumentNotesEditor")

        layout.addWidget(self.text_edit, stretch=1)

        cancel_btn = create_button("Cancel", "secondary")

        cancel_btn.clicked.connect(self.reject)

        save_btn = create_button("Save Notes", "primary")

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
