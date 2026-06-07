import os
import json
import subprocess
import sys

from datetime import date

from pathlib import Path

from PySide6.QtWidgets import (
    QGridLayout,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QFormLayout,
    QStackedWidget,
    QSizePolicy,
)

from PySide6.QtCore import Qt, QSize, QDate

from services.workflow_service import WorkflowService
from services.document_service import DocumentService
from services.missionary_service import MissionaryService
from services.document_image_export_service import (
    DocumentImageExportService,
)
from services.thumbnail_service import ThumbnailService
from ui.dialogs.ocr_data_view_dialog import OcrDataViewDialog
from ui.dialogs.stage_advance_dialog import StageAdvanceDialog
from ui.dialogs.upload_session_dialog import UploadSessionDialog
from ui.foundation import (
    BodyLabel,
    DialogFooter,
    MaskDialogBase,
    SectionTitle,
    StatCard,
    SubtitleLabel,
    create_button,
    create_card,
    create_combo_box,
    create_date_picker,
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
    required_documents_for_missionary,
)
from utils.i18n import tr, field_label
from utils.logger import logger
from services.workflow_validator import WorkflowValidator

DATE_PLACEHOLDER = QDate(1900, 1, 1)
DATE_EDIT_MAX_WIDTH = 180
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
    "passport_expiration",
    "residency_expiration",
    "prorroga_expiration",
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


class MissionaryDetailPage(QWidget):
    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("MissionaryDetailPage")

        self.main_window = main_window

        logger.info("Initializing MissionaryDetailPage")

        self.workflow_service = WorkflowService()

        self.document_service = DocumentService()

        self.missionary_service = MissionaryService()

        self.workflow_validator = WorkflowValidator()

        self.thumb_service = ThumbnailService()

        self.image_export_service = DocumentImageExportService()

        self._document_data = []
        self._date_edits = {}
        self._date_source_labels = {}
        self._date_empty_on_load = set()

        self.setup_ui()

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

        self.delete_button = create_button(
            "Delete Missionary",
            "danger",
        )

        self.delete_button.clicked.connect(
            self.delete_missionary
        )

        header_layout.addWidget(self.advance_button)

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

        self._build_details_tab()

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

        for field_key in EDITABLE_DATE_FIELDS:
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
        details_layout.addLayout(btn_row)

        details_layout.addStretch()

        scroll.setWidget(details_content)

        outer_layout.addWidget(scroll)

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

            # Refresh missionaries list too
            missionaries_page = (
                self.main_window.stack.widget(1)
            )

            if missionaries_page:
                missionaries_page.load_data()

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
        dialog.exec()

        if dialog.saved_any():
            self._reload_missionary()

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
        dialog.exec()

        if dialog.saved_any():
            self._reload_missionary()

        return

    def _update_field_sources(self, missionary):
        sources = {}
        if missionary.field_sources:
            try:
                sources = json.loads(missionary.field_sources)
            except (json.JSONDecodeError, TypeError):
                sources = {}

        for field_key, source_lbl in self._date_source_labels.items():
            info = sources.get(field_key)
            if info and info.get("label"):
                source_lbl.setText(
                    tr("field_from_source", label=info["label"])
                )
            else:
                source_lbl.setText("")

    def _save_dates(self):
        if not hasattr(self, "current_missionary"):
            return

        updates = {}
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

        self.nationality_label.setText(
            missionary.nationality or "-"
        )
        self.passport_label.setText(
            missionary.passport_number or "-"
        )

        self._date_empty_on_load = set()
        for field_key, date_edit in self._date_edits.items():
            value = getattr(missionary, field_key, None)
            if value:
                date_edit.setDate(
                    QDate(value.year, value.month, value.day)
                )
            else:
                date_edit.setDate(DATE_PLACEHOLDER)
                self._date_empty_on_load.add(field_key)

        self._update_field_sources(missionary)

        self.folder_label.setText(
            missionary.folder_path or "-"
        )

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
        self.load_documents(documents)
        self.load_missing_documents(documents)
        self._refresh_overview_summary(workflows, documents)
        self._load_timeline()
        self._update_advance_banner()

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

        actions.addStretch()
        actions.addWidget(view_btn)
        actions.addWidget(notes_btn)
        actions.addWidget(open_btn)

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
