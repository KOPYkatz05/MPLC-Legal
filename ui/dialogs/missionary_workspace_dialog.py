from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None

from services.document_service import DocumentService
from services.residency_service import ResidencyService
from services.secretary_work_service import SecretaryWorkService
from services.workspace_block_registry import (
    BLOCK_LABELS,
    block_definition,
    block_presentation,
)
from services.workspace_layout import (
    WORKSPACE_GRID_COLUMNS,
    normalize_workspace_layout,
    validate_block_layout,
)
from services.workflow_service import WorkflowService
from services.workflow_validator import WorkflowValidator
from ui.dialogs.document_viewer_dialog import (
    DocumentPreviewWidget,
    DocumentViewerDialog,
)
from ui.dialogs.office_work_dialogs import TaskDialog
from ui.foundation import (
    DialogFooter,
    MaskDialogBase,
    SubtitleLabel,
    create_button,
    create_card,
    create_info_badge,
    create_scroll_area,
    setup_dialog_shell,
    show_message,
    tune_fluent_scrollable,
)
from utils.constants import (
    DOCUMENTS,
    WORKFLOW_STAGES,
    required_documents_for_missionary,
)
from utils.i18n import field_label
from utils.language_helper import ui_text as tr
from utils.logger import logger
from ui.widgets.missionary_block_widgets import (
    build_document_card,
    build_empty_state_card,
    build_missing_stage_card,
    build_task_card,
    build_workflow_stage_card,
    document_label,
    format_value,
    stage_display_name,
    workflow_status_label as status_label,
)


FIELD_KEYS = [
    "full_name",
    "missionary_code",
    "nationality",
    "passport_number",
    "carnet_number",
    "date_of_birth",
    "arrival_date",
    "visa_expiration",
    "passport_expiration",
    "residency_expiration",
    "prorroga_expiration",
    "carnet_issue_date",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
    "folder_path",
    "current_stage",
]

WORKSPACE_DIALOG_BODY_SIZES = {
    "medium": (784, 520),
    "large": (1004, 620),
    "wide": (1184, 660),
}
WORKSPACE_RUNTIME_ROW_HEIGHT = 96


def stage_display_name(stage):
    if not stage:
        return tr("missionary_detail_not_assigned")
    keys = {
        "INTERPOL": "missionary_detail_stage_interpol",
        "CARNET DE EXTRANJERIA": "missionary_detail_stage_carnet_de_extranjeria",
        "PRORROGA": "missionary_detail_stage_prorroga",
        "CANCELACION": "missionary_detail_stage_cancelacion",
    }
    return tr(keys.get(stage, stage))


def document_label(document_type):
    key = {
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
    }.get(document_type)
    if key:
        return tr(key)
    return DOCUMENTS.get(document_type, {}).get("label", document_type or "")


def status_label(status):
    keys = {
        "NOT STARTED": "missionary_detail_status_not_started",
        "IN PROGRESS": "missionary_detail_status_in_progress",
        "WAITING": "missionary_detail_status_waiting",
        "COMPLETED": "missionary_detail_status_completed",
        "BLOCKED": "missionary_detail_status_blocked",
    }
    return tr(keys.get(status, status or ""))


def format_value(value):
    if value is None or value == "":
        return tr("missionary_detail_not_set")
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    return str(value)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)


@dataclass
class MissionaryWorkspaceContext:
    missionary: object
    documents: list
    workflows: list
    tasks: list
    residency_rows: list
    missing_groups: list

    @classmethod
    def load(cls, missionary):
        document_service = DocumentService()
        workflow_service = WorkflowService()
        secretary_service = SecretaryWorkService()
        residency_service = ResidencyService()

        documents = document_service.get_documents(missionary.id)
        workflows = workflow_service.get_workflows(missionary.id)
        tasks = secretary_service.list_tasks(missionary_id=missionary.id)
        residency_rows = residency_service.get_residency_timeline(missionary.id)
        missing_groups = cls._missing_groups(missionary, documents)
        return cls(
            missionary=missionary,
            documents=documents,
            workflows=workflows,
            tasks=tasks,
            residency_rows=residency_rows,
            missing_groups=missing_groups,
        )

    @staticmethod
    def _missing_groups(missionary, documents):
        uploaded_types = {doc.document_type for doc in documents}
        current_stage = getattr(missionary, "current_stage", None)
        groups = []
        general_missing = [
            doc_key
            for doc_key, config in DOCUMENTS.items()
            if config.get("required")
            and config.get("stage") is None
            and doc_key not in uploaded_types
            and doc_key != "OTHER"
        ]
        if general_missing:
            groups.append(("Always required", general_missing, True))

        stage_order = []
        if current_stage in WORKFLOW_STAGES:
            stage_order.append(current_stage)
        stage_order.extend(stage for stage in WORKFLOW_STAGES if stage != current_stage)
        for stage_name in stage_order:
            missing = [
                doc_key
                for doc_key in required_documents_for_missionary(
                    stage_name,
                    missionary,
                )
                if doc_key not in uploaded_types
            ]
            if missing:
                groups.append((stage_name, missing, stage_name == current_stage))
        return groups


