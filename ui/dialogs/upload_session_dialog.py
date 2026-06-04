from dataclasses import dataclass, field
from pathlib import Path

import fitz
from shiboken6 import isValid as shiboken_is_valid

from PySide6.QtCore import QDate, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from services.document_image_export_service import DocumentImageExportService
from services.document_service import DocumentService
from services.upload_pipeline import (
    UploadPipelineResult,
    finalize_ocr_ingestion,
    get_missing_for_missionary,
    prepare_ocr_ingestion,
)
from ui.dialogs.ocr_review_dialog import OCRReviewDialog
from ui.dialogs.upload_summary_dialog import UploadSummaryDialog
from ui.foundation import (
    create_button,
    create_combo_box,
    create_date_edit,
    create_line_edit,
    create_list_widget,
    create_plain_text_edit,
    create_scroll_area,
    create_slider,
    show_message,
)
from ui.widgets.crop_graphics_view import CropGraphicsView
from utils.constants import DOCUMENTS, MISSIONARY_DATE_FIELDS, WORKFLOW_STAGES
from utils.i18n import field_label, tr
from utils.logger import logger

try:
    from qfluentwidgets import MaskDialogBase

    FLUENT_DIALOG_AVAILABLE = True
except Exception:
    MaskDialogBase = QDialog
    FLUENT_DIALOG_AVAILABLE = False


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
}
DATE_PLACEHOLDER = QDate(1900, 1, 1)


def _widget_alive(widget):
    try:
        return widget is not None and shiboken_is_valid(widget)
    except Exception:
        return False


def _refresh_style(widget):
    if widget is None:
        return
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


@dataclass
class UploadQueueItem:
    file_path: str
    document_type: str = "PASSPORT"
    workflow_stage: str = "GENERAL"
    export_settings: dict = field(default_factory=dict)
    ocr_result: object = None
    confirmed_data: dict = field(default_factory=dict)
    ocr_reviewed: bool = False
    duplicate_action: str = "replace"
    status: str = "pending"
    error_text: str = ""
    updated_fields: list = field(default_factory=list)
    notes: str = ""
    saved_document_id: int | None = None

    @property
    def file_name(self):
        return Path(self.file_path).name

    @property
    def has_ocr_fields(self):
        return bool(
            DOCUMENTS.get(self.document_type, {}).get("ocr_fields", [])
        )

    @property
    def file_size_text(self):
        try:
            size = Path(self.file_path).stat().st_size
        except OSError:
            return "Unknown size"

        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"


@dataclass
class UploadSaveResult:
    item: UploadQueueItem | None = None
    status: str = "failed"
    document: object = None
    error_text: str = ""

    @property
    def succeeded(self):
        return self.status in {"saved", "skipped"}


class QueueItemWidget(QFrame):
    activated = Signal(int)

    def __init__(self, item, index, selected=False, parent=None):
        super().__init__(parent)
        self.setObjectName("UploadQueueItemCard")
        self.item = item
        self.index = index

        layout = QHBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        self.setLayout(layout)

        icon = QLabel("PDF" if item.file_name.lower().endswith(".pdf") else "IMG")
        icon.setObjectName("UploadFileIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(42, 42)
        icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(4)

        title = QLabel(item.file_name)
        title.setObjectName("UploadQueueTitle")
        title.setWordWrap(True)
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        meta = QLabel(
            f"{DOCUMENTS.get(item.document_type, {}).get('label', item.document_type)}"
            f"  .  {item.file_size_text}"
        )
        meta.setObjectName("UploadQueueMeta")
        meta.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        copy.addWidget(title)
        copy.addWidget(meta)

        badge = QLabel(UploadSessionDialog.status_text(item))
        badge.setObjectName("UploadStatusChip")
        badge.setProperty("status", item.status)
        badge.setAlignment(Qt.AlignCenter)
        badge.setMinimumWidth(88)
        badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout.addWidget(icon)
        layout.addLayout(copy, stretch=1)
        layout.addWidget(badge, alignment=Qt.AlignTop)

        if selected:
            self.setProperty("selected", True)
        _refresh_style(self)
        _refresh_style(badge)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.index)
        super().mouseReleaseEvent(event)


