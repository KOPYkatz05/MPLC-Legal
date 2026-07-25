from pathlib import Path
import time

from PySide6.QtCore import QRect, QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.document_service import DocumentService
from services.client_view_service import ClientViewService
from services.secretary_work_service import SecretaryWorkService
from services.workflow_service import WorkflowService
from services.workflow_validator import WorkflowValidator
from services.workspace_layout import (
    WORKSPACE_GRID_COLUMNS,
    normalize_workspace_layout,
    validate_block_layout,
)
from ui.dialogs.document_viewer_dialog import DocumentViewerDialog
from ui.dialogs.missionary_workspace_dialog import (
    MissionaryWorkspaceContext,
    WORKSPACE_DIALOG_BODY_SIZES,
    WORKSPACE_RUNTIME_ROW_HEIGHT,
    WorkspaceBlockFactory,
    document_label,
)
from ui.dialogs.office_work_dialogs import TaskDialog
from ui.foundation import (
    SubtitleLabel,
    create_button,
    create_scroll_area,
    show_message,
    tune_fluent_scrollable,
)
from ui.foundation.background_loader import LatestRequestLoader
from utils.i18n import tr
from utils.logger import logger


class MissionaryWorkspacePage(QWidget):
    CONTEXT_CACHE_TTL_SECONDS = 30.0

    def __init__(self, main_window=None):
        super().__init__()
        self.setObjectName("MissionaryWorkspacePage")
        self.main_window = main_window
        self.is_full_screen_workspace = True
        self.missionary = None
        self.workspace = {}
        self.context = None
        self.document_service = DocumentService()
        self.workflow_service = WorkflowService()
        self.secretary_work_service = SecretaryWorkService()
        self.workflow_validator = WorkflowValidator()
        self._context_cache_key = None
        self._context_refreshed_at = 0.0
        self._context_loader = LatestRequestLoader(parent=self)
        self._context_loader.busy_changed.connect(
            lambda busy: self.refresh_btn.setEnabled(not busy)
            if hasattr(self, "refresh_btn")
            else None
        )
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setLayout(root)

        header = QFrame()
        header.setObjectName("MissionaryWorkspacePageHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(12)
        header.setLayout(header_layout)

        self.back_btn = create_button(tr("common_back"), "secondary")
        self.back_btn.clicked.connect(self.go_back)
        header_layout.addWidget(self.back_btn)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(4)
        self.title_label = SubtitleLabel(tr("workspace_title"))
        self.title_label.setObjectName("MissionaryWorkspacePageTitle")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("MissionaryWorkspacePageSubtitle")
        title_stack.addWidget(self.title_label)
        title_stack.addWidget(self.subtitle_label)
        header_layout.addLayout(title_stack, stretch=1)

        self.refresh_btn = create_button(tr("common_refresh"), "secondary")
        self.refresh_btn.clicked.connect(self.refresh_context)
        header_layout.addWidget(self.refresh_btn)
        root.addWidget(header)

        self.scroll = create_scroll_area(
            "MissionaryWorkspacePageScroll",
            transparent=True,
            single_direction=True,
        )
        self.scroll.setWidgetResizable(False)
        tune_fluent_scrollable(self.scroll)
        self.content = QWidget()
        self.content.setObjectName("MissionaryWorkspacePageBody")
        self.content.setAttribute(Qt.WA_StyledBackground, True)
        self._workspace_block_widgets = []
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, stretch=1)

    def load_workspace(self, missionary, workspace):
        """Synchronous compatibility path used by focused local callers."""
        self.missionary = missionary
        self.workspace = normalize_workspace_layout(workspace or {})
        self.context = MissionaryWorkspaceContext.load(missionary)
        self._context_cache_key = self._workspace_context_key(
            missionary,
            self.workspace,
        )
        self._context_refreshed_at = time.monotonic()
        self.title_label.setText(self.workspace.get("name") or tr("workspace_title"))
        self.subtitle_label.setText(getattr(missionary, "full_name", ""))
        self._render_blocks()

    def request_workspace(
        self,
        missionary,
        workspace,
        *,
        force=False,
        refresh_detail=False,
    ):
        normalized_workspace = normalize_workspace_layout(workspace or {})
        workspace_changed = normalized_workspace != self.workspace
        context_key = self._workspace_context_key(
            missionary,
            normalized_workspace,
        )
        now = time.monotonic()
        cache_is_fresh = (
            self.context is not None
            and context_key == self._context_cache_key
            and (
                now - self._context_refreshed_at
                < self.CONTEXT_CACHE_TTL_SECONDS
            )
        )

        self.missionary = missionary
        self.workspace = normalized_workspace
        self.title_label.setText(
            self.workspace.get("name") or tr("workspace_title")
        )
        self.subtitle_label.setText(
            getattr(missionary, "full_name", "")
        )

        if cache_is_fresh and not force:
            if workspace_changed:
                self._render_blocks()
            return False

        self.context = None
        self._render_context_loading()
        self._context_cache_key = context_key
        load_for = missionary
        load_context = type(self)._load_workspace_context
        self._context_loader.request(
            lambda: load_context(load_for),
            on_success=lambda context: self._apply_workspace_context(
                context,
                refresh_detail=refresh_detail,
            ),
            on_error=self._workspace_context_failed,
        )
        return True

    @staticmethod
    def _workspace_context_key(missionary, workspace):
        return (
            getattr(missionary, "id", None),
            (workspace or {}).get("id"),
        )

    @staticmethod
    def _load_workspace_context(missionary):
        snapshot = ClientViewService().get_missionary_detail_snapshot(
            missionary.id
        )
        if snapshot is None:
            raise LookupError(
                f"Missionary ID {missionary.id} is no longer available."
            )
        current_missionary = snapshot["missionary"]
        documents = list(snapshot.get("documents") or [])
        return MissionaryWorkspaceContext(
            missionary=current_missionary,
            documents=documents,
            workflows=list(snapshot.get("workflows") or []),
            tasks=list(snapshot.get("tasks") or []),
            residency_rows=list(
                snapshot.get("residency_timeline") or []
            ),
            missing_groups=MissionaryWorkspaceContext._missing_groups(
                current_missionary,
                documents,
            ),
        )

    def _apply_workspace_context(self, context, *, refresh_detail=False):
        self.context = context
        self.missionary = context.missionary
        self.subtitle_label.setText(
            getattr(self.missionary, "full_name", "")
        )
        self._context_refreshed_at = time.monotonic()
        self._render_blocks()
        if refresh_detail:
            self._refresh_detail_page()

    def _render_context_loading(self):
        self._clear_workspace_widgets()
        body_width, body_height = self._workspace_body_size()
        loading = QLabel("Loading workspace details…", self.content)
        loading.setObjectName("MutedText")
        loading.setGeometry(QRect(18, 16, body_width - 36, 40))
        loading.show()
        self._workspace_block_widgets.append(loading)
        self.content.setMinimumSize(QSize(body_width, body_height))
        self.content.resize(body_width, body_height)

    def _workspace_context_failed(self, error):
        logger.error(
            "Failed to load missionary workspace context",
            exc_info=(type(error), error, error.__traceback__),
        )
        self._clear_workspace_widgets()
        body_width, body_height = self._workspace_body_size()
        message = QLabel(tr("workspace_action_failed"), self.content)
        message.setObjectName("MutedText")
        message.setGeometry(QRect(18, 16, body_width - 36, 60))
        message.setWordWrap(True)
        message.show()
        self._workspace_block_widgets.append(message)
        self.content.setMinimumSize(QSize(body_width, body_height))
        self.content.resize(body_width, body_height)

    def retranslate_ui(self):
        self.back_btn.setText(tr("common_back"))
        self.refresh_btn.setText(tr("common_refresh"))
        if self.workspace:
            self.title_label.setText(
                self.workspace.get("name") or tr("workspace_title")
            )
        else:
            self.title_label.setText(tr("workspace_title"))

    def _render_blocks(self):
        self._clear_workspace_widgets()
        body_width, body_height = self._workspace_body_size()
        if not self.missionary or self.context is None:
            empty = QLabel(tr("workspace_no_workspaces"))
            empty.setObjectName("MutedText")
            empty.setParent(self.content)
            empty.setGeometry(QRect(18, 16, body_width - 36, 40))
            empty.show()
            self._workspace_block_widgets.append(empty)
            self.content.setMinimumSize(QSize(body_width, body_height))
            self.content.resize(body_width, body_height)
            return

        factory = WorkspaceBlockFactory(self)
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

    def _clear_workspace_widgets(self):
        for widget in getattr(self, "_workspace_block_widgets", []):
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._workspace_block_widgets = []

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

    def go_back(self):
        if self.main_window is not None and hasattr(self.main_window, "stack"):
            detail_page = getattr(self.main_window, "detail_page", None)
            if detail_page is not None:
                self.main_window.stack.setCurrentWidget(detail_page)

    def refresh_context(self):
        if self.missionary is None:
            return
        self.request_workspace(
            self.missionary,
            self.workspace,
            force=True,
            refresh_detail=True,
        )

    def _refresh_detail_page(self):
        detail_page = getattr(self.main_window, "detail_page", None)
        if detail_page is None:
            return
        refresher = getattr(detail_page, "request_refresh", None)
        if callable(refresher):
            refresher(force=True)
            return
        if hasattr(detail_page, "load_missionary"):
            detail_page.load_missionary(self.missionary)

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
        documents = self.context.documents if self.context else []
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
            logger.exception("Failed to upload document from workspace page")
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
        for candidate in self.context.workflows if self.context else []:
            if getattr(candidate, "stage_name", None) == current_stage:
                workflow = candidate
                break
        if workflow is None and self.context and self.context.workflows:
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
            show_message(
                self,
                tr("workspace_block_tasks"),
                tr("workspace_action_failed"),
                kind="warning",
            )