class WorkspaceBlockFactory:
    def __init__(self, dialog):
        self.dialog = dialog

    def build(self, block):
        block_type = block.get("type")
        builders = {
            "personal_info": self.personal_info,
            "documents": self.documents,
            "document_viewer": self.document_viewer,
            "web_viewer": self.web_viewer,
            "missing_documents": self.missing_documents,
            "workflow": self.workflow,
            "open_tasks": self.open_tasks,
            "notes": self.notes,
            "residency_timeline": self.residency_timeline,
            "quick_actions": self.quick_actions,
            "appointments": self.appointments,
            "status_summary": self.status_summary,
            "document_checklist": self.document_checklist,
            "task_board": self.task_board,
            "notes_editor": self.notes,
            "contact_info": self.contact_info_polished,
            "workflow_next_steps": self.workflow_next_steps_polished,
            "recent_activity": self.recent_activity_polished,
            "link_list": self.link_list_polished,
        }
        builder = builders.get(block_type)
        if builder is None:
            return self.unsupported(block)
        return builder(block)

    def card(self, block):
        card = create_card()
        height = block.get("height", "normal")
        card.setMinimumHeight({"compact": 160, "normal": 260, "tall": 420}.get(height, 260))
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        presentation = self.presentation(block)
        margins = {
            "compact": (14, 12, 14, 12),
            "comfortable": (18, 16, 18, 16),
            "spacious": (22, 20, 22, 20),
        }.get(presentation["density"], (18, 16, 18, 16))
        spacing = {"compact": 6, "comfortable": 10, "spacious": 14}.get(
            presentation["density"],
            10,
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        card.setLayout(layout)
        definition = block_definition(block.get("type"))
        header = QHBoxLayout()
        icon = QLabel(definition.get("icon", "□"))
        icon.setObjectName("MutedText")
        title = QLabel(block.get("title") or tr(BLOCK_LABELS.get(block.get("type"), "workspace_block_unsupported")))
        title.setObjectName("PanelTitle")
        header.addWidget(icon)
        header.addWidget(title, stretch=1)
        if definition.get("supports_actions") and not getattr(self.dialog, "preview_mode", False):
            action_hint = QLabel("⋯")
            action_hint.setObjectName("MutedText")
            header.addWidget(action_hint)
        layout.addLayout(header)
        return card, layout

    def presentation(self, block):
        return block_presentation(block)

    def variant(self, block):
        return self.presentation(block)["variant"]

    def is_variant(self, block, *variants):
        return self.variant(block) in variants

    def limited_items(self, block, items):
        presentation = self.presentation(block)
        limit = presentation["content_limit"]
        items = list(items or [])
        return items[:limit], max(0, len(items) - limit)

    def add_overflow_hint(self, layout, hidden_count, label="View all"):
        if hidden_count <= 0:
            return
        hint = QLabel(f"{label} ({hidden_count} more)")
        hint.setObjectName("MutedText")
        layout.addWidget(hint)

    def metric_grid(self, layout, metrics):
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, metric in enumerate(metrics):
            label, value, *rest = metric
            detail = rest[0] if rest else None
            grid.addWidget(self.metric_card(label, value, detail), index // 2, index % 2)
        layout.addLayout(grid)

    def empty(self, title, detail):
        return build_empty_state_card(title, detail)

    def key_value_row(self, label, value, action=None):
        row = QFrame()
        row.setObjectName("WorkspaceInfoRow")
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(10)
        row.setLayout(row_layout)

        label_widget = QLabel(label)
        label_widget.setObjectName("MutedText")
        value_widget = QLabel(format_value(value))
        value_widget.setObjectName("ReadOnlyValue")
        value_widget.setWordWrap(True)

        row_layout.addWidget(label_widget)
        row_layout.addStretch()
        row_layout.addWidget(value_widget)
        if action is not None:
            row_layout.addWidget(action)
        return row

    def metric_card(self, label, value, detail=None):
        metric = QFrame()
        metric.setObjectName("WorkspaceMetricCard")
        metric_layout = QVBoxLayout()
        metric_layout.setContentsMargins(12, 10, 12, 10)
        metric_layout.setSpacing(3)
        metric.setLayout(metric_layout)

        value_widget = QLabel(str(value))
        value_widget.setObjectName("PanelTitle")
        label_widget = QLabel(label)
        label_widget.setObjectName("MutedText")
        label_widget.setWordWrap(True)
        metric_layout.addWidget(value_widget)
        metric_layout.addWidget(label_widget)
        if detail:
            detail_widget = QLabel(detail)
            detail_widget.setObjectName("MutedText")
            detail_widget.setWordWrap(True)
            metric_layout.addWidget(detail_widget)
        return metric

    def current_workflow(self):
        current_stage = getattr(self.dialog.context.missionary, "current_stage", None)
        for workflow in self.dialog.context.workflows:
            if getattr(workflow, "stage_name", None) == current_stage:
                return workflow
        return self.dialog.context.workflows[0] if self.dialog.context.workflows else None

    def personal_info(self, block):
        card, layout = self.card(block)
        grid = None
        if self.is_variant(block, "detail"):
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(8)
            layout.addLayout(grid)
        fields = block.get("fields") or [
            "full_name",
            "nationality",
            "passport_number",
            "carnet_number",
        ]
        fields, hidden_count = self.limited_items(block, fields)
        for index, field_key in enumerate(fields):
            value = getattr(self.dialog.context.missionary, field_key, None)
            label = field_label(field_key)
            if field_key == "current_stage":
                value = stage_display_name(value)
            if self.is_variant(block, "summary"):
                layout.addWidget(self.key_value_row(label, value))
                continue
            item = QWidget()
            item_layout = QVBoxLayout()
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(3)
            item.setLayout(item_layout)
            label_widget = QLabel(label)
            label_widget.setObjectName("MutedText")
            value_widget = QLabel(format_value(value))
            value_widget.setObjectName("ReadOnlyValue")
            value_widget.setWordWrap(True)
            item_layout.addWidget(label_widget)
            item_layout.addWidget(value_widget)
            if grid is not None:
                grid.addWidget(item, index // 2, index % 2)
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def documents(self, block):
        card, layout = self.card(block)
        documents = sorted(
            self.dialog.context.documents,
            key=lambda doc: getattr(doc, "uploaded_at", None) or 0,
            reverse=True,
        )
        if not documents:
            layout.addWidget(
                self.empty(
                    tr("missionary_detail_no_documents"),
                    tr("missionary_detail_no_documents_hint"),
                )
            )
            layout.addStretch()
            return card
        documents, hidden_count = self.limited_items(block, documents)
        if self.is_variant(block, "summary"):
            self.metric_grid(
                layout,
                [
                    ("Documents", len(self.dialog.context.documents)),
                    ("Missing groups", len(self.dialog.context.missing_groups)),
                ],
            )
            for doc in documents:
                layout.addWidget(
                    self.key_value_row(
                        "Recent",
                        document_label(getattr(doc, "document_type", "")),
                    )
                )
        else:
            for doc in documents:
                layout.addWidget(self.document_row(doc))
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def document_row(self, doc):
        return build_document_card(
            doc,
            on_view=self.dialog.open_document_viewer,
            on_notes=self.dialog.open_document_notes,
            on_open=self.dialog.open_document_file,
            show_thumbnail=False,
        )

    def document_viewer(self, block):
        card, layout = self.card(block)
        doc = self.dialog.find_document(block.get("document_type"))
        if doc is None:
            layout.addWidget(
                self.empty(
                    tr("workspace_no_document_preview"),
                    tr("workspace_no_document_preview_hint"),
                ),
                stretch=1,
            )
            return card
        preview = DocumentPreviewWidget(
            getattr(doc, "file_path", "") or "",
            parent=card,
            show_header=False,
        )
        layout.addWidget(preview, stretch=1)
        return card

    def web_viewer(self, block):
        card, layout = self.card(block)
        url = self.dialog.normalized_web_url(block.get("web_url", ""))
        if not url:
            layout.addWidget(
                self.empty(
                    tr("workspace_no_web_url"),
                    tr("workspace_no_web_url_hint"),
                ),
                stretch=1,
            )
            return card

        if getattr(self.dialog, "preview_mode", False):
            layout.addWidget(
                self.empty(
                    tr("workspace_web_preview"),
                    url,
                ),
                stretch=1,
            )
            return card

        if QWebEngineView is None:
            layout.addWidget(
                self.empty(
                    tr("workspace_web_viewer_unavailable"),
                    tr("workspace_web_viewer_unavailable_hint"),
                ),
                stretch=1,
            )
            open_btn = create_button(tr("workspace_open_website"), "primary")
            open_btn.clicked.connect(lambda checked=False: self.dialog.open_web_url(url))
            layout.addWidget(open_btn)
            return card

        web_view = QWebEngineView(card)
        web_view.setObjectName("WorkspaceWebViewer")
        web_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        web_view.setMinimumHeight(
            520 if getattr(self.dialog, "is_full_screen_workspace", False) else 320
        )
        status_label = QLabel(tr("workspace_web_loading"))
        status_label.setObjectName("WorkspaceWebStatus")
        status_label.setWordWrap(True)
        status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if hasattr(web_view, "loadStarted"):
            web_view.loadStarted.connect(
                lambda: status_label.setText(tr("workspace_web_loading"))
            )
        if hasattr(web_view, "loadFinished"):
            web_view.loadFinished.connect(
                lambda ok: status_label.setText(
                    "" if ok else tr("workspace_web_load_failed")
                )
            )
        QTimer.singleShot(0, lambda: web_view.setUrl(QUrl.fromUserInput(url)))
        layout.addWidget(web_view, stretch=1)
        layout.addWidget(status_label)

        open_btn = create_button(tr("workspace_open_website"), "secondary", fixed_height=28)
        open_btn.clicked.connect(lambda checked=False: self.dialog.open_web_url(url))
        layout.addWidget(open_btn, alignment=Qt.AlignRight)
        return card

    def missing_documents(self, block):
        card, layout = self.card(block)
        if not self.dialog.context.missing_groups:
            layout.addWidget(
                self.empty(
                    tr("missionary_detail_all_required_uploaded"),
                    tr("missionary_detail_all_required_uploaded_hint"),
                )
            )
            layout.addStretch()
            return card
        missing_groups, hidden_count = self.limited_items(
            block,
            self.dialog.context.missing_groups,
        )
        if self.is_variant(block, "summary"):
            total_missing = sum(
                len(missing_docs)
                for _, missing_docs, _ in self.dialog.context.missing_groups
            )
            self.metric_grid(
                layout,
                [
                    ("Missing", total_missing),
                    ("Groups", len(self.dialog.context.missing_groups)),
                ],
            )
            for stage_name, missing_docs, _ in missing_groups:
                layout.addWidget(
                    self.key_value_row(
                        stage_display_name(stage_name),
                        f"{len(missing_docs)} document(s)",
                    )
                )
        else:
            for stage_name, missing_docs, is_current in missing_groups:
                layout.addWidget(self.missing_row(stage_name, missing_docs, is_current))
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def missing_row(self, stage_name, missing_docs, is_current):
        return build_missing_stage_card(
            stage_name,
            missing_docs,
            is_current=is_current,
        )

    def workflow(self, block):
        card, layout = self.card(block)
        current = getattr(self.dialog.context.missionary, "current_stage", None)
        workflows, hidden_count = self.limited_items(block, self.dialog.context.workflows)
        if self.is_variant(block, "summary"):
            layout.addWidget(
                self.key_value_row(
                    "Current stage",
                    stage_display_name(current),
                )
            )
            active_workflow = self.current_workflow()
            if active_workflow:
                layout.addWidget(
                    self.key_value_row(
                        "Status",
                        status_label(getattr(active_workflow, "status", "")),
                    )
                )
            for workflow in workflows:
                if getattr(workflow, "stage_name", None) == current:
                    continue
                layout.addWidget(
                    self.key_value_row(
                        stage_display_name(getattr(workflow, "stage_name", "")),
                        status_label(getattr(workflow, "status", "")),
                    )
                )
        else:
            for workflow in workflows:
                layout.addWidget(self.workflow_row(workflow, workflow.stage_name == current))
        if not self.dialog.context.workflows:
            layout.addWidget(QLabel(tr("missionary_detail_no_workflow_stages")))
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def workflow_row(self, workflow, is_current):
        return build_workflow_stage_card(
            workflow,
            hint=status_label(workflow.status),
            is_current=is_current,
            on_update=self.dialog.change_workflow_status,
        )

    def open_tasks(self, block):
        card, layout = self.card(block)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addStretch()
        add_btn = create_button(tr("missionary_detail_add_task"), "primary", fixed_height=28)
        add_btn.clicked.connect(self.dialog.add_task)
        header.addWidget(add_btn)
        layout.addLayout(header)
        if not self.dialog.context.tasks:
            layout.addWidget(
                self.empty(
                    tr("missionary_detail_no_open_tasks"),
                    tr("missionary_detail_no_open_tasks_hint"),
                )
            )
            layout.addStretch()
            return card
        tasks, hidden_count = self.limited_items(block, self.dialog.context.tasks)
        if self.is_variant(block, "summary"):
            priority_count = sum(
                1
                for task in self.dialog.context.tasks
                if (
                    task.get("priority") if isinstance(task, dict)
                    else getattr(task, "priority", "")
                )
                in {"High", "HIGH", "Urgent", "URGENT"}
            )
            self.metric_grid(
                layout,
                [
                    ("Open tasks", len(self.dialog.context.tasks)),
                    ("High priority", priority_count),
                ],
            )
            for task in tasks:
                title = task.get("title") if isinstance(task, dict) else getattr(task, "title", "Task")
                layout.addWidget(self.key_value_row("Next", title))
        else:
            for task in tasks:
                layout.addWidget(self.task_row(task))
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def task_row(self, task):
        return build_task_card(
            task,
            on_done=self.dialog.complete_task,
            on_edit=self.dialog.edit_task,
        )

    def notes(self, block):
        card, layout = self.card(block)
        notes = getattr(self.dialog.context.missionary, "notes", None) or tr("workspace_no_notes")
        if self.is_variant(block, "summary") and len(str(notes)) > 180:
            notes = f"{str(notes)[:177].rstrip()}..."
        label = QLabel(notes)
        label.setObjectName("RowText")
        label.setWordWrap(True)
        layout.addWidget(label, stretch=1)
        return card

    def residency_timeline(self, block):
        card, layout = self.card(block)
        if not self.dialog.context.residency_rows:
            layout.addWidget(QLabel(tr("missionary_detail_residency_timeline_hint")))
            layout.addStretch()
            return card
        rows, hidden_count = self.limited_items(block, self.dialog.context.residency_rows)
        if self.is_variant(block, "summary"):
            self.metric_grid(
                layout,
                [
                    ("Events", len(self.dialog.context.residency_rows)),
                    ("Next", format_value(rows[0].get("target_expiration")) if rows else "-"),
                ],
            )
            for row in rows:
                layout.addWidget(
                    self.key_value_row(
                        row.get("event_type", ""),
                        row.get("target_expiration"),
                    )
                )
        else:
            for row in rows:
                line = QHBoxLayout()
                label = QLabel(row.get("event_type", ""))
                target = QLabel(format_value(row.get("target_expiration")))
                target.setObjectName("MutedText")
                line.addWidget(label)
                line.addStretch()
                line.addWidget(target)
                layout.addLayout(line)
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card



    def quick_actions(self, block):
        card, layout = self.card(block)
        actions = (
            (block.get("settings") or {}).get("actions")
            or ["upload_document", "add_task", "open_folder", "update_workflow"]
        )
        labels = {
            "upload_document": "Upload Document",
            "add_task": "Add Task",
            "open_folder": "Open Folder",
            "update_workflow": "Update Workflow",
        }
        handlers = {
            "upload_document": self.dialog.upload_document,
            "add_task": self.dialog.add_task,
            "open_folder": self.dialog.open_folder_path,
            "update_workflow": self.dialog.update_current_workflow,
        }
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        actions, hidden_count = self.limited_items(block, actions)
        if self.is_variant(block, "summary"):
            self.metric_grid(layout, [("Actions", len(actions))])
            for action in actions:
                layout.addWidget(
                    self.key_value_row(
                        "Action",
                        labels.get(action, str(action).replace("_", " ").title()),
                    )
                )
            self.add_overflow_hint(layout, hidden_count)
            layout.addStretch()
            return card
        for index, action in enumerate(actions):
            btn = create_button(
                labels.get(action, str(action).replace("_", " ").title()),
                "secondary",
                fixed_height=30,
            )
            handler = handlers.get(action)
            btn.setEnabled(
                handler is not None
                and not getattr(self.dialog, "preview_mode", False)
            )
            if handler is not None:
                btn.clicked.connect(handler)
            grid.addWidget(btn, index // 2, index % 2)
        layout.addLayout(grid)
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def appointments(self, block):
        card, layout = self.card(block)
        fields = ["interpol_appointment_date", "biometric_appointment_date", "pickup_appointment_date", "visa_expiration", "passport_expiration", "residency_expiration", "prorroga_expiration"]
        added = 0
        fields, hidden_count = self.limited_items(block, fields)
        dated_fields = [
            (field, getattr(self.dialog.context.missionary, field, None))
            for field in fields
            if getattr(self.dialog.context.missionary, field, None)
        ]
        if self.is_variant(block, "summary") and dated_fields:
            next_field, next_value = dated_fields[0]
            self.metric_grid(layout, [("Upcoming", len(dated_fields))])
            layout.addWidget(self.key_value_row(field_label(next_field), next_value))
            remaining = dated_fields[1:]
            for field, value in remaining[: max(0, self.presentation(block)["content_limit"] - 1)]:
                layout.addWidget(self.key_value_row(field_label(field), value))
            hidden_count += max(0, len(remaining) - max(0, self.presentation(block)["content_limit"] - 1))
            self.add_overflow_hint(layout, hidden_count)
            layout.addStretch()
            return card
        for field in fields:
            value = getattr(self.dialog.context.missionary, field, None)
            if value:
                layout.addWidget(self.key_value_row(field_label(field), value))
                added += 1
        if not added:
            layout.addWidget(self.empty("No upcoming appointments", "Appointment and expiration dates will appear here."))
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def status_summary(self, block):
        card, layout = self.card(block)
        current = stage_display_name(
            getattr(self.dialog.context.missionary, "current_stage", None)
        )
        metric_data = [
            ("Stage", current),
            ("Documents", len(self.dialog.context.documents)),
            ("Missing groups", len(self.dialog.context.missing_groups)),
            ("Open tasks", len(self.dialog.context.tasks)),
        ]
        metric_data, hidden_count = self.limited_items(block, metric_data)
        self.metric_grid(layout, metric_data)
        workflow = self.current_workflow()
        if workflow:
            layout.addWidget(
                self.key_value_row(
                    "Workflow status",
                    status_label(getattr(workflow, "status", "")),
                )
            )
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def document_checklist(self, block):
        return self.missing_documents(block)

    def task_board(self, block):
        return self.open_tasks(block)

    def contact_info(self, block):
        card, layout = self.card(block)
        fields, hidden_count = self.limited_items(
            block,
            ["phone", "email", "emergency_contact", "folder_path"],
        )
        for field in fields:
            value = getattr(self.dialog.context.missionary, field, None)
            line = QHBoxLayout(); line.addWidget(QLabel(field_label(field))); line.addStretch(); line.addWidget(QLabel(format_value(value))); layout.addLayout(line)
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch(); return card

    def contact_info_polished(self, block):
        card, layout = self.card(block)
        added = 0
        fields, hidden_count = self.limited_items(
            block,
            ["phone", "email", "emergency_contact", "folder_path"],
        )
        if self.is_variant(block, "summary"):
            available = [
                field
                for field in fields
                if getattr(self.dialog.context.missionary, field, None)
            ]
            self.metric_grid(layout, [("Contact fields", len(available))])
        for field in fields:
            value = getattr(self.dialog.context.missionary, field, None)
            if not value:
                continue
            action = None
            if field == "folder_path":
                action = create_button("Open", "secondary", fixed_height=26)
                action.setEnabled(not getattr(self.dialog, "preview_mode", False))
                action.clicked.connect(self.dialog.open_folder_path)
            layout.addWidget(
                self.key_value_row(field_label(field), value, action=action)
            )
            added += 1
        if not added:
            layout.addWidget(
                self.empty(
                    "No contact details",
                    "Phone, email, emergency contact, and folder details will appear here.",
                )
            )
        layout.addStretch()
        self.add_overflow_hint(layout, hidden_count)
        return card

    def workflow_next_steps(self, block):
        return self.workflow_next_steps_polished(block)

    def recent_activity(self, block):
        return self.recent_activity_polished(block)

    def link_list(self, block):
        return self.link_list_polished(block)

    def workflow_next_steps_polished(self, block):
        card, layout = self.card(block)
        current = stage_display_name(
            getattr(self.dialog.context.missionary, "current_stage", None)
        )
        if self.is_variant(block, "summary"):
            self.metric_grid(layout, [("Current", current)])
        else:
            layout.addWidget(self.key_value_row("Current workflow", current))

        next_steps = []
        if self.dialog.context.missing_groups:
            stage_name, missing_docs, _ = self.dialog.context.missing_groups[0]
            next_steps.append(
                f"Review {len(missing_docs)} missing document(s) for {stage_display_name(stage_name)}"
            )
        if self.dialog.context.tasks:
            next_steps.append(f"Complete {len(self.dialog.context.tasks)} open task(s)")
        workflow = self.current_workflow()
        if workflow and getattr(workflow, "status", "") != "COMPLETED":
            next_steps.append(
                f"Update {stage_display_name(getattr(workflow, 'stage_name', ''))} status"
            )
        if not next_steps:
            next_steps.append("No urgent next steps for this workspace.")

        next_steps, hidden_count = self.limited_items(block, next_steps)
        for text in next_steps:
            layout.addWidget(self.key_value_row("Next", text))
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def recent_activity_polished(self, block):
        card, layout = self.card(block)
        added = 0
        documents = sorted(
            self.dialog.context.documents,
            key=lambda doc: getattr(doc, "uploaded_at", None) or 0,
            reverse=True,
        )
        documents, hidden_docs = self.limited_items(block, documents)
        if self.is_variant(block, "summary"):
            self.metric_grid(
                layout,
                [
                    ("Documents", len(self.dialog.context.documents)),
                    ("Tasks", len(self.dialog.context.tasks)),
                ],
            )
        for doc in documents:
            layout.addWidget(
                self.key_value_row(
                    "Document",
                    document_label(getattr(doc, "document_type", "")),
                )
            )
            added += 1
        remaining_slots = max(0, self.presentation(block)["content_limit"] - added)
        tasks = list(self.dialog.context.tasks or [])
        visible_tasks = tasks[:remaining_slots]
        hidden_tasks = max(0, len(tasks) - len(visible_tasks))
        for task in visible_tasks:
            title = task.get("title") if isinstance(task, dict) else getattr(task, "title", "Task")
            layout.addWidget(self.key_value_row("Task", title))
            added += 1
        if not added:
            layout.addWidget(
                self.empty(
                    "No recent activity",
                    "Document, task, and workflow changes will appear here.",
                )
            )
        self.add_overflow_hint(layout, hidden_docs + hidden_tasks)
        layout.addStretch()
        return card

    def link_list_polished(self, block):
        card, layout = self.card(block)
        links = (block.get("settings") or {}).get("links") or []
        if not links:
            layout.addWidget(
                self.empty(
                    "No links configured",
                    "Add government portals or reference links in the inspector.",
                )
            )
        links, hidden_count = self.limited_items(block, links)
        if self.is_variant(block, "summary"):
            self.metric_grid(layout, [("Links", len(links))])
        for link in links:
            if isinstance(link, str):
                label = link
                url = link
            else:
                label = link.get("label") or link.get("url") or "Link"
                url = link.get("url") or ""
            open_btn = create_button("Open", "secondary", fixed_height=26)
            open_btn.setEnabled(
                bool(url) and not getattr(self.dialog, "preview_mode", False)
            )
            open_btn.clicked.connect(
                lambda checked=False, target=url: self.dialog.open_web_url(target)
            )
            layout.addWidget(self.key_value_row("Link", label, action=open_btn))
        self.add_overflow_hint(layout, hidden_count)
        layout.addStretch()
        return card

    def unsupported(self, block):
        card, layout = self.card(block)
        layout.addWidget(QLabel(tr("workspace_unsupported_block")))
        layout.addStretch()
        return card


class MissionaryWorkspaceDialog(MaskDialogBase):
    def __init__(
        self,
        missionary,
        workspace,
        parent=None,
        on_refresh=None,
        context=None,
    ):
        super().__init__(parent)
        self.missionary = missionary
        self.workspace = normalize_workspace_layout(workspace or {})
        self.on_refresh = on_refresh
        self.document_service = DocumentService()
        self.workflow_service = WorkflowService()
        self.secretary_work_service = SecretaryWorkService()
        self.workflow_validator = WorkflowValidator()
        self.context = context or MissionaryWorkspaceContext.load(missionary)

        self.setWindowTitle(self.workspace.get("name") or tr("workspace_title"))
        width, height = {
            "medium": (820, 620),
            "large": (1040, 720),
            "wide": (1220, 760),
        }.get(self.workspace.get("dialog_size"), (1040, 720))
        self.surface = setup_dialog_shell(
            self,
            surface_width=width,
            surface_min_height=height,
            use_masked_shell=True,
            fit_to_content=False,
        )
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.surface.setLayout(root)

        header = QFrame()
        header.setObjectName("MissionaryWorkspaceDialogHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(12)
        header.setLayout(header_layout)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(4)
        title = SubtitleLabel(self.workspace.get("name") or tr("workspace_title"))
        title.setObjectName("MissionaryWorkspaceDialogTitle")
        subtitle = QLabel(getattr(self.missionary, "full_name", ""))
        subtitle.setObjectName("MissionaryWorkspaceDialogSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        header_layout.addLayout(title_stack, stretch=1)
        close_btn = create_button(tr("common_close"), "secondary")
        close_btn.clicked.connect(self.accept)
        header_layout.addWidget(close_btn)
        root.addWidget(header)

        scroll = create_scroll_area(
            "WorkspaceScrollArea",
            transparent=True,
            single_direction=True,
        )
        scroll.setWidgetResizable(False)
        tune_fluent_scrollable(scroll)
        self.content = QWidget()
        self.content.setObjectName("MissionaryWorkspaceDialogBody")
        self.content.setAttribute(Qt.WA_StyledBackground, True)
        self._workspace_block_widgets = []
        scroll.setWidget(self.content)
        root.addWidget(scroll, stretch=1)
        self._render_blocks()

    def _render_blocks(self):
        for widget in getattr(self, "_workspace_block_widgets", []):
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._workspace_block_widgets = []

        factory = WorkspaceBlockFactory(self)
        body_width, body_height = self._workspace_body_size()
        max_bottom = body_height
        for block in self.workspace.get("blocks", []):
            if block.get("visible") is False:
                continue
            widget = factory.build(block)
            widget.setParent(self.content)
            rect = self._workspace_block_rect(block)
            widget.setGeometry(rect)
            widget.setMinimumSize(rect.size())
            widget.show()
            self._workspace_block_widgets.append(widget)
            max_bottom = max(max_bottom, rect.bottom() + 18)
        self.content.setMinimumSize(QSize(body_width, max_bottom))
        self.content.resize(body_width, max_bottom)

    def _workspace_body_size(self):
        return WORKSPACE_DIALOG_BODY_SIZES.get(
            self.workspace.get("dialog_size"),
            WORKSPACE_DIALOG_BODY_SIZES["large"],
        )

    def _workspace_block_rect(self, block):
        body_width, _ = self._workspace_body_size()
        free_layout = block.get("free_layout") if isinstance(block, dict) else None
        if isinstance(free_layout, dict):
            try:
                return QRect(
                    int(round(float(free_layout.get("x", 0)))),
                    int(round(float(free_layout.get("y", 0)))),
                    max(96, int(round(float(free_layout.get("width", 96))))),
                    max(64, int(round(float(free_layout.get("height", 64))))),
                )
            except (TypeError, ValueError):
                pass
        layout = validate_block_layout(block)
        cell_width = body_width / WORKSPACE_GRID_COLUMNS
        return QRect(
            int(round(layout["col"] * cell_width)) + 5,
            int(round(layout["row"] * WORKSPACE_RUNTIME_ROW_HEIGHT)) + 5,
            max(96, int(round(layout["col_span"] * cell_width)) - 10),
            max(64, int(round(layout["row_span"] * WORKSPACE_RUNTIME_ROW_HEIGHT)) - 10),
        )

    def refresh_context(self):
        self.context = MissionaryWorkspaceContext.load(self.missionary)
        self._render_blocks()
        if callable(self.on_refresh):
            self.on_refresh()

    def document_data(self, doc):
        return {
            "id": doc.id,
            "document_type": doc.document_type,
            "label": document_label(doc.document_type),
            "file_path": doc.file_path,
            "file_name": doc.file_name,
            "notes": doc.notes or "",
            "ocr_raw_data": getattr(doc, "ocr_raw_data", None),
            "ocr_confirmed_data": getattr(doc, "ocr_confirmed_data", None),
        }

    def find_document(self, document_type=None):
        documents = self.context.documents
        if document_type:
            documents = [doc for doc in documents if doc.document_type == document_type]
        if not documents:
            return None
        return sorted(
            documents,
            key=lambda doc: getattr(doc, "uploaded_at", None) or 0,
            reverse=True,
        )[0]

    @staticmethod
    def normalized_web_url(value):
        url = (value or "").strip()
        if not url or url == "https://":
            return ""
        if "://" not in url:
            url = f"https://{url}"
        return url

    def open_web_url(self, url):
        normalized = self.normalized_web_url(url)
        if normalized:
            QDesktopServices.openUrl(QUrl(normalized))

    def upload_document(self):
        try:
            from ui.dialogs.upload_session_dialog import UploadSessionDialog

            dialog = UploadSessionDialog(self.missionary, parent=self)
            dialog.exec()
            saved_any = getattr(dialog, "saved_any", None)
            if callable(saved_any) and saved_any():
                self.refresh_context()
        except Exception:
            logger.exception("Failed to upload document from workspace")
            show_message(
                self,
                tr("missionary_detail_upload_document"),
                tr("workspace_action_failed"),
                kind="warning",
            )

    def open_folder_path(self):
        folder_path = getattr(self.missionary, "folder_path", None)
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
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def update_current_workflow(self):
        current_stage = getattr(self.missionary, "current_stage", None)
        workflow = None
        for candidate in self.context.workflows:
            if getattr(candidate, "stage_name", None) == current_stage:
                workflow = candidate
                break
        if workflow is None and self.context.workflows:
            workflow = self.context.workflows[0]
        if workflow is None:
            show_message(
                self,
                tr("workspace_block_workflow"),
                tr("missionary_detail_no_workflow_stages"),
                kind="info",
            )
            return
        self.change_workflow_status(workflow)

    def open_document_viewer(self, doc):
        file_path = getattr(doc, "file_path", None)
        if not file_path or not Path(file_path).exists():
            show_message(
                self,
                tr("missionary_detail_file_not_found_title"),
                tr("missionary_detail_cannot_open_document"),
                kind="warning",
            )
            return
        DocumentViewerDialog(file_path, parent=self).exec()

    def open_document_notes(self, doc):
        from ui.pages.missionary_detail_page import DocumentNotesDialog

        dialog = DocumentNotesDialog(
            self.document_data(doc),
            self.document_service,
            parent=self,
        )
        if dialog.exec():
            self.refresh_context()

    def open_document_file(self, doc):
        from ui.pages.missionary_detail_page import open_document_with_default_app

        file_path = getattr(doc, "file_path", None)
        if not file_path or not Path(file_path).exists():
            show_message(
                self,
                tr("missionary_detail_file_not_found_title"),
                tr("missionary_detail_cannot_open_file", file_path=file_path or ""),
                kind="warning",
            )
            return
        open_document_with_default_app(file_path)

    def change_workflow_status(self, workflow):
        from ui.pages.missionary_detail_page import WorkflowStatusDialog

        dialog = WorkflowStatusDialog(parent=self)
        if dialog.exec():
            self.workflow_service.update_workflow_status(
                workflow.id,
                dialog.selected_status(),
            )
            self.refresh_context()

    def add_task(self):
        dialog = TaskDialog(
            self.secretary_work_service,
            defaults={"missionary_id": self.missionary.id},
            parent=self,
        )
        if dialog.exec():
            self.refresh_context()

    def edit_task(self, task):
        dialog = TaskDialog(
            self.secretary_work_service,
            task=task,
            parent=self,
        )
        if dialog.exec():
            self.refresh_context()

    def complete_task(self, task):
        try:
            self.secretary_work_service.complete_task(task["id"])
            self.refresh_context()
        except Exception:
            logger.exception("Failed to complete workspace task")