class UploadSessionController:
    def __init__(
        self,
        missionary,
        document_service=None,
        image_export_service=None,
    ):
        self.missionary = missionary
        self.document_service = document_service or DocumentService()
        self.image_export_service = (
            image_export_service or DocumentImageExportService()
        )
        self.items = []
        self.selected_index = -1
        self.saved_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.updated_fields = []

    def add_files(self, file_paths):
        added = []
        known = {str(Path(item.file_path)) for item in self.items}
        for file_path in file_paths:
            path = Path(file_path)
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            normalized = str(path)
            if normalized in known:
                continue
            item = UploadQueueItem(
                file_path=normalized,
                workflow_stage=self.derive_stage("PASSPORT"),
                export_settings=self.default_export_settings(path),
            )
            self.items.append(item)
            known.add(normalized)
            added.append(item)

        if self.selected_index < 0 and self.items:
            self.selected_index = 0

        return added

    def remove_item(self, index):
        if index < 0 or index >= len(self.items):
            return
        del self.items[index]
        if not self.items:
            self.selected_index = -1
        elif self.selected_index >= len(self.items):
            self.selected_index = len(self.items) - 1

    def select(self, index):
        if 0 <= index < len(self.items):
            self.selected_index = index

    def selected_item(self):
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None

    def set_document_type(self, index, document_type):
        if index < 0 or index >= len(self.items):
            return
        item = self.items[index]
        if document_type not in DOCUMENTS:
            document_type = "OTHER"
        logger.info(
            "Queue item %s type change: %s -> %s",
            index,
            item.document_type,
            document_type,
        )
        item.document_type = document_type
        item.workflow_stage = self.derive_stage(document_type)
        item.ocr_result = None
        item.confirmed_data = {}
        item.ocr_reviewed = False
        item.error_text = ""
        if item.status not in {"saved", "skipped"}:
            item.status = "pending"

    @staticmethod
    def derive_stage(document_type):
        return DOCUMENTS.get(document_type, {}).get("stage") or "GENERAL"

    @staticmethod
    def default_export_settings(path):
        if Path(path).suffix.lower() == ".pdf":
            return {
                "page": 0,
                "pages": "all",
                "rotation": 0,
                "crop_rect": None,
            }
        return {
            "page": 0,
            "rotation": 0,
            "crop_rect": None,
        }

    def has_duplicate(self, item):
        return self.document_service.document_type_exists(
            self.missionary.id,
            item.document_type,
        )

    def run_ocr(self, item, parent=None, review=False):
        ocr_fields = DOCUMENTS.get(item.document_type, {}).get(
            "ocr_fields", []
        )
        if not ocr_fields:
            item.ocr_result = None
            item.confirmed_data = {}
            item.ocr_reviewed = False
            item.status = "pending"
            return None

        item.status = "ocr"
        item.error_text = ""
        item.ocr_result = prepare_ocr_ingestion(
            source_file=item.file_path,
            document_type=item.document_type,
            export_settings=item.export_settings,
            parent=parent,
            ocr_fields=ocr_fields,
            image_export_service=self.image_export_service,
        )
        item.confirmed_data = dict(item.ocr_result.parsed_data or {})
        item.ocr_reviewed = False

        if review:
            self.review_ocr_result(item, parent=parent)

        self._apply_post_ocr_state(item)
        return item.ocr_result

    def review_ocr_result(self, item, parent=None):
        ocr_result = item.ocr_result
        if ocr_result is None:
            return False

        ocr_fields = DOCUMENTS.get(item.document_type, {}).get(
            "ocr_fields", []
        )
        if not ocr_fields:
            return False

        review = OCRReviewDialog(
            ocr_fields=ocr_fields,
            parsed_data=item.confirmed_data or ocr_result.parsed_data,
            parent=parent or None,
            ocr_status=ocr_result.ocr_status,
            image_path=ocr_result.ocr_image_path,
        )

        if review.exec() == QDialog.Accepted:
            item.confirmed_data = review.get_data()
            item.ocr_reviewed = True
            self._apply_post_ocr_state(item)
            return True
        return False

    def _apply_post_ocr_state(self, item):
        if item.ocr_result is None:
            item.status = "pending"
            return

        status = item.ocr_result.ocr_status
        if status == "success":
            item.status = "ready"
            item.error_text = ""
        elif status == "partial":
            item.status = "review"
            item.error_text = "OCR found some fields. Please review."
        elif status == "failed":
            item.status = "review"
            error_message = item.ocr_result.errors[:1]
            item.error_text = (
                error_message[0]
                if error_message
                else "OCR could not read this document."
            )
        else:
            item.status = "pending"
            item.error_text = ""

    def save_item(self, item, parent=None, run_ocr=True):
        try:
            if item.duplicate_action == "skip":
                item.status = "skipped"
                item.error_text = ""
                self.skipped_count += 1
                logger.info(
                    "Skipping upload for missionary=%s file=%s type=%s",
                    self.missionary.id,
                    item.file_name,
                    item.document_type,
                )
                return UploadSaveResult(item=item, status="skipped")

            document_type = item.document_type
            if document_type not in DOCUMENTS:
                raise ValueError("document_type is required")

            workflow_stage = item.workflow_stage or self.derive_stage(
                document_type
            )
            if not workflow_stage:
                workflow_stage = "GENERAL"

            logger.info(
                "Saving upload item missionary=%s file=%s type=%s stage=%s ocr=%s",
                self.missionary.id,
                item.file_name,
                document_type,
                workflow_stage,
                item.has_ocr_fields,
            )

            if (
                item.duplicate_action == "replace"
                and self.has_duplicate(item)
            ):
                self.document_service.delete_document_by_type(
                    self.missionary.id,
                    document_type,
                )

            document = None
            if item.has_ocr_fields:
                if item.ocr_result is None and run_ocr:
                    self.run_ocr(item, parent=parent)
                if item.ocr_result is None:
                    ocr_fields = DOCUMENTS.get(
                        item.document_type, {}
                    ).get("ocr_fields", [])
                    item.ocr_result = UploadPipelineResult(
                        ocr_status="skipped",
                        document_type=item.document_type,
                        ocr_fields=list(ocr_fields),
                        export_settings=item.export_settings,
                    )
                if (
                    not item.confirmed_data
                    and item.ocr_result
                    and not item.ocr_reviewed
                ):
                    item.confirmed_data = dict(
                        item.ocr_result.parsed_data or {}
                    )
                save_result = finalize_ocr_ingestion(
                    missionary=self.missionary,
                    source_file=item.file_path,
                    document_type=document_type,
                    workflow_stage=workflow_stage,
                    pipeline_result=item.ocr_result,
                    confirmed_data=item.confirmed_data,
                    document_service=self.document_service,
                )
                item.updated_fields = list(
                    save_result.updated_fields or []
                )
                document = save_result.document
            else:
                document = self.document_service.upload_document(
                    missionary=self.missionary,
                    source_file=item.file_path,
                    document_type=document_type,
                    workflow_stage=workflow_stage,
                )
                item.updated_fields = []

            if document and item.notes.strip():
                self.document_service.update_document_notes(
                    document.id,
                    item.notes.strip(),
                )
            item.saved_document_id = getattr(document, "id", None)
            item.status = "saved"
            item.error_text = ""
            self.saved_count += 1
            self.updated_fields.extend(item.updated_fields)
            logger.info(
                "Saved upload item missionary=%s file=%s type=%s stage=%s document_id=%s",
                self.missionary.id,
                item.file_name,
                document_type,
                workflow_stage,
                getattr(document, "id", None),
            )
            return UploadSaveResult(
                item=item,
                status="saved",
                document=document,
            )
        except Exception as exc:
            logger.exception("Upload session save failed")
            item.status = "failed"
            item.error_text = str(exc)
            self.failed_count += 1
            return UploadSaveResult(
                item=item,
                status="failed",
                error_text=str(exc),
            )

    def has_saved_items(self):
        return any(item.status == "saved" for item in self.items)

    def summary(self):
        current_stage = getattr(
            self.missionary,
            "current_stage",
            None,
        )
        missing = []
        if current_stage:
            try:
                missing = get_missing_for_missionary(
                    self.missionary.id,
                    current_stage,
                )
            except Exception:
                logger.exception("Failed to collect upload summary")
        return {
            "uploaded": sum(1 for item in self.items if item.status == "saved"),
            "failed": sum(1 for item in self.items if item.status == "failed"),
            "skipped": sum(1 for item in self.items if item.status == "skipped"),
            "updated_fields": sorted(set(self.updated_fields)),
            "missing_documents": missing,
        }


