"""Section renderers used by the Missionary Detail compatibility page."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from utils.constants import (
    DOCUMENTS,
    WORKFLOW_STAGES,
    required_documents_for_missionary,
)
from utils.language_helper import ui_text as tr
from utils.logger import logger


def _document_label(document_type):
    return DOCUMENTS.get(document_type, {}).get("label", document_type or "Document")


class WorkflowSection:
    def __init__(self, host):
        self.host = host

    def render(self, workflows=None):
        host = self.host
        host.workflow_list.clear()
        if not hasattr(host, "current_missionary"):
            host._workflow_records = []
            return
        if workflows is None:
            workflows = host.workflow_service.get_workflows(
                host.current_missionary.id
            )
        workflows = list(workflows)
        host._workflow_records = workflows

        if (
            getattr(host.current_missionary, "tracking_profile", "LEGAL")
            == "PERUVIAN_DNI"
        ):
            item = QListWidgetItem()
            widget = host._build_empty_state_card(
                "Peruvian DNI tracking",
                "This missionary only requires an active copy of the DNI.",
                tone="muted",
            )
            item.setSizeHint(widget.sizeHint())
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            host.workflow_list.addItem(item)
            host.workflow_list.setItemWidget(item, widget)
            return

        workflow_map = {workflow.stage_name: workflow for workflow in workflows}
        current_stage = getattr(host.current_missionary, "current_stage", None)
        for stage_name in WORKFLOW_STAGES:
            workflow = workflow_map.get(stage_name)
            if workflow is None:
                continue
            item = QListWidgetItem()
            widget = host._build_workflow_stage_widget(
                workflow,
                is_current=(stage_name == current_stage),
            )
            item.setData(Qt.UserRole, workflow.id)
            item.setSizeHint(widget.sizeHint())
            host.workflow_list.addItem(item)
            host.workflow_list.setItemWidget(item, widget)

        if host.workflow_list.count() == 0:
            empty = QListWidgetItem(tr("missionary_detail_no_workflow_stages"))
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            host.workflow_list.addItem(empty)


class DocumentsSection:
    def __init__(self, host):
        self.host = host

    def render(self, documents=None):
        host = self.host
        host.documents_list.clear()
        host._document_data = []
        host._document_records = {}
        host._document_widgets = {}
        if not hasattr(host, "current_missionary"):
            return
        if documents is None:
            documents = host.document_service.get_documents(
                host.current_missionary.id
            )

        def sort_key(document):
            uploaded_at = getattr(document, "uploaded_at", None)
            if uploaded_at:
                try:
                    uploaded_value = uploaded_at.timestamp()
                except Exception:
                    uploaded_value = 0
            else:
                uploaded_value = -1
            return (
                uploaded_value,
                (document.document_type or "").lower(),
                (document.file_name or "").lower(),
            )

        documents = sorted(documents, key=sort_key, reverse=True)
        host._update_header_photo(documents)
        if not documents:
            empty = QListWidgetItem()
            widget = host._build_empty_state_card(
                tr("missionary_detail_no_documents"),
                tr("missionary_detail_no_documents_hint"),
            )
            empty.setSizeHint(widget.sizeHint())
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            host.documents_list.addItem(empty)
            host.documents_list.setItemWidget(empty, widget)
            return

        for document in documents:
            label = _document_label(document.document_type)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, document.id)
            widget = host._build_document_item_widget(document, label)
            item.setSizeHint(widget.sizeHint())
            host.documents_list.addItem(item)
            host.documents_list.setItemWidget(item, widget)
            host._document_records[document.id] = document
            host._document_widgets[document.id] = widget
            host._document_data.append(
                {
                    "id": document.id,
                    "document_type": document.document_type,
                    "label": label,
                    "file_path": None,
                    "file_name": document.file_name,
                    "notes": document.notes or "",
                    "ocr_raw_data": document.ocr_raw_data,
                    "ocr_confirmed_data": document.ocr_confirmed_data,
                }
            )


class OpenTasksSection:
    def __init__(self, host):
        self.host = host

    def render(self, tasks=None):
        host = self.host
        if not hasattr(host, "open_tasks_list"):
            return
        host.open_tasks_list.clear()
        host._detail_task_widgets = {}
        if not hasattr(host, "current_missionary"):
            return
        if tasks is None:
            tasks = host.secretary_work_service.list_tasks(
                missionary_id=host.current_missionary.id,
            )
        if not tasks:
            empty = QListWidgetItem()
            widget = host._build_empty_state_card(
                tr("missionary_detail_no_open_tasks"),
                tr("missionary_detail_no_open_tasks_hint"),
            )
            empty.setSizeHint(widget.sizeHint())
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            host.open_tasks_list.addItem(empty)
            host.open_tasks_list.setItemWidget(empty, widget)
            return
        for task in tasks:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, task["id"])
            widget = host._build_open_task_widget(task)
            task_id = task["id"]
            widget.setEnabled(task_id not in host._pending_task_actions)
            host._detail_task_widgets[task_id] = widget
            item.setSizeHint(widget.sizeHint())
            host.open_tasks_list.addItem(item)
            host.open_tasks_list.setItemWidget(item, widget)


class MissingDocumentsSection:
    def __init__(self, host):
        self.host = host

    def render(self, documents=None):
        host = self.host
        host.missing_documents_list.clear()
        if not hasattr(host, "current_missionary"):
            return
        if documents is None:
            documents = host.document_service.get_documents(
                host.current_missionary.id
            )
        uploaded_types = {
            document.document_type
            for document in documents
            if getattr(document, "status", "ACTIVE") == "ACTIVE"
        }
        current_stage = getattr(host.current_missionary, "current_stage", None)
        missing_groups = []
        if (
            getattr(host.current_missionary, "tracking_profile", "LEGAL")
            == "PERUVIAN_DNI"
        ):
            if "DNI" not in uploaded_types:
                missing_groups.append(("DNI", ["DNI"], True))
            else:
                empty = QListWidgetItem()
                widget = host._build_empty_state_card(
                    "DNI copy uploaded",
                    "No other legal documents are required.",
                    tone="success",
                )
                empty.setSizeHint(widget.sizeHint())
                empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
                host.missing_documents_list.addItem(empty)
                host.missing_documents_list.setItemWidget(empty, widget)
                return

        general_missing = [] if missing_groups else [
            key
            for key, config in DOCUMENTS.items()
            if config.get("required")
            and config.get("stage") is None
            and key not in uploaded_types
            and key != "OTHER"
        ]
        if general_missing:
            missing_groups.append(("Always required", general_missing, True))

        stage_order = []
        if current_stage in WORKFLOW_STAGES:
            stage_order.append(current_stage)
        stage_order.extend(
            stage for stage in WORKFLOW_STAGES if stage != current_stage
        )
        for stage_name in stage_order:
            missing = [
                key
                for key in required_documents_for_missionary(
                    stage_name,
                    host.current_missionary,
                )
                if key not in uploaded_types
            ]
            if missing:
                missing_groups.append(
                    (stage_name, missing, stage_name == current_stage)
                )

        if not missing_groups:
            empty = QListWidgetItem()
            widget = host._build_empty_state_card(
                tr("missionary_detail_all_required_uploaded"),
                tr("missionary_detail_all_required_uploaded_hint"),
                tone="success",
            )
            empty.setSizeHint(widget.sizeHint())
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            host.missing_documents_list.addItem(empty)
            host.missing_documents_list.setItemWidget(empty, widget)
            return

        for stage_name, missing_docs, is_current in missing_groups:
            item = QListWidgetItem()
            widget = host._build_missing_stage_widget(
                stage_name,
                missing_docs,
                is_current=is_current,
            )
            item.setSizeHint(widget.sizeHint())
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            host.missing_documents_list.addItem(item)
            host.missing_documents_list.setItemWidget(item, widget)


class TimelineSection:
    def __init__(self, host):
        self.host = host

    def render(self):
        host = self.host
        host.timeline_list.clear()
        category = getattr(host, "_timeline_filter", "all")
        feed = getattr(host, "_timeline_feed", {}) or {}
        upcoming = [
            event
            for event in feed.get("upcoming", [])
            if category in {"all", event.get("category")}
        ]
        events = [
            event
            for event in feed.get("events", [])
            if category in {"all", event.get("category")}
        ]
        if upcoming:
            host._add_timeline_heading(
                tr("missionary_detail_timeline_upcoming"),
                upcoming=True,
            )
            for event in upcoming:
                item = QListWidgetItem()
                widget = host._build_timeline_event_widget(event, upcoming=True)
                item.setSizeHint(widget.sizeHint())
                host.timeline_list.addItem(item)
                host.timeline_list.setItemWidget(item, widget)

        current_group = None
        for event in events:
            group = host._timeline_group_label(event.get("occurred_at"))
            if group != current_group:
                host._add_timeline_heading(group)
                current_group = group
            item = QListWidgetItem()
            widget = host._build_timeline_event_widget(event)
            item.setSizeHint(widget.sizeHint())
            host.timeline_list.addItem(item)
            host.timeline_list.setItemWidget(item, widget)

        if not upcoming and not events:
            empty = QListWidgetItem()
            widget = host._build_empty_state_card(
                tr("missionary_detail_timeline_empty"),
                tr("missionary_detail_timeline_empty_hint"),
            )
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            empty.setSizeHint(widget.sizeHint())
            host.timeline_list.addItem(empty)
            host.timeline_list.setItemWidget(empty, widget)

    def load(self, activity_feed=None):
        host = self.host
        if not hasattr(host, "current_missionary"):
            return
        try:
            if activity_feed is None:
                activity_feed = host.client_view_service.get_missionary_activity(
                    host.current_missionary.id
                )
            host._timeline_feed = activity_feed or {
                "events": [],
                "upcoming": [],
            }
            self.render()
        except Exception:
            logger.exception("Failed to load timeline")