class UploadSessionDialog(MaskDialogBase):
    def __init__(self, missionary, initial_files=None, parent=None):
        super().__init__(parent)
        self.controller = UploadSessionController(missionary)
        self.document = None
        self.current_pixmap = None
        self.field_edits = {}
        self.date_edits = {}
        self._detail_item_index = -1
        self._is_closing = False
        self._backdrop_label = None
        self._backdrop_scrim = None
        self._surface_host = None

        self.setWindowTitle("Upload Documents")
        self.setAcceptDrops(True)

        if FLUENT_DIALOG_AVAILABLE:
            self._configure_fluent_shell()
        else:
            self._configure_fallback_shell()

        self.setup_ui()
        if initial_files:
            self.add_files(initial_files)

    def _configure_fluent_shell(self):
        self.setMaskColor(QColor(74, 80, 90, 84))
        self.setShadowEffect(
            70,
            (0, 16),
            QColor(15, 23, 42, 90),
        )

        self._hBoxLayout.setContentsMargins(24, 24, 24, 24)
        self._hBoxLayout.removeWidget(self.widget)
        self._hBoxLayout.addWidget(
            self.widget,
            1,
            Qt.AlignCenter,
        )

        self.widget.setObjectName("UploadWorkspaceSurface")
        self.widget.setAttribute(Qt.WA_StyledBackground, True)
        self.widget.setFixedWidth(1240)
        self.widget.setMinimumHeight(820)

    def _configure_fallback_shell(self):
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("UploadWorkspaceDialog")

        host = self._resolve_backdrop_source()
        if host is not None:
            self.resize(host.size())
        else:
            self.resize(1400, 900)

    def _resolve_backdrop_source(self):
        parent = self.parentWidget()
        if not parent:
            return None

        window = parent.window()
        if window and window is not self:
            return window

        return parent

    def _ensure_fallback_backdrop(self):
        if FLUENT_DIALOG_AVAILABLE or self._backdrop_label is not None:
            return

        self._backdrop_label = QLabel(self)
        self._backdrop_label.setObjectName("UploadBackdrop")
        self._backdrop_label.setScaledContents(True)
        self._backdrop_label.lower()

        self._backdrop_scrim = QWidget(self)
        self._backdrop_scrim.setObjectName("UploadBackdropScrim")
        self._backdrop_scrim.lower()

        self._sync_fallback_backdrop_geometry()

    def _sync_fallback_backdrop_geometry(self):
        if FLUENT_DIALOG_AVAILABLE:
            return

        rect = self.rect()
        if self._backdrop_label is not None:
            self._backdrop_label.setGeometry(rect)
        if self._backdrop_scrim is not None:
            self._backdrop_scrim.setGeometry(rect)

    def _refresh_fallback_backdrop(self):
        if FLUENT_DIALOG_AVAILABLE:
            return

        self._ensure_fallback_backdrop()

        host = self._resolve_backdrop_source()
        if host is None:
            return

        capture = host.grab()
        if capture.isNull():
            return

        blurred = self._blur_pixmap(capture)
        self._backdrop_label.setPixmap(blurred)

    @staticmethod
    def _blur_pixmap(pixmap, radius=18):
        if pixmap.isNull():
            return pixmap

        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(pixmap)
        effect = item.graphicsEffect()
        if effect is None:
            from PySide6.QtWidgets import QGraphicsBlurEffect

            effect = QGraphicsBlurEffect()
            effect.setBlurRadius(radius)
            item.setGraphicsEffect(effect)

        scene.addItem(item)
        result = QImage(
            pixmap.size(),
            QImage.Format_ARGB32_Premultiplied,
        )
        result.fill(Qt.transparent)

        painter = QPainter(result)
        scene.render(
            painter,
            QRectF(result.rect()),
            QRectF(0, 0, pixmap.width(), pixmap.height()),
        )
        painter.end()
        return QPixmap.fromImage(result)

    def setup_ui(self):
        if FLUENT_DIALOG_AVAILABLE:
            surface = self.widget
            root_target = surface
        else:
            self._ensure_fallback_backdrop()
            self._surface_host = QFrame(self)
            self._surface_host.setObjectName("UploadWorkspaceSurface")
            self._surface_host.setAttribute(Qt.WA_StyledBackground, True)
            self._surface_host.setFixedWidth(1240)
            self._surface_host.setMinimumHeight(820)

            shell_layout = QVBoxLayout()
            shell_layout.setContentsMargins(24, 24, 24, 24)
            shell_layout.setSpacing(0)
            self.setLayout(shell_layout)
            shell_layout.addWidget(
                self._surface_host,
                1,
                Qt.AlignCenter,
            )
            surface = self._surface_host
            root_target = surface

        surface.setObjectName("UploadWorkspaceSurface")
        surface.setAttribute(Qt.WA_StyledBackground, True)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root_target.setLayout(root)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setObjectName("UploadWorkspaceSplitter")
        root.addWidget(self.splitter, stretch=1)

        self.left_panel = QFrame()
        self.left_panel.setObjectName("UploadSurfaceCard")
        self.left_panel.setAttribute(Qt.WA_StyledBackground, True)
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(24, 22, 24, 22)
        left_layout.setSpacing(14)
        self.left_panel.setLayout(left_layout)

        queue_header = QHBoxLayout()
        queue_header.setSpacing(10)
        queue_title = QLabel("Upload Queue")
        queue_title.setObjectName("PanelTitle")
        self.queue_count_badge = QLabel("0 files")
        self.queue_count_badge.setObjectName("UploadCountBadge")
        import_folder_btn = create_button("Import Folder", "secondary", fixed_height=34)
        import_folder_btn.clicked.connect(self.pick_folder)
        add_btn = create_button("Add Files", "primary", fixed_height=34)
        add_btn.clicked.connect(self.pick_files)
        queue_header.addWidget(queue_title)
        queue_header.addWidget(self.queue_count_badge)
        queue_header.addStretch()
        queue_header.addWidget(import_folder_btn)
        queue_header.addWidget(add_btn)
        left_layout.addLayout(queue_header)

        self.progress_label = QLabel("No files selected.")
        self.progress_label.setObjectName("UploadCompactStatus")
        left_layout.addWidget(self.progress_label)

        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(8)
        self.saved_stat = self._make_stat_chip("0 saved", "success")
        self.failed_stat = self._make_stat_chip("0 failed", "danger")
        self.pending_stat = self._make_stat_chip("0 queued", "info")
        self.stats_row.addWidget(self.saved_stat)
        self.stats_row.addWidget(self.failed_stat)
        self.stats_row.addWidget(self.pending_stat)
        self.stats_row.addStretch()
        left_layout.addLayout(self.stats_row)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("UploadDropZone")
        self.drop_zone.setAttribute(Qt.WA_StyledBackground, True)
        drop_layout = QVBoxLayout()
        drop_layout.setContentsMargins(18, 24, 18, 24)
        drop_layout.setSpacing(8)
        self.drop_zone.setLayout(drop_layout)

        drop_icon = QLabel("Upload")
        drop_icon.setObjectName("UploadDropIcon")
        drop_icon.setAlignment(Qt.AlignCenter)
        drop_copy = QLabel("Drop files here or browse")
        drop_copy.setObjectName("UploadDropTitle")
        drop_copy.setAlignment(Qt.AlignCenter)
        drop_hint = QLabel("PDF, JPG, PNG up to 25 MB each")
        drop_hint.setObjectName("MiniMutedText")
        drop_hint.setAlignment(Qt.AlignCenter)
        browse_btn = create_button("Browse Files", "secondary")
        browse_btn.clicked.connect(self.pick_files)
        drop_layout.addWidget(drop_icon)
        drop_layout.addWidget(drop_copy)
        drop_layout.addWidget(drop_hint)
        drop_layout.addWidget(browse_btn, alignment=Qt.AlignCenter)
        left_layout.addWidget(self.drop_zone)

        self.queue_list = create_list_widget()
        self.queue_list.setObjectName("UploadQueueList")
        self.queue_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.queue_list.currentRowChanged.connect(self.select_item)
        self.queue_list.setSpacing(10)
        left_layout.addWidget(self.queue_list, stretch=1)

        queue_footer = QHBoxLayout()
        queue_footer.setSpacing(10)
        queue_note = QLabel("Files are OCR processed automatically after upload.")
        queue_note.setObjectName("SubtleText")
        remove_btn = create_button("Remove", "secondary")
        remove_btn.clicked.connect(self.remove_selected)
        queue_footer.addWidget(queue_note, stretch=1)
        queue_footer.addWidget(remove_btn)
        left_layout.addLayout(queue_footer)
        self.splitter.addWidget(self.left_panel)

        self.right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)
        self.right_panel.setLayout(right_layout)

        self.preview_card = QFrame()
        self.preview_card.setObjectName("UploadSurfaceCard")
        self.preview_card.setAttribute(Qt.WA_StyledBackground, True)
        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(12)
        self.preview_card.setLayout(preview_layout)

        preview_header = QHBoxLayout()
        preview_title_stack = QVBoxLayout()
        preview_title_stack.setSpacing(4)
        self.preview_name_label = QLabel("No document selected")
        self.preview_name_label.setObjectName("PanelTitle")
        self.preview_meta_label = QLabel("Add files to begin.")
        self.preview_meta_label.setObjectName("MutedText")
        preview_title_stack.addWidget(self.preview_name_label)
        preview_title_stack.addWidget(self.preview_meta_label)
        preview_header.addLayout(preview_title_stack, stretch=1)
        self.preview_status_badge = QLabel("Pending")
        self.preview_status_badge.setObjectName("UploadStatusChip")
        self.preview_status_badge.setProperty("status", "pending")
        preview_header.addWidget(self.preview_status_badge, alignment=Qt.AlignTop)
        preview_layout.addLayout(preview_header)

        self.page_list = create_list_widget()
        self.page_list.setObjectName("UploadPageList")
        self.page_list.setMaximumHeight(92)
        self.page_list.currentRowChanged.connect(self.change_page)
        preview_layout.addWidget(self.page_list)

        self.scene = QGraphicsScene()
        self.graphics_view = CropGraphicsView()
        self.graphics_view.setScene(self.scene)
        self.graphics_view.setObjectName("UploadPreviewCanvas")
        preview_layout.addWidget(self.graphics_view, stretch=1)

        preview_tools = QHBoxLayout()
        preview_tools.setSpacing(12)
        rotation_label = QLabel("Rotation")
        rotation_label.setObjectName("MutedText")
        self.rotation_value_label = QLabel("0 deg")
        self.rotation_value_label.setObjectName("StrongText")
        self.rotation_slider = create_slider(Qt.Horizontal)
        self.rotation_slider.setRange(-180, 180)
        self.rotation_slider.valueChanged.connect(self.rotation_changed)
        preview_tools.addWidget(rotation_label)
        preview_tools.addWidget(self.rotation_slider, stretch=1)
        preview_tools.addWidget(self.rotation_value_label)
        preview_layout.addLayout(preview_tools)
        right_layout.addWidget(self.preview_card, stretch=1)

        self.details_card = QFrame()
        self.details_card.setObjectName("UploadSurfaceCard")
        self.details_card.setAttribute(Qt.WA_StyledBackground, True)
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(18, 18, 18, 18)
        details_layout.setSpacing(14)
        self.details_card.setLayout(details_layout)

        details_title = QLabel("Document Details")
        details_title.setObjectName("PanelTitle")
        details_layout.addWidget(details_title)

        summary_form = QFormLayout()
        summary_form.setSpacing(10)
        summary_form.setContentsMargins(0, 0, 0, 0)

        self.type_combo = create_combo_box()
        self.type_combo.setObjectName("UploadFieldInput")
        for key, config in DOCUMENTS.items():
            self.type_combo.addItem(config["label"], key)
        self.type_combo.currentIndexChanged.connect(self.type_changed)
        summary_form.addRow("Document Type", self.type_combo)

        self.stage_combo = create_combo_box()
        self.stage_combo.setObjectName("UploadFieldInput")
        self.stage_combo.addItem("GENERAL", "GENERAL")
        for stage in WORKFLOW_STAGES:
            self.stage_combo.addItem(stage, stage)
        self.stage_combo.currentIndexChanged.connect(self.stage_changed)
        summary_form.addRow("Workflow Stage", self.stage_combo)

        self.missionary_label = QLabel(self.controller.missionary.full_name)
        self.missionary_label.setObjectName("UploadReadValue")
        summary_form.addRow("Missionary", self.missionary_label)

        self.duplicate_combo = create_combo_box()
        self.duplicate_combo.setObjectName("UploadFieldInput")
        self.duplicate_combo.addItem("Replace existing", "replace")
        self.duplicate_combo.addItem("Keep both", "keep")
        self.duplicate_combo.addItem("Skip this file", "skip")
        self.duplicate_combo.currentIndexChanged.connect(
            self.duplicate_changed
        )
        summary_form.addRow("If duplicate", self.duplicate_combo)
        details_layout.addLayout(summary_form)

        ocr_tools = QHBoxLayout()
        ocr_tools.setSpacing(10)
        self.ocr_status_label = QLabel("OCR fields will appear here.")
        self.ocr_status_label.setObjectName("OcrStatusBanner")
        self.ocr_status_label.setProperty("status", "skipped")
        self.ocr_status_label.setWordWrap(True)
        self.ocr_checkbox = QCheckBox("Run OCR automatically")
        self.ocr_checkbox.setChecked(True)
        rerun_ocr_btn = create_button("Rerun OCR", "secondary")
        rerun_ocr_btn.clicked.connect(self.run_ocr_for_selected)
        review_ocr_btn = create_button("Review OCR", "secondary")
        review_ocr_btn.clicked.connect(self.review_ocr_for_selected)
        ocr_tools.addWidget(self.ocr_status_label, stretch=1)
        ocr_tools.addWidget(self.ocr_checkbox)
        ocr_tools.addWidget(rerun_ocr_btn)
        ocr_tools.addWidget(review_ocr_btn)
        details_layout.addLayout(ocr_tools)

        self.duplicate_warning = QLabel("")
        self.duplicate_warning.setObjectName("OcrStatusBanner")
        self.duplicate_warning.setProperty("status", "partial")
        self.duplicate_warning.setWordWrap(True)
        self.duplicate_warning.hide()
        details_layout.addWidget(self.duplicate_warning)

        self.ocr_form_widget = QWidget()
        self.ocr_form = QFormLayout()
        self.ocr_form.setSpacing(10)
        self.ocr_form_widget.setLayout(self.ocr_form)
        scroll = create_scroll_area()
        scroll.setWidget(self.ocr_form_widget)
        scroll.setObjectName("UploadDetailsScroll")
        details_layout.addWidget(scroll, stretch=1)

        notes_label = QLabel("Notes")
        notes_label.setObjectName("MutedText")
        self.notes_editor = create_plain_text_edit()
        self.notes_editor.setObjectName("DocumentNotesEditor")
        self.notes_editor.setPlaceholderText("Add any context about this document.")
        self.notes_editor.setFixedHeight(88)
        self.notes_editor.textChanged.connect(self.notes_changed)
        details_layout.addWidget(notes_label)
        details_layout.addWidget(self.notes_editor)
        right_layout.addWidget(self.details_card, stretch=1)

        self.progress_card = QFrame()
        self.progress_card.setObjectName("UploadSurfaceCard")
        self.progress_card.setAttribute(Qt.WA_StyledBackground, True)
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(18, 14, 18, 14)
        progress_layout.setSpacing(20)
        self.progress_card.setLayout(progress_layout)

        self.progress_step_files = self._make_progress_step(
            "1", "Select files", "Waiting"
        )
        self.progress_step_review = self._make_progress_step(
            "2", "Review metadata", "Not started"
        )
        self.progress_step_save = self._make_progress_step(
            "3", "Save records", "Not started"
        )
        progress_layout.addWidget(self.progress_step_files)
        progress_layout.addWidget(self.progress_step_review)
        progress_layout.addWidget(self.progress_step_save)
        right_layout.addWidget(self.progress_card)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([470, 750])

        self.footer = QFrame()
        self.footer.setObjectName("PageHeader")
        self.footer.setAttribute(Qt.WA_StyledBackground, True)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(24, 14, 24, 18)
        footer_layout.setSpacing(12)
        self.footer.setLayout(footer_layout)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("SubtleText")
        cancel_btn = create_button("Cancel", "secondary")
        cancel_btn.clicked.connect(self.reject)
        next_btn = create_button("Next", "secondary")
        next_btn.clicked.connect(self.go_to_next_item)
        save_current_btn = create_button("Save Current", "primary")
        save_current_btn.clicked.connect(self.save_current)
        save_all_btn = create_button("Save All", "success")
        save_all_btn.clicked.connect(self.save_all)

        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch()
        footer_layout.addWidget(cancel_btn)
        footer_layout.addWidget(next_btn)
        footer_layout.addWidget(save_current_btn)
        footer_layout.addWidget(save_all_btn)
        root.addWidget(self.footer)

    def _make_stat_chip(self, text, tone):
        label = QLabel(text)
        label.setObjectName("UploadSummaryChip")
        label.setProperty("tone", tone)
        return label

    def _make_progress_step(self, number, title, subtitle):
        frame = QFrame()
        frame.setObjectName("UploadProgressStep")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        frame.setLayout(layout)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        badge = QLabel(number)
        badge.setObjectName("UploadStepBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(28, 28)
        row.addWidget(badge)

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("StrongText")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("SubtleText")
        copy.addWidget(title_label)
        copy.addWidget(subtitle_label)
        row.addLayout(copy)
        row.addStretch()

        layout.addLayout(row)
        return frame

    def pick_files(self, checked=False):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Documents",
            "",
            "Documents (*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.tif)",
        )
        self.add_files(files)

    def pick_folder(self, checked=False):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder",
            "",
        )
        if not folder:
            return

        files = [
            str(path)
            for path in Path(folder).rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not files:
            show_message(
                self,
                "No supported files",
                "No PDF or image files were found in that folder.",
            )
            return

        self.add_files(files)

    def add_files(self, files):
        added = self.controller.add_files(files)
        self.refresh_queue()
        if self.controller.selected_index >= 0:
            self._set_queue_row(self.controller.selected_index)
        elif self.controller.items:
            self._set_queue_row(0)

        if added and self.ocr_checkbox.isChecked():
            self.auto_run_ocr_for_items(added)

        self.refresh_queue()
        if self.controller.selected_index >= 0:
            self._switch_to_item(
                self.controller.selected_index,
                persist_current=False,
            )
        self.update_progress()

    def auto_run_ocr_for_items(self, items):
        for item in items:
            if item.has_ocr_fields:
                self.controller.run_ocr(item, parent=self, review=False)

    def remove_selected(self, checked=False):
        row = self.queue_list.currentRow() if _widget_alive(self.queue_list) else -1
        self.controller.remove_item(row)
        self.refresh_queue()
        if self.controller.selected_index >= 0:
            self._switch_to_item(
                self.controller.selected_index,
                persist_current=False,
            )
        else:
            self.clear_detail()
        self.update_progress()

    def refresh_queue(self):
        if self._is_closing or not _widget_alive(self.queue_list):
            return
        current = self.queue_list.currentRow()
        if current < 0:
            current = self.controller.selected_index
        self.queue_list.blockSignals(True)
        self.queue_list.clear()
        for index, item in enumerate(self.controller.items):
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(250, 78))
            self.queue_list.addItem(list_item)
            widget = QueueItemWidget(
                item,
                index,
                selected=(index == current),
            )
            widget.activated.connect(self._activate_queue_card)
            self.queue_list.setItemWidget(list_item, widget)
        if 0 <= current < self.queue_list.count():
            self.queue_list.setCurrentRow(current)
        self.queue_list.blockSignals(False)
        self.queue_count_badge.setText(
            f"{len(self.controller.items)} file"
            f"{'' if len(self.controller.items) == 1 else 's'}"
        )

    def _set_queue_row(self, index):
        if not _widget_alive(self.queue_list):
            return
        self.queue_list.blockSignals(True)
        try:
            self.queue_list.setCurrentRow(index)
        finally:
            self.queue_list.blockSignals(False)

    def _activate_queue_card(self, index):
        if (
            self._is_closing
            or index < 0
            or index >= len(self.controller.items)
        ):
            return
        self._switch_to_item(index, persist_current=True)

    def _detail_widgets_available(self):
        if self._is_closing:
            return False
        required = [
            self.type_combo,
            self.stage_combo,
            self.duplicate_combo,
            self.notes_editor,
            self.preview_name_label,
            self.preview_meta_label,
            self.preview_status_badge,
            self.status_label,
            self.ocr_status_label,
        ]
        return all(_widget_alive(widget) for widget in required)

    def _persist_item_state_for_index(self, index):
        if (
            self._is_closing
            or index < 0
            or index >= len(self.controller.items)
        ):
            return
        original_index = self.controller.selected_index
        self.controller.select(index)
        try:
            self.persist_current_item_state()
        finally:
            self.controller.select(original_index)

    def _switch_to_item(self, index, persist_current=True):
        if self._is_closing:
            return
        if persist_current:
            self._persist_item_state_for_index(self._detail_item_index)

        if index < 0 or index >= len(self.controller.items):
            self._detail_item_index = -1
            self.clear_detail()
            self.refresh_queue()
            return

        current_item = self.controller.items[index]
        logger.info(
            "Switching upload detail to index=%s file=%s type=%s stage=%s status=%s",
            index,
            current_item.file_name,
            current_item.document_type,
            current_item.workflow_stage,
            current_item.status,
        )
        self.controller.select(index)
        self._set_queue_row(index)
        try:
            self.load_detail()
        except RuntimeError:
            logger.exception("Failed to load upload session detail")
        finally:
            self.refresh_queue()

    @staticmethod
    def status_text(item):
        return {
            "pending": "Queued",
            "ocr": "Reading",
            "ready": "Ready",
            "review": "Needs review",
            "saved": "Saved",
            "failed": "Failed",
            "skipped": "Skipped",
        }.get(item.status, item.status.title())

    def select_item(self, row):
        self._switch_to_item(row, persist_current=True)

    def load_detail(self):
        if not self._detail_widgets_available():
            return
        item = self.controller.selected_item()
        if item is None:
            self._detail_item_index = -1
            self.clear_detail()
            return

        if _widget_alive(self.type_combo):
            idx = self.type_combo.findData(item.document_type)
            if idx >= 0:
                self.type_combo.blockSignals(True)
                self.type_combo.setCurrentIndex(idx)
                self.type_combo.blockSignals(False)
        if _widget_alive(self.stage_combo):
            stage_idx = self.stage_combo.findData(item.workflow_stage)
            if stage_idx >= 0:
                self.stage_combo.blockSignals(True)
                self.stage_combo.setCurrentIndex(stage_idx)
                self.stage_combo.blockSignals(False)
        if _widget_alive(self.duplicate_combo):
            dup_idx = self.duplicate_combo.findData(item.duplicate_action)
            if dup_idx >= 0:
                self.duplicate_combo.blockSignals(True)
                self.duplicate_combo.setCurrentIndex(dup_idx)
                self.duplicate_combo.blockSignals(False)
        if _widget_alive(self.notes_editor):
            self.notes_editor.blockSignals(True)
            try:
                self.notes_editor.setPlainText(item.notes or "")
            finally:
                self.notes_editor.blockSignals(False)

        self.load_preview(item)
        self.render_ocr_fields(item)
        self.update_duplicate_warning(item)
        if _widget_alive(self.status_label):
            self.status_label.setText(item.error_text or "Ready.")
        if _widget_alive(self.preview_name_label):
            self.preview_name_label.setText(item.file_name)
        if _widget_alive(self.preview_meta_label):
            self.preview_meta_label.setText(
                f"{DOCUMENTS.get(item.document_type, {}).get('label', item.document_type)}"
                f"  .  {item.file_size_text}"
            )
        if _widget_alive(self.preview_status_badge):
            self.preview_status_badge.setText(self.status_text(item))
            self.preview_status_badge.setProperty("status", item.status)
            _refresh_style(self.preview_status_badge)
        self._detail_item_index = self.controller.selected_index

    def clear_detail(self):
        self._detail_item_index = -1
        try:
            if _widget_alive(self.scene):
                self.scene.clear()
        except RuntimeError:
            pass
        try:
            if _widget_alive(self.page_list):
                self.page_list.clear()
        except RuntimeError:
            pass
        self.clear_ocr_form()
        try:
            if _widget_alive(self.stage_combo):
                idx = self.stage_combo.findData("GENERAL")
                if idx >= 0:
                    self.stage_combo.blockSignals(True)
                    self.stage_combo.setCurrentIndex(idx)
                    self.stage_combo.blockSignals(False)
            if _widget_alive(self.preview_name_label):
                self.preview_name_label.setText("No document selected")
            if _widget_alive(self.preview_meta_label):
                self.preview_meta_label.setText("Add files to begin.")
            if _widget_alive(self.notes_editor):
                self.notes_editor.blockSignals(True)
                try:
                    self.notes_editor.clear()
                finally:
                    self.notes_editor.blockSignals(False)
        except RuntimeError:
            pass
        self.apply_ocr_banner("skipped", "OCR fields will appear here.")
        try:
            if _widget_alive(self.status_label):
                self.status_label.setText("Add files to begin.")
        except RuntimeError:
            pass

    def type_changed(self, checked=False):
        item = self.controller.selected_item()
        if item is None:
            return
        logger.info(
            "Type combo changed for selected upload item index=%s current_type=%s current_stage=%s",
            self.controller.selected_index,
            item.document_type,
            item.workflow_stage,
        )
        self.persist_current_editor_settings(item)
        current_index = self.controller.selected_index
        self.controller.set_document_type(
            current_index,
            self.type_combo.currentData(),
        )
        item = self.controller.selected_item()
        if self.ocr_checkbox.isChecked() and item.has_ocr_fields:
            self.controller.run_ocr(item, parent=self, review=False)
        self.load_detail()
        self.refresh_queue()
        self.update_progress()

    def stage_changed(self, checked=False):
        item = self.controller.selected_item()
        if item is None or not _widget_alive(self.stage_combo):
            return
        item.workflow_stage = self.stage_combo.currentData() or "GENERAL"
        self.refresh_queue()

    def duplicate_changed(self, checked=False):
        item = self.controller.selected_item()
        if item is not None:
            item.duplicate_action = self.duplicate_combo.currentData()

    def notes_changed(self):
        if self._is_closing or not _widget_alive(self.notes_editor):
            return
        item = self.controller.selected_item()
        if item is not None:
            item.notes = self.notes_editor.toPlainText().strip()

    def _sync_current_ocr_data(self):
        if self._is_closing:
            return
        item = self.controller.selected_item()
        if item is not None and item.has_ocr_fields:
            self.collect_ocr_data(item)

    def update_duplicate_warning(self, item):
        if not _widget_alive(self.duplicate_warning):
            return
        if self.controller.has_duplicate(item):
            self.duplicate_warning.setText(
                "A document of this type already exists for this missionary."
            )
            self.duplicate_warning.show()
        else:
            self.duplicate_warning.hide()

    def load_preview(self, item):
        if self._is_closing:
            return
        self.close_document()
        if _widget_alive(self.page_list):
            self.page_list.blockSignals(True)
            self.page_list.clear()
        if _widget_alive(self.rotation_slider):
            self.rotation_slider.blockSignals(True)
            self.rotation_slider.setValue(
                int(item.export_settings.get("rotation", 0))
            )
            self.rotation_value_label.setText(
                f"{int(item.export_settings.get('rotation', 0))} deg"
            )
            self.rotation_slider.blockSignals(False)

        path = Path(item.file_path)
        if not path.exists():
            self.current_pixmap = None
            if _widget_alive(self.page_list):
                self.page_list.hide()
                self.page_list.blockSignals(False)
            self.update_preview()
            return

        if path.suffix.lower() == ".pdf":
            self.document = fitz.open(str(path))
            if _widget_alive(self.page_list):
                self.page_list.show()
                for page_index in range(len(self.document)):
                    self.page_list.addItem(f"Page {page_index + 1}")
                page = int(item.export_settings.get("page", 0))
                self.page_list.setCurrentRow(
                    min(page, len(self.document) - 1)
                )
                self.page_list.blockSignals(False)
                self.change_page(self.page_list.currentRow())
        else:
            if _widget_alive(self.page_list):
                self.page_list.hide()
                self.page_list.blockSignals(False)
            self.current_pixmap = QPixmap(str(path))
            self.update_preview()

    def close_document(self):
        if self.document:
            self.document.close()
        self.document = None

    def change_page(self, index):
        item = self.controller.selected_item()
        if item is not None and index >= 0:
            item.export_settings["page"] = index
        if self.document is None or index < 0:
            return

        page = self.document.load_page(index)
        pix = page.get_pixmap(dpi=180)
        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format_RGB888,
        )
        self.current_pixmap = QPixmap.fromImage(image.copy())
        self.update_preview()

    def rotation_changed(self, value):
        if self._is_closing or not _widget_alive(self.rotation_value_label):
            return
        item = self.controller.selected_item()
        if item is not None:
            item.export_settings["rotation"] = value
        self.rotation_value_label.setText(f"{value} deg")
        self.update_preview()

    def update_preview(self):
        if self._is_closing:
            return
        if not _widget_alive(self.scene):
            return
        self.scene.clear()
        if self.current_pixmap is None or self.current_pixmap.isNull():
            self.scene.addText("Preview unavailable")
            return

        rotated = self.current_pixmap.transformed(
            QTransform().rotate(
                self.rotation_slider.value()
                if _widget_alive(self.rotation_slider)
                else 0
            ),
            Qt.SmoothTransformation,
        )
        pix_item = QGraphicsPixmapItem(rotated)
        self.scene.addItem(pix_item)
        self.scene.setSceneRect(pix_item.boundingRect())
        self.graphics_view.fitInView(pix_item, Qt.KeepAspectRatio)

    def persist_current_editor_settings(self, item=None):
        if self._is_closing:
            return
        item = item or self.controller.selected_item()
        if item is None:
            return
        if _widget_alive(self.rotation_slider):
            item.export_settings["rotation"] = self.rotation_slider.value()
        if _widget_alive(self.page_list) and self.page_list.isVisible():
            if self.page_list.currentRow() >= 0:
                item.export_settings["page"] = self.page_list.currentRow()
        if _widget_alive(self.graphics_view):
            item.export_settings["crop_rect"] = self.graphics_view.get_crop_rect()

    def clear_ocr_form(self):
        try:
            while self.ocr_form.rowCount():
                self.ocr_form.removeRow(0)
        except RuntimeError:
            pass
        self.field_edits = {}
        self.date_edits = {}

    def render_ocr_fields(self, item):
        if self._is_closing or not _widget_alive(self.ocr_status_label):
            return
        self.clear_ocr_form()
        fields = DOCUMENTS.get(item.document_type, {}).get("ocr_fields", [])
        if not fields:
            self.apply_ocr_banner(
                "skipped",
                "This document type does not use OCR fields.",
            )
            return

        status = "OCR ready."
        state = "skipped"
        if item.ocr_result is not None:
            state = item.ocr_result.ocr_status
            status = tr(f"ocr_status_{item.ocr_result.ocr_status}")
        self.apply_ocr_banner(state, status)

        for field in fields:
            value = item.confirmed_data.get(field, "")
            label = field_label(field)
            if field in MISSIONARY_DATE_FIELDS or field == "date_of_birth":
                edit = create_date_edit()
                edit.setMinimumDate(DATE_PLACEHOLDER)
                edit.setSpecialValueText("--")
                parsed = self._to_qdate(value)
                edit.setDate(parsed or DATE_PLACEHOLDER)
                edit.dateChanged.connect(
                    lambda _value, self=self: self._sync_current_ocr_data()
                )
                self.date_edits[field] = edit
                if _widget_alive(self.ocr_form):
                    self.ocr_form.addRow(f"{label}", edit)
            else:
                edit = create_line_edit()
                edit.setText(str(value or ""))
                edit.textChanged.connect(
                    lambda _text, self=self: self._sync_current_ocr_data()
                )
                self.field_edits[field] = edit
                if _widget_alive(self.ocr_form):
                    self.ocr_form.addRow(f"{label}", edit)

    def apply_ocr_banner(self, status, text):
        if not _widget_alive(self.ocr_status_label):
            return
        self.ocr_status_label.setProperty("status", status)
        self.ocr_status_label.setText(text)
        _refresh_style(self.ocr_status_label)

    @staticmethod
    def _to_qdate(value):
        if not value:
            return None
        from services.upload_pipeline import parse_date_value

        parsed = parse_date_value(value)
        if not parsed:
            return None
        return QDate(parsed.year, parsed.month, parsed.day)

    def collect_ocr_data(self, item):
        if self._is_closing:
            return
        data = {}
        for field, edit in self.field_edits.items():
            data[field] = edit.text().strip()
        for field, edit in self.date_edits.items():
            qdate = edit.date()
            if qdate.isValid() and qdate != DATE_PLACEHOLDER:
                data[field] = qdate.toString("yyyy-MM-dd")
        item.confirmed_data = data

    def persist_current_item_state(self):
        if self._is_closing:
            return
        item = self.controller.selected_item()
        if item is None:
            return
        try:
            self.persist_current_editor_settings(item)
        except RuntimeError:
            logger.exception("Failed to persist editor state")
        if item.has_ocr_fields:
            try:
                self.collect_ocr_data(item)
            except RuntimeError:
                logger.exception("Failed to persist OCR form state")
        if _widget_alive(self.notes_editor):
            item.notes = self.notes_editor.toPlainText().strip()

    def run_ocr_for_selected(self, checked=False):
        item = self.controller.selected_item()
        if item is None:
            return
        self.persist_current_editor_settings(item)
        self.controller.run_ocr(item, parent=self, review=False)
        self.render_ocr_fields(item)
        self.refresh_queue()
        self.update_progress()
        self.status_label.setText(item.error_text or "OCR updated.")

    def review_ocr_for_selected(self, checked=False):
        item = self.controller.selected_item()
        if item is None:
            return
        if item.ocr_result is None:
            self.controller.run_ocr(item, parent=self, review=False)
        if self.controller.review_ocr_result(item, parent=self):
            self.render_ocr_fields(item)
            self.refresh_queue()
            self.update_progress()

    def save_current(self, checked=False):
        item = self.controller.selected_item()
        if item is None:
            return
        logger.info(
            "Save Current clicked for index=%s file=%s type=%s stage=%s status=%s",
            self.controller.selected_index,
            item.file_name,
            item.document_type,
            item.workflow_stage,
            item.status,
        )
        self.persist_current_item_state()
        if item.has_ocr_fields and self.ocr_checkbox.isChecked():
            if item.ocr_result is None:
                self.controller.run_ocr(item, parent=self)
                self.render_ocr_fields(item)
        elif item.has_ocr_fields:
            item.confirmed_data = {}
        save_result = self.controller.save_item(
            item,
            parent=self,
            run_ocr=self.ocr_checkbox.isChecked(),
        )
        logger.info(
            "Save Current result for index=%s file=%s status=%s error=%s",
            self.controller.selected_index,
            item.file_name,
            save_result.status,
            save_result.error_text,
        )
        self.after_save()
        if not self._is_closing and save_result.succeeded:
            self.go_to_next_item()

    def save_all(self, checked=False):
        current = self.controller.selected_item()
        if current is not None:
            self.persist_current_item_state()

        for index, item in enumerate(self.controller.items):
            self.controller.select(index)
            if item.status in {"saved", "skipped"}:
                continue
            if item.has_ocr_fields and self.ocr_checkbox.isChecked():
                if item.ocr_result is None:
                    self.controller.run_ocr(item, parent=self)
                if (
                    not item.confirmed_data
                    and item.ocr_result is not None
                    and not item.ocr_reviewed
                ):
                    item.confirmed_data = dict(
                        item.ocr_result.parsed_data or {}
                    )
            else:
                item.confirmed_data = {}
            self.controller.save_item(
                item,
                parent=self,
                run_ocr=self.ocr_checkbox.isChecked(),
            )

        self.after_save(show_summary=True)

    def after_save(self, show_summary=False):
        if self._is_closing:
            return
        logger.info(
            "Post-save refresh selected_index=%s selected_file=%s selected_status=%s",
            self.controller.selected_index,
            getattr(self.controller.selected_item(), "file_name", None),
            getattr(self.controller.selected_item(), "status", None),
        )
        self.refresh_queue()
        if (
            self.controller.selected_item() is not None
            and self._detail_widgets_available()
        ):
            self.load_detail()
        else:
            self.clear_detail()
        self.update_progress()
        if self.controller.items and (
            show_summary
            or all(
                item.status in {"saved", "skipped", "failed"}
                for item in self.controller.items
            )
        ):
            self.show_summary()

    def go_to_next_item(self, checked=False):
        total = len(self.controller.items)
        if total == 0:
            return

        current = self.queue_list.currentRow() if _widget_alive(self.queue_list) else -1
        if current < 0:
            current = self.controller.selected_index

        next_index = current + 1
        if next_index >= total:
            next_index = 0

        self._switch_to_item(next_index, persist_current=True)

    def update_progress(self):
        if self._is_closing:
            return
        total = len(self.controller.items)
        saved = sum(1 for item in self.controller.items if item.status == "saved")
        failed = sum(1 for item in self.controller.items if item.status == "failed")
        queued = sum(
            1
            for item in self.controller.items
            if item.status in {"pending", "ocr", "ready", "review"}
        )
        review = sum(1 for item in self.controller.items if item.status == "review")
        if total:
            self.progress_label.setText(
                f"{saved} saved, {failed} failed, {review} need review out of {total}"
            )
        else:
            self.progress_label.setText("No files selected.")

        self.saved_stat.setText(f"{saved} saved")
        self.failed_stat.setText(f"{failed} failed")
        self.pending_stat.setText(f"{queued} queued")

        self._set_progress_step(
            self.progress_step_files,
            "complete" if total else "idle",
            "Files added" if total else "Waiting",
        )
        if review:
            review_state = "active"
            review_text = f"{review} need review"
        elif total and queued:
            review_state = "complete"
            review_text = "Ready to save"
        else:
            review_state = "idle"
            review_text = "Not started"
        self._set_progress_step(
            self.progress_step_review,
            review_state,
            review_text,
        )

        if saved:
            save_state = "complete"
            save_text = f"{saved} saved"
        elif total:
            save_state = "idle"
            save_text = "Not started"
        else:
            save_state = "idle"
            save_text = "Waiting"
        self._set_progress_step(
            self.progress_step_save,
            save_state,
            save_text,
        )

    def _set_progress_step(self, frame, state, subtitle):
        frame.setProperty("state", state)
        labels = frame.findChildren(QLabel)
        if len(labels) >= 3:
            labels[2].setText(subtitle)
        _refresh_style(frame)

    def show_summary(self):
        if self._is_closing:
            return
        summary = self.controller.summary()
        missing_labels = [
            DOCUMENTS.get(key, {}).get("label", key)
            for key in summary["missing_documents"]
        ]
        try:
            if _widget_alive(self.status_label):
                self.status_label.setText(
                    f"{summary['uploaded']} uploaded, "
                    f"{summary['failed']} failed, "
                    f"{summary['skipped']} skipped."
                )
        except RuntimeError:
            pass

        self._summary_box = UploadSummaryDialog(
            updated_fields=summary["updated_fields"],
            missing_docs=missing_labels,
            parent=self,
            uploaded_count=summary["uploaded"],
            failed_count=summary["failed"],
            skipped_count=summary["skipped"],
        )
        self._summary_box.setWindowTitle("Upload Summary")
        self._summary_box.setModal(True)
        self._summary_box.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        self.add_files(files)
        event.acceptProposedAction()

    def closeEvent(self, event):
        self._is_closing = True
        self.close_document()
        super().closeEvent(event)

    def showEvent(self, event):
        self._refresh_fallback_backdrop()
        super().showEvent(event)

    def resizeEvent(self, event):
        self._sync_fallback_backdrop_geometry()
        super().resizeEvent(event)

    def _onDone(self, code):
        if FLUENT_DIALOG_AVAILABLE:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def accept(self):
        self._is_closing = True
        self.close_document()
        super().accept()

    def reject(self):
        self._is_closing = True
        self.close_document()
        super().reject()

    def saved_any(self):
        return self.controller.has_saved_items()
