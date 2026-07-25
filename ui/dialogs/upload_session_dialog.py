from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import fitz
from shiboken6 import isValid as shiboken_is_valid

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QDate,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from services.document_image_export_service import DocumentImageExportService
from services.document_service import DocumentService
from services.settings_service import SettingsService
from services.upload_pipeline import (
    OCR_MODE_SUBPROCESS,
    UploadPipelineResult,
    finalize_ocr_ingestion,
    get_ocr_service,
    ocr_runtime_mode,
    prepare_ocr_ingestion,
)
from ui.dialogs.document_rendering import (
    get_document_viewer_render_hints,
    render_document_pixmap,
    render_pdf_page,
)
from ui.foundation import (
    BodyLabel,
    SubtitleLabel,
    setup_dialog_shell,
    SmoothScrollDelegate,
    create_button,
    create_card,
    create_combo_box,
    create_date_picker,
    create_line_edit,
    create_list_widget,
    create_menu,
    create_plain_text_edit,
    create_scroll_area,
    FluentLoadingDialog,
    MaskDialogBase,
    show_message,
    tune_fluent_scrollable,
)
from utils.constants import (
    DOCUMENTS,
    MISSIONARY_DATE_FIELDS,
    WORKFLOW_STAGES,
    requires_fbi_document,
    visible_document_keys_for_missionary,
)
from utils.i18n import field_label, tr
from utils.logger import logger
from utils.passport_numbers import normalize_passport_number


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
PREVIEW_MIN_SCALE = 0.05
PREVIEW_MAX_SCALE = 8.0
APPOINTMENT_UPDATE_FIELDS = {
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
}


def supported_upload_files_from_paths(paths):
    files = []
    for raw_path in paths or []:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(
                str(child)
                for child in sorted(
                    path.rglob("*"),
                    key=lambda child_path: (
                        len(child_path.relative_to(path).parts),
                        str(child_path).lower(),
                    ),
                )
                if child.is_file()
                and child.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(str(path))
    return files


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
    document_type: str | None = None
    workflow_stage: str = "GENERAL"
    export_settings: dict = field(default_factory=dict)
    ocr_result: object = None
    confirmed_data: dict = field(default_factory=dict)
    ocr_reviewed: bool = False
    duplicate_action: str = "replace"
    status: str = "pending"
    error_text: str = ""
    notes: str = ""
    updated_fields: list = field(default_factory=list)
    saved_document_id: int | None = None
    prefilled_data: dict = field(default_factory=dict)

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


class UploadOcrWorker(QObject):
    finished = Signal(int, bool, str, object)

    def __init__(self, controller, index):
        super().__init__()
        self.controller = controller
        self.index = index

    def run(self):
        try:
            if self.index < 0 or self.index >= len(self.controller.items):
                raise IndexError("OCR item is no longer available.")
            item = self.controller.items[self.index]
            result = self.controller.run_ocr(
                item,
                parent=None,
            )
            self.finished.emit(self.index, True, "", result)
        except Exception as exc:
            logger.exception("Async upload OCR failed")
            try:
                item = self.controller.items[self.index]
                item.status = "failed"
                item.error_text = str(exc)
            except Exception:
                pass
            self.finished.emit(self.index, False, str(exc), None)


class UploadOcrWarmupWorker(QObject):
    finished = Signal(bool, str)

    def run(self):
        try:
            service = get_ocr_service(parent=None)
            if service is None:
                self.finished.emit(False, "OCR service unavailable.")
                return
            self.finished.emit(True, "")
        except Exception as exc:
            logger.exception("Upload OCR warm-up failed")
            self.finished.emit(False, str(exc))


class UploadSaveProgressDialog(MaskDialogBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saving Documents")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)

        self.surface = setup_dialog_shell(
            self,
            surface_width=420,
            surface_min_width=360,
            surface_min_height=170,
            shell_object_name="UploadSaveProgressDialog",
            surface_object_name="FluentLoadingSurface",
            use_masked_shell=True,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(14)
        self.surface.setLayout(layout)

        self.title_label = SubtitleLabel("Saving Documents")
        self.title_label.setObjectName("FluentLoadingTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.message_label = BodyLabel("Preparing documents...")
        self.message_label.setObjectName("FluentLoadingMessage")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.progress_track = QFrame(self.surface)
        self.progress_track.setObjectName("UploadSaveProgressTrack")
        self.progress_track.setFixedHeight(8)
        self.progress_track.setAttribute(Qt.WA_StyledBackground, True)
        self.progress_track.installEventFilter(self)
        self.progress_fill = QFrame(self.progress_track)
        self.progress_fill.setObjectName("UploadSaveProgressFill")
        self.progress_fill.setAttribute(Qt.WA_StyledBackground, True)
        self.progress_fill.setGeometry(0, 0, 0, 8)
        self.progress_fill.show()
        self._progress_fraction = 0.0
        self._progress_animation = QPropertyAnimation(
            self.progress_fill,
            b"geometry",
            self,
        )
        self._progress_animation.setDuration(180)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)
        layout.addWidget(self.progress_track)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "progress_track", None) and event.type() in {
            QEvent.Show,
            QEvent.Resize,
        }:
            QTimer.singleShot(0, self._set_progress_fill_width)
        return super().eventFilter(watched, event)

    def set_progress(self, completed, total, file_name=None):
        total = max(int(total or 0), 1)
        completed = min(max(int(completed or 0), 0), total)
        self._progress_fraction = completed / total
        QTimer.singleShot(0, self._animate_progress_fill)

        if file_name and completed < total:
            message = f"Saving documents ({completed} of {total})"
        else:
            message = f"Saved {completed} of {total}."
        self.message_label.setText(message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_progress_fill_width(animated=False)

    def _animate_progress_fill(self):
        if not _widget_alive(getattr(self, "progress_fill", None)):
            return

        target = self._progress_fill_geometry()
        if self._progress_animation.state() == QPropertyAnimation.Running:
            self._progress_animation.stop()
        self._progress_animation.setStartValue(self.progress_fill.geometry())
        self._progress_animation.setEndValue(target)
        self._progress_animation.start()

    def _set_progress_fill_width(self, animated=True):
        target = self._progress_fill_geometry()
        if animated:
            self._animate_progress_fill()
        else:
            self.progress_fill.setGeometry(target)

    def _progress_fill_geometry(self):
        track_width = max(self.progress_track.width(), 0)
        fill_width = int(track_width * self._progress_fraction)
        if self._progress_fraction > 0 and track_width > 0:
            fill_width = max(fill_width, 2)
        width = min(fill_width, track_width)
        height = max(self.progress_track.height(), 8)
        return QRect(0, 0, width, height)


class UploadPreviewGraphicsView(QGraphicsView):
    zoom_requested = Signal(float, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview_interactions_enabled = False
        self._is_middle_panning = False
        self._last_pan_pos = QPoint()
        self.scrollDelegate = None

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        if SmoothScrollDelegate is not None:
            self.scrollDelegate = SmoothScrollDelegate(self)
            tune_fluent_scrollable(self)

        self.viewport().installEventFilter(self)

    def set_preview_interactions_enabled(self, enabled):
        self._preview_interactions_enabled = enabled
        if not enabled:
            self._stop_middle_pan()

    def eventFilter(self, watched, event):
        if watched == self.viewport() and event.type() == QEvent.Type.Wheel:
            if self._handle_wheel_zoom(event):
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if not self._handle_wheel_zoom(event):
            super().wheelEvent(event)

    def _handle_wheel_zoom(self, event):
        if not self._preview_interactions_enabled:
            return False
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            return False

        factor = 1.25 if delta > 0 else 0.8
        self.zoom_requested.emit(factor, event.position().toPoint())
        event.accept()
        return True

    def mousePressEvent(self, event):
        if (
            self._preview_interactions_enabled
            and event.button() == Qt.MiddleButton
        ):
            self._is_middle_panning = True
            self._last_pan_pos = event.position().toPoint()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_middle_panning:
            current_pos = event.position().toPoint()
            delta = current_pos - self._last_pan_pos
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            self._last_pan_pos = current_pos
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_middle_panning and event.button() == Qt.MiddleButton:
            self._stop_middle_pan()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _stop_middle_pan(self):
        if not self._is_middle_panning:
            return
        self._is_middle_panning = False
        self.viewport().unsetCursor()


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
                workflow_stage="GENERAL",
                export_settings=self.default_export_settings(path),
            )
            self.items.append(item)
            known.add(normalized)
            added.append(item)

        if self.selected_index < 0 and self.items:
            self.selected_index = 0

        if added:
            logger.info(
                "UPLOAD_FILES_ADDED count=%s files=%s total=%s",
                len(added),
                [item.file_name for item in added],
                len(self.items),
            )

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
        if document_type == "FBI" and not requires_fbi_document(self.missionary):
            document_type = "OTHER"
        item = self.items[index]
        if document_type is None:
            normalized_type = None
        elif document_type in DOCUMENTS:
            normalized_type = document_type
        else:
            normalized_type = "OTHER"
        if normalized_type is None:
            workflow_stage = "GENERAL"
        else:
            workflow_stage = self.derive_stage(normalized_type)
        if item.document_type == normalized_type:
            return
        if document_type not in DOCUMENTS and document_type is not None:
            document_type = "OTHER"
        logger.info(
            "Queue item %s type change: %s -> %s",
            index,
            item.document_type,
            normalized_type,
        )
        item.document_type = normalized_type
        item.workflow_stage = workflow_stage
        item.ocr_result = None
        item.prefilled_data = self.missionary_defaults_for_document(
            normalized_type
        )
        item.confirmed_data = dict(item.prefilled_data)
        item.ocr_reviewed = False
        item.error_text = ""
        if item.status not in {"saved", "skipped"}:
            item.status = "pending"
        logger.info(
            "UPLOAD_DOCUMENT_TYPE_SET index=%s file=%s type=%s stage=%s prefilled_fields=%s",
            index,
            item.file_name,
            item.document_type,
            item.workflow_stage,
            sorted(item.prefilled_data.keys()),
        )

    @staticmethod
    def derive_stage(document_type):
        return DOCUMENTS.get(document_type, {}).get("stage") or "GENERAL"

    @staticmethod
    def default_export_settings(path):
        if Path(path).suffix.lower() == ".pdf":
            return {
                "page": 0,
                "pages": "all",
            }
        return {
            "page": 0,
        }

    def has_duplicate(self, item):
        return self.document_service.document_type_exists(
            self.missionary.id,
            item.document_type,
        )

    def missionary_defaults_for_document(self, document_type):
        defaults = {}
        for field in DOCUMENTS.get(
            document_type, {}
        ).get("ocr_fields", []):
            value = self._serialize_missionary_field(field)
            if not self._blank_confirmed_value(value):
                defaults[field] = value
        return defaults

    def _serialize_missionary_field(self, field):
        value = getattr(self.missionary, field, None)
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value).strip()

    @staticmethod
    def _blank_confirmed_value(value):
        if value is None:
            return True
        return str(value).strip() == ""

    def merge_ocr_data_into_confirmed(self, item):
        if item.ocr_result is None:
            return

        parsed_data = getattr(item.ocr_result, "parsed_data", None) or {}
        if not parsed_data:
            logger.info(
                "UPLOAD_OCR_MERGE_SKIPPED file=%s type=%s parsed_fields=[]",
                item.file_name,
                item.document_type,
            )
            return

        confirmed = dict(item.confirmed_data or {})
        filled_blank = []
        replaced_prefill = []
        preserved = []
        for field, value in parsed_data.items():
            confirmed_value = confirmed.get(field)
            if self._blank_confirmed_value(confirmed_value):
                confirmed[field] = value
                filled_blank.append(field)
            elif self._ocr_should_replace_prefill(
                item,
                field,
                confirmed_value,
            ):
                confirmed[field] = value
                replaced_prefill.append(field)
            else:
                preserved.append(field)
        item.confirmed_data = confirmed
        logger.info(
            "UPLOAD_OCR_MERGE_DONE file=%s type=%s parsed_fields=%s filled_blank=%s replaced_prefill=%s preserved=%s",
            item.file_name,
            item.document_type,
            sorted(parsed_data.keys()),
            sorted(filled_blank),
            sorted(replaced_prefill),
            sorted(preserved),
        )

    def _ocr_should_replace_prefill(self, item, field, confirmed_value):
        if item.document_type != "PASSPORT":
            return False

        prefilled_value = (item.prefilled_data or {}).get(field)
        if self._blank_confirmed_value(prefilled_value):
            return False

        return str(confirmed_value).strip() == str(prefilled_value).strip()

    def run_ocr(self, item, parent=None):
        ocr_fields = DOCUMENTS.get(item.document_type, {}).get(
            "ocr_fields", []
        )
        logger.info(
            "UPLOAD_OCR_REQUEST file=%s type=%s fields=%s status=%s",
            item.file_name,
            item.document_type,
            list(ocr_fields),
            item.status,
        )
        logger.info(
            "UPLOAD_OCR_RUNTIME file=%s type=%s mode=%s",
            item.file_name,
            item.document_type,
            ocr_runtime_mode(),
        )
        if not ocr_fields:
            item.ocr_result = None
            item.confirmed_data = {}
            item.ocr_reviewed = False
            item.status = "pending"
            logger.info(
                "UPLOAD_OCR_SKIPPED_NO_FIELDS file=%s type=%s",
                item.file_name,
                item.document_type,
            )
            return None

        item.status = "ocr"
        item.error_text = ""
        logger.info(
            "UPLOAD_OCR_PIPELINE_BEGIN file=%s type=%s export_settings=%s",
            item.file_name,
            item.document_type,
            item.export_settings,
        )
        item.ocr_result = prepare_ocr_ingestion(
            source_file=item.file_path,
            document_type=item.document_type,
            export_settings=item.export_settings,
            parent=parent,
            ocr_fields=ocr_fields,
            image_export_service=self.image_export_service,
        )
        logger.info(
            "UPLOAD_OCR_PIPELINE_DONE file=%s type=%s ocr_status=%s errors=%s parsed_fields=%s images=%s",
            item.file_name,
            item.document_type,
            getattr(item.ocr_result, "ocr_status", None),
            getattr(item.ocr_result, "errors", None),
            sorted((getattr(item.ocr_result, "parsed_data", None) or {}).keys()),
            [str(path) for path in getattr(item.ocr_result, "ocr_image_paths", [])],
        )
        self.merge_ocr_data_into_confirmed(item)
        item.ocr_reviewed = False

        self._apply_post_ocr_state(item)
        logger.info(
            "UPLOAD_OCR_STATE_APPLIED file=%s type=%s status=%s error=%s",
            item.file_name,
            item.document_type,
            item.status,
            item.error_text,
        )
        return item.ocr_result

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

    def save_item(self, item, parent=None, run_ocr=False):
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
            if document_type == "FBI" and not requires_fbi_document(self.missionary):
                raise ValueError(
                    "FBI documents are only available for USA or Canada missionaries"
                )

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
                save_result = finalize_ocr_ingestion(
                    missionary=self.missionary,
                    source_file=item.file_path,
                    document_type=document_type,
                    workflow_stage=workflow_stage,
                    pipeline_result=item.ocr_result,
                    confirmed_data=item.confirmed_data,
                    notes=item.notes,
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
                    notes=item.notes,
                )
                item.updated_fields = []

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


class UploadSessionDialog(MaskDialogBase):
    ocr_finished_on_ui = Signal(int, bool, str, object, str)
    appointment_dates_updated = Signal(int, list)

    def __init__(self, missionary, initial_files=None, parent=None):
        super().__init__(parent)
        main_window = getattr(parent, "main_window", None)
        self.settings_service = (
            getattr(main_window, "settings_service", None)
            or SettingsService()
        )
        self.controller = UploadSessionController(missionary)
        self.document = None
        self.current_pixmap = None
        self._preview_item = None
        self._preview_scale = 1.0
        self._preview_zoom_mode = "fit_window"
        self.field_edits = {}
        self.date_edits = {}
        self._detail_item_index = -1
        self._is_closing = False
        self._content_loading_dialog = None
        self._busy = False
        self._ocr_thread = None
        self._ocr_worker = None
        self._ocr_warmup_thread = None
        self._ocr_warmup_worker = None
        self._ocr_warmup_started = False
        self._pending_save_after_ocr = None
        self._saving_all = False
        self._save_all_index = 0
        self._save_all_total = 0
        self._save_all_completed = 0
        self._save_progress_dialog = None
        self._active_screen = None
        self._screen_changed_connected = False
        self._tracked_parent_window = None
        self._emitted_appointment_update_fields = set()
        self._responsive_geometry_timer = QTimer(self)
        self._responsive_geometry_timer.setSingleShot(True)
        self._responsive_geometry_timer.setInterval(80)
        self._responsive_geometry_timer.timeout.connect(
            self._apply_responsive_shell_geometry
        )
        self.ocr_finished_on_ui.connect(
            self._handle_ocr_finished,
            Qt.ConnectionType.QueuedConnection,
        )

        self.setWindowTitle("Upload Documents")
        self.setAcceptDrops(True)

        self._configure_shell()

        self.setup_ui()
        if initial_files:
            self.add_files(supported_upload_files_from_paths(initial_files))

    def _configure_shell(self):
        self.surface = setup_dialog_shell(
            self,
            shell_object_name="UploadWorkspaceDialog",
            surface_object_name="UploadWorkspaceSurface",
            use_masked_shell=True,
            fit_to_content=False,
        )
        self.surface.setMinimumSize(0, 0)

    def _start_ocr_warmup(self):
        if self._is_closing or self._ocr_warmup_started:
            return
        self._ocr_warmup_started = True

        if ocr_runtime_mode() == OCR_MODE_SUBPROCESS:
            logger.info("UPLOAD_OCR_WARMUP_SKIPPED mode=subprocess")
            return

        logger.info("UPLOAD_OCR_WARMUP_BEGIN")
        self._ocr_warmup_thread = QThread()
        self._ocr_warmup_worker = UploadOcrWarmupWorker()
        self._ocr_warmup_worker.moveToThread(self._ocr_warmup_thread)
        self._ocr_warmup_thread.started.connect(self._ocr_warmup_worker.run)
        self._ocr_warmup_worker.finished.connect(
            self._handle_ocr_warmup_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._ocr_warmup_worker.finished.connect(self._ocr_warmup_thread.quit)
        self._ocr_warmup_worker.finished.connect(
            self._ocr_warmup_worker.deleteLater
        )
        self._ocr_warmup_thread.finished.connect(
            self._ocr_warmup_thread.deleteLater
        )
        self._ocr_warmup_thread.finished.connect(
            lambda thread=self._ocr_warmup_thread: (
                self._clear_ocr_warmup_refs(thread)
            )
        )

        try:
            self._ocr_warmup_thread.start(QThread.Priority.LowPriority)
        except TypeError:
            self._ocr_warmup_thread.start()

    @Slot(bool, str)
    def _handle_ocr_warmup_finished(self, ok, error):
        if ok:
            logger.info("UPLOAD_OCR_WARMUP_DONE")
        else:
            logger.info("UPLOAD_OCR_WARMUP_FAILED error=%s", error)

    def _clear_ocr_warmup_refs(self, thread):
        if self._ocr_warmup_thread is thread:
            self._ocr_warmup_thread = None
            self._ocr_warmup_worker = None

    def _ensure_screen_tracking(self):
        window_handle = self.windowHandle()
        if window_handle is not None and not self._screen_changed_connected:
            window_handle.screenChanged.connect(self._on_screen_changed)
            self._screen_changed_connected = True

        parent_window = self._parent_window()
        tracked_parent = getattr(self, "_tracked_parent_window", None)
        if parent_window is not tracked_parent:
            if _widget_alive(tracked_parent):
                tracked_parent.removeEventFilter(self)
            self._tracked_parent_window = parent_window
            if _widget_alive(parent_window):
                parent_window.installEventFilter(self)

        self._bind_active_screen(self._responsive_screen())

    def _parent_window(self):
        parent = self.parentWidget()
        if parent is None:
            return None
        return parent.window()

    def _parent_container(self):
        return self.parentWidget()

    def _screen_for_widget(self, widget):
        if not _widget_alive(widget):
            return None

        rect = widget.rect()
        if rect.isValid() and not rect.isEmpty():
            screen = QApplication.screenAt(
                widget.mapToGlobal(rect.center())
            )
            if screen is not None:
                return screen

        window_handle = widget.windowHandle()
        if window_handle is not None:
            return window_handle.screen()
        return None

    def _responsive_screen(self):
        screen = self._screen_for_widget(self._parent_container())
        if screen is not None:
            return screen

        screen = self._screen_for_widget(self._parent_window())
        if screen is not None:
            return screen

        screen = self._screen_for_widget(self)
        if screen is not None:
            return screen

        window_handle = self.windowHandle()
        if window_handle is not None:
            return window_handle.screen()
        return QApplication.primaryScreen()

    def _bind_active_screen(self, screen):
        current = getattr(self, "_active_screen", None)
        if current is screen:
            return

        if _widget_alive(current):
            try:
                current.availableGeometryChanged.disconnect(
                    self._on_screen_geometry_changed
                )
            except (TypeError, RuntimeError):
                pass

        self._active_screen = screen

        if _widget_alive(screen):
            try:
                screen.availableGeometryChanged.connect(
                    self._on_screen_geometry_changed
                )
            except (TypeError, RuntimeError):
                pass

    def _on_screen_changed(self, screen):
        self._bind_active_screen(screen)
        self._schedule_responsive_shell_geometry()

    def _on_screen_geometry_changed(self, geometry):
        _ = geometry
        self._schedule_responsive_shell_geometry()

    def _schedule_responsive_shell_geometry(self):
        timer = getattr(self, "_responsive_geometry_timer", None)
        if timer is None:
            return
        timer.start()

    def _apply_responsive_shell_geometry(self):
        surface = getattr(self, "surface", None)
        splitter = getattr(self, "splitter", None)
        if not _widget_alive(surface):
            return

        self._ensure_screen_tracking()
        screen = self._responsive_screen()
        if screen is None:
            return

        available = screen.availableGeometry()
        parent_container = self._parent_container()
        container_size = (
            parent_container.size()
            if _widget_alive(parent_container)
            else QSize(available.width(), available.height())
        )
        horizontal_margin = 96
        vertical_margin = 48
        container_width = min(available.width(), container_size.width())
        container_height = min(available.height(), container_size.height())
        max_width = max(1, container_width - horizontal_margin)
        max_height = max(1, container_height - vertical_margin)

        preferred_width = max(1120, int(container_width * 0.82))
        preferred_height = max(640, int(container_height * 0.84))
        target_width = min(preferred_width, max_width)
        target_height = min(preferred_height, max_height)

        if _widget_alive(parent_container):
            self.setMaximumSize(16777215, 16777215)
            self.resize(container_size)
        else:
            self.setMaximumSize(
                target_width + horizontal_margin,
                target_height + vertical_margin,
            )
            self.resize(
                target_width + horizontal_margin,
                target_height + vertical_margin,
            )

        self.setMinimumSize(0, 0)
        surface.setFixedSize(target_width, target_height)

        if _widget_alive(splitter):
            splitter.setSizes(
                self._responsive_splitter_sizes(target_width)
            )

    def _responsive_splitter_sizes(self, total_width):
        if total_width <= 0:
            return [240, 320, 480]

        if total_width < 1100:
            ratios = (0.22, 0.28, 0.50)
        elif total_width < 1350:
            ratios = (0.23, 0.30, 0.47)
        else:
            ratios = (0.24, 0.31, 0.45)

        sizes = [max(1, int(total_width * ratio)) for ratio in ratios]
        remainder = total_width - sum(sizes)
        sizes[-1] = max(1, sizes[-1] + remainder)
        return sizes

    def _surface_widget(self):
        return getattr(self, "surface", None)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_tracked_parent_window", None):
            if event.type() in {
                QEvent.Type.Move,
                QEvent.Type.Resize,
                QEvent.Type.Show,
            }:
                self._ensure_screen_tracking()
                self._schedule_responsive_shell_geometry()
        return super().eventFilter(watched, event)

    def setup_ui(self):
        root = self._build_shell()
        self._build_queue_panel()
        self._build_details_panel()
        self._build_preview_panel()
        self._build_progress_panel(root)
        self._build_footer(root)
        self._ensure_screen_tracking()
        self._apply_responsive_shell_geometry()
        self._set_page_controls_visible(False)
        self._set_preview_controls_enabled(False)
        self._set_busy(False)
        self.clear_detail()
        self.update_progress()
        self._update_action_states()

    def _build_shell(self):
        surface = self.surface
        root_target = surface

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root_target.setLayout(root)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setObjectName("UploadWorkspaceSplitter")
        root.addWidget(self.splitter, stretch=1)
        return root

    def _build_queue_panel(self):
        self.left_panel = create_card(object_name="UploadSurfaceCard")
        self.left_panel.setObjectName("UploadSurfaceCard")
        self.left_panel.setAttribute(Qt.WA_StyledBackground, True)
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(18, 16, 18, 16)
        left_layout.setSpacing(12)
        self.left_panel.setLayout(left_layout)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("UploadDropZone")
        self.drop_zone.setAttribute(Qt.WA_StyledBackground, True)
        drop_layout = QVBoxLayout()
        drop_layout.setContentsMargins(18, 20, 18, 20)
        drop_layout.setSpacing(8)
        self.drop_zone.setLayout(drop_layout)

        drop_icon = QLabel(tr("upload_drop_icon"))
        drop_icon.setObjectName("UploadDropIcon")
        drop_icon.setAlignment(Qt.AlignCenter)
        drop_copy = QLabel(tr("upload_drop_title"))
        drop_copy.setObjectName("UploadDropTitle")
        drop_copy.setAlignment(Qt.AlignCenter)
        drop_hint = QLabel(tr("upload_drop_hint"))
        drop_hint.setObjectName("MiniMutedText")
        drop_hint.setAlignment(Qt.AlignCenter)
        browse_btn = create_button(tr("upload_browse"), "secondary")
        browse_menu = create_menu("", browse_btn)
        files_action = QAction(tr("upload_browse_files"), browse_menu)
        folder_action = QAction(tr("upload_browse_folder"), browse_menu)
        browse_menu.addAction(files_action)
        browse_menu.addAction(folder_action)
        files_action.triggered.connect(self.pick_files)
        folder_action.triggered.connect(self.pick_folder)
        browse_btn.setMenu(browse_menu)
        drop_layout.addWidget(drop_icon)
        drop_layout.addWidget(drop_copy)
        drop_layout.addWidget(drop_hint)
        drop_layout.addWidget(browse_btn, alignment=Qt.AlignCenter)
        left_layout.addWidget(self.drop_zone)

        self.queue_list = create_list_widget()
        self.queue_list.setObjectName("UploadQueueList")
        self.queue_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.queue_list.currentRowChanged.connect(self.select_item)
        self.queue_list.setSpacing(0)
        left_layout.addWidget(self.queue_list, stretch=1)

        self.queue_empty_label = QLabel(tr("upload_queue_empty"))
        self.queue_empty_label.setObjectName("UploadEmptyState")
        self.queue_empty_label.setAlignment(Qt.AlignCenter)
        self.queue_empty_label.setWordWrap(True)
        left_layout.addWidget(self.queue_empty_label, stretch=1)

        queue_footer = QHBoxLayout()
        queue_footer.setSpacing(10)
        queue_note = QLabel(tr("upload_queue_note"))
        queue_note.setObjectName("SubtleText")
        self.remove_btn = create_button(tr("upload_remove"), "secondary")
        self.remove_btn.clicked.connect(self.remove_selected)
        queue_footer.addWidget(queue_note, stretch=1)
        queue_footer.addWidget(self.remove_btn)
        left_layout.addLayout(queue_footer)
        self.splitter.addWidget(self.left_panel)

    def _build_details_panel(self):
        self.middle_panel = create_card(object_name="UploadSurfaceCard")
        self.middle_panel.setObjectName("UploadSurfaceCard")
        self.middle_panel.setAttribute(Qt.WA_StyledBackground, True)
        middle_layout = QVBoxLayout()
        middle_layout.setContentsMargins(18, 16, 18, 16)
        middle_layout.setSpacing(12)
        self.middle_panel.setLayout(middle_layout)

        details_title = QLabel("Document Details")
        details_title.setObjectName("PanelTitle")
        middle_layout.addWidget(details_title)

        summary_form = QFormLayout()
        summary_form.setSpacing(10)
        summary_form.setContentsMargins(0, 0, 0, 0)

        self.type_combo = create_combo_box()
        self.type_combo.setObjectName("UploadFieldInput")
        self.type_combo.addItem("Select document type...", None)
        for key in visible_document_keys_for_missionary(
            self.controller.missionary
        ):
            config = DOCUMENTS[key]
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
        self.notes_editor = create_plain_text_edit()
        self.notes_editor.setFixedHeight(76)
        summary_form.addRow("Notes", self.notes_editor)
        middle_layout.addLayout(summary_form)

        ocr_tools = QHBoxLayout()
        ocr_tools.setSpacing(10)
        self.ocr_status_label = QLabel("")
        self.ocr_status_label.setObjectName("OcrStatusBanner")
        self.ocr_status_label.setProperty("status", "skipped")
        self.ocr_status_label.setWordWrap(True)
        self.ocr_status_label.hide()
        self.autodetect_btn = create_button("AI Read", "secondary")
        self.autodetect_btn.clicked.connect(self.run_ocr_for_selected)
        ocr_tools.addStretch()
        ocr_tools.addWidget(self.autodetect_btn)
        middle_layout.addLayout(ocr_tools)

        self.duplicate_warning = QLabel("")
        self.duplicate_warning.setObjectName("OcrStatusBanner")
        self.duplicate_warning.setProperty("status", "partial")
        self.duplicate_warning.setWordWrap(True)
        self.duplicate_warning.hide()
        middle_layout.addWidget(self.duplicate_warning)

        self.ocr_form_widget = QWidget()
        self.ocr_form = QFormLayout()
        self.ocr_form.setSpacing(10)
        self.ocr_form_widget.setLayout(self.ocr_form)
        scroll = create_scroll_area(single_direction=True)
        scroll.setWidget(self.ocr_form_widget)
        scroll.setObjectName("UploadDetailsScroll")
        middle_layout.addWidget(scroll, stretch=1)

        self.details_empty_label = QLabel("Select a file to edit document details.")
        self.details_empty_label.setObjectName("UploadEmptyState")
        self.details_empty_label.setAlignment(Qt.AlignCenter)
        self.details_empty_label.setWordWrap(True)
        middle_layout.addWidget(self.details_empty_label, stretch=1)

        self.splitter.addWidget(self.middle_panel)

    def _auto_ocr_enabled(self):
        service = getattr(self, "settings_service", None)
        if service is None:
            return True
        return service.get_upload_auto_ocr_enabled()

    def _build_preview_panel(self):
        self.right_panel = create_card(object_name="UploadSurfaceCard")
        self.right_panel.setObjectName("UploadSurfaceCard")
        self.right_panel.setAttribute(Qt.WA_StyledBackground, True)
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(18, 16, 18, 16)
        right_layout.setSpacing(12)
        self.right_panel.setLayout(right_layout)

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

        right_layout.addLayout(preview_header)

        self.preview_toolbar = QFrame()
        self.preview_toolbar.setObjectName("UploadPreviewToolbar")
        self.preview_toolbar.setAttribute(Qt.WA_StyledBackground, True)
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(14, 12, 14, 12)
        toolbar_layout.setSpacing(10)
        self.preview_toolbar.setLayout(toolbar_layout)

        page_group = QHBoxLayout()
        page_group.setContentsMargins(0, 0, 0, 0)
        page_group.setSpacing(8)
        self.page_label = QLabel("Page")
        self.page_label.setObjectName("MutedText")
        self.page_combo = create_combo_box(object_name="UploadPageInput")
        self.page_combo.setMinimumWidth(152)
        self.page_combo.currentIndexChanged.connect(self.change_page)
        self.page_prev_btn = self._make_preview_button(
            "<",
            self.go_to_previous_page,
            width=34,
            tooltip="Previous page",
        )
        self.page_next_btn = self._make_preview_button(
            ">",
            self.go_to_next_page,
            width=34,
            tooltip="Next page",
        )
        page_group.addWidget(self.page_label)
        page_group.addWidget(self.page_combo)
        page_group.addWidget(self.page_prev_btn)
        page_group.addWidget(self.page_next_btn)
        toolbar_layout.addLayout(page_group)
        toolbar_layout.addStretch()

        zoom_group = QHBoxLayout()
        zoom_group.setContentsMargins(0, 0, 0, 0)
        zoom_group.setSpacing(8)
        self.preview_zoom_label = QLabel("Fit 100%")
        self.preview_zoom_label.setObjectName("UploadZoomBadge")
        self.preview_zoom_label.setAlignment(Qt.AlignCenter)
        self.preview_zoom_out_btn = self._make_preview_button(
            "-",
            self.zoom_out_preview,
            width=34,
            tooltip="Zoom out",
        )
        self.preview_zoom_in_btn = self._make_preview_button(
            "+",
            self.zoom_in_preview,
            width=34,
            tooltip="Zoom in",
        )
        self.preview_fit_width_btn = self._make_preview_button(
            "Width",
            self.fit_preview_width,
            tooltip="Fit to width",
        )
        self.preview_fit_window_btn = self._make_preview_button(
            "Fit",
            self.fit_preview_window,
            tooltip="Fit whole page",
        )
        self.preview_reset_btn = self._make_preview_button(
            "100%",
            self.reset_preview_zoom,
            tooltip="Actual size",
        )
        zoom_group.addWidget(self.preview_zoom_label)
        zoom_group.addWidget(self.preview_zoom_out_btn)
        zoom_group.addWidget(self.preview_zoom_in_btn)
        zoom_group.addWidget(self.preview_fit_width_btn)
        zoom_group.addWidget(self.preview_fit_window_btn)
        zoom_group.addWidget(self.preview_reset_btn)
        toolbar_layout.addLayout(zoom_group)

        right_layout.addWidget(self.preview_toolbar)

        self.scene = QGraphicsScene()
        self.graphics_view = UploadPreviewGraphicsView()
        self.graphics_view.setScene(self.scene)
        self.graphics_view.setAlignment(Qt.AlignCenter)
        self.graphics_view.setRenderHints(
            self.graphics_view.renderHints()
            | get_document_viewer_render_hints()
        )
        self.graphics_view.setFrameShape(QFrame.NoFrame)
        self.graphics_view.setBackgroundBrush(Qt.GlobalColor.white)
        self.graphics_view.setObjectName("UploadPreviewCanvas")
        self.graphics_view.zoom_requested.connect(self._zoom_preview_by)
        right_layout.addWidget(self.graphics_view, stretch=1)

        self.preview_empty_label = QLabel("No preview selected.")
        self.preview_empty_label.setObjectName("UploadEmptyState")
        self.preview_empty_label.setAlignment(Qt.AlignCenter)
        self.preview_empty_label.setWordWrap(True)
        right_layout.addWidget(self.preview_empty_label, stretch=1)

        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 2)

    def _build_progress_panel(self, root):
        self.progress_card = create_card(object_name="UploadSurfaceCard")
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
        root.addWidget(self.progress_card)

    def _build_footer(self, root):
        self.footer = QFrame()
        self.footer.setObjectName("UploadWorkspaceFooter")
        self.footer.setAttribute(Qt.WA_StyledBackground, True)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(18, 12, 18, 12)
        footer_layout.setSpacing(12)
        self.footer.setLayout(footer_layout)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("SubtleText")
        self.cancel_btn = create_button("Cancel", "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        self.next_btn = create_button("Next", "secondary")
        self.next_btn.clicked.connect(self.go_to_next_item)
        self.save_all_btn = create_button("Save All", "success")
        self.save_all_btn.clicked.connect(self.save_all)

        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.cancel_btn)
        footer_layout.addWidget(self.next_btn)
        footer_layout.addWidget(self.save_all_btn)
        root.addWidget(self.footer)

    def _make_preview_button(self, text, slot, width=None, tooltip=""):
        button = create_button(text, "subtle", fixed_height=28)
        button.setObjectName("UploadNavButton")
        if width is not None:
            button.setFixedWidth(width)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(slot)
        return button

    @staticmethod
    def _ocr_loading_messages():
        return [
            tr("ocr_loading_reading_document"),
            tr("ocr_loading_appointment_details"),
            tr("ocr_loading_saving_extracted_data"),
            tr("ocr_loading_large_pdf_hint"),
        ]

    def _set_busy(
        self,
        busy,
        message="",
        content_loading_overlay=False,
        content_loading_messages=None,
    ):
        self._busy = busy
        if _widget_alive(getattr(self, "status_label", None)) and message:
            self.status_label.setText(message)
        if content_loading_overlay and busy:
            self._show_content_loading_overlay(
                message,
                content_loading_messages,
            )
        elif not busy:
            self._hide_content_loading_overlay()
        if _widget_alive(getattr(self, "progress_step_files", None)):
            self.update_progress()
        self._update_action_states()

    def _show_content_loading_overlay(self, message, rotating_messages=None):
        dialog = self._ensure_content_loading_dialog()
        if dialog is None:
            return
        dialog.show_busy(
            message or tr("ocr_loading_reading_document"),
            rotating_messages=rotating_messages,
        )

    def _hide_content_loading_overlay(self):
        dialog = self._content_loading_dialog
        if dialog is not None:
            dialog.hide_busy()

    def _ensure_content_loading_dialog(self):
        dialog = self._content_loading_dialog
        if dialog is None:
            dialog = FluentLoadingDialog(self, title="Reading document...")
            self._content_loading_dialog = dialog
        return dialog

    def _set_widget_enabled(self, widget_name, enabled):
        widget = getattr(self, widget_name, None)
        if _widget_alive(widget):
            widget.setEnabled(enabled)

    def _selected_item_can_save(self):
        item = self.controller.selected_item()
        if item is None or item.status in {"saved", "skipped", "ocr"}:
            return False
        return item.duplicate_action == "skip" or bool(item.document_type)

    def _item_can_autodetect(self, item):
        return bool(
            item
            and item.document_type
            and item.has_ocr_fields
            and item.status not in {"saved", "skipped", "ocr"}
        )

    def _has_unsaved_valid_items(self):
        return any(
            item.status not in {"saved", "skipped", "ocr"}
            and (item.duplicate_action == "skip" or bool(item.document_type))
            for item in self.controller.items
        )

    def _update_action_states(self):
        if self._is_closing:
            return

        item = self.controller.selected_item()
        has_items = bool(self.controller.items)
        has_selection = item is not None
        can_edit = has_selection and not self._busy
        can_autodetect = can_edit and self._item_can_autodetect(item)
        for name in (
            "type_combo",
            "stage_combo",
            "duplicate_combo",
        ):
            self._set_widget_enabled(name, can_edit)

        self._set_widget_enabled("remove_btn", can_edit)
        self._set_widget_enabled("next_btn", has_items and not self._busy)
        self._set_widget_enabled("autodetect_btn", can_autodetect)
        self._set_widget_enabled(
            "save_all_btn",
            not self._busy and self._has_unsaved_valid_items(),
        )

        if _widget_alive(getattr(self, "queue_list", None)):
            self.queue_list.setVisible(has_items)
            self.queue_list.setEnabled(not self._busy)
        if _widget_alive(getattr(self, "queue_empty_label", None)):
            self.queue_empty_label.setVisible(not has_items)
        if _widget_alive(getattr(self, "details_empty_label", None)):
            self.details_empty_label.setVisible(not has_selection)
        if _widget_alive(getattr(self, "ocr_form_widget", None)):
            self.ocr_form_widget.setVisible(has_selection)
        if _widget_alive(getattr(self, "graphics_view", None)):
            self.graphics_view.setVisible(self._preview_item is not None)
        if _widget_alive(getattr(self, "preview_empty_label", None)):
            self.preview_empty_label.setVisible(self._preview_item is None)
        self._set_preview_controls_enabled(
            self._preview_item is not None and not self._busy
        )
        for name in ("page_combo", "page_prev_btn", "page_next_btn"):
            self._set_widget_enabled(
                name,
                self._preview_item is not None and not self._busy,
            )

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

        files = supported_upload_files_from_paths([folder])
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
            self._switch_to_item(
                self.controller.selected_index,
                persist_current=False,
            )
        elif self.controller.items:
            self._set_queue_row(0)
        if _widget_alive(self.status_label):
            if added:
                noun = "file" if len(added) == 1 else "files"
                self.status_label.setText(f"Added {len(added)} {noun}.")
            elif files:
                self.status_label.setText("No new supported files were added.")
        self.update_progress()
        self._update_action_states()

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
        self._update_action_states()

    def refresh_queue(self):
        if self._is_closing or not _widget_alive(self.queue_list):
            return
        current = self.queue_list.currentRow()
        if current < 0:
            current = self.controller.selected_index
        self.queue_list.blockSignals(True)
        self.queue_list.clear()
        for item in self.controller.items:
            list_item = QListWidgetItem()
            prefix = "PDF" if item.file_name.lower().endswith(".pdf") else "IMG"
            document_type = self.document_type_text(item)
            list_item.setText(
                f"{prefix}  {item.file_name}  |  {document_type}  |  {item.file_size_text}"
            )
            list_item.setToolTip(
                f"{item.file_name}\n{document_type}\n{item.file_size_text}"
            )
            self.queue_list.addItem(list_item)
        if 0 <= current < self.queue_list.count():
            self.queue_list.setCurrentRow(current)
        self.queue_list.blockSignals(False)
        self._update_action_states()

    def _set_queue_row(self, index):
        if not _widget_alive(self.queue_list):
            return
        self.queue_list.blockSignals(True)
        try:
            self.queue_list.setCurrentRow(index)
        finally:
            self.queue_list.blockSignals(False)

    def _detail_widgets_available(self):
        if self._is_closing:
            return False
        required = [
            self.type_combo,
            self.stage_combo,
            self.duplicate_combo,
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
            self._update_action_states()

    @staticmethod
    def document_type_text(item):
        if not item.document_type:
            return "Select document type"
        return DOCUMENTS.get(item.document_type, {}).get(
            "label", item.document_type
        )

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
            if idx < 0:
                idx = 0
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
        if _widget_alive(getattr(self, "notes_editor", None)):
            self.notes_editor.blockSignals(True)
            self.notes_editor.setPlainText(item.notes or "")
            self.notes_editor.blockSignals(False)
        self.load_preview(item)
        self.render_ocr_fields(item)
        self.update_duplicate_warning(item)
        if _widget_alive(self.status_label):
            self.status_label.setText(item.error_text or "Ready.")
        if _widget_alive(self.preview_name_label):
            self.preview_name_label.setText(item.file_name)
        self._update_preview_meta_label(item)
        if _widget_alive(self.preview_status_badge):
            self.preview_status_badge.setText(self.status_text(item))
            self.preview_status_badge.setProperty("status", item.status)
            _refresh_style(self.preview_status_badge)
        self._detail_item_index = self.controller.selected_index
        self._update_action_states()

    def clear_detail(self):
        self._detail_item_index = -1
        self.current_pixmap = None
        self._preview_item = None
        self._preview_scale = 1.0
        self._preview_zoom_mode = "fit_window"
        try:
            if _widget_alive(self.scene):
                self.scene.clear()
        except RuntimeError:
            pass
        try:
            if _widget_alive(self.page_combo):
                self.page_combo.blockSignals(True)
                self.page_combo.clear()
                self.page_combo.blockSignals(False)
            self._set_page_controls_visible(False)
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
            if _widget_alive(self.preview_status_badge):
                self.preview_status_badge.setText("Pending")
                self.preview_status_badge.setProperty("status", "pending")
                _refresh_style(self.preview_status_badge)
            if _widget_alive(getattr(self, "notes_editor", None)):
                self.notes_editor.blockSignals(True)
                self.notes_editor.clear()
                self.notes_editor.blockSignals(False)
        except RuntimeError:
            pass
        self._update_preview_meta_label(None)
        self._update_preview_zoom_label()
        self.apply_ocr_banner("skipped", "")
        try:
            if _widget_alive(self.status_label):
                self.status_label.setText("Add files to begin.")
        except RuntimeError:
            pass
        self._update_action_states()

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
        should_run_ocr = (
            item.document_type
            and item.has_ocr_fields
            and self._auto_ocr_enabled()
        )
        self._refresh_detail_after_type_change(item)
        self.refresh_queue()
        self.update_progress()
        self._update_action_states()
        if should_run_ocr:
            logger.info(
                "TYPE_CHANGE_AUTO_OCR_SCHEDULED index=%s file=%s type=%s",
                current_index,
                item.file_name,
                item.document_type,
            )
            QTimer.singleShot(
                0,
                lambda index=current_index, doc_type=item.document_type: (
                    self._run_auto_ocr_after_type_change(index, doc_type)
                ),
            )

    def _refresh_detail_after_type_change(self, item):
        if item is None or self._is_closing:
            return
        logger.info(
            "TYPE_CHANGE_UI_REFRESH_BEGIN file=%s type=%s status=%s",
            item.file_name,
            item.document_type,
            item.status,
        )
        if _widget_alive(self.stage_combo):
            stage_idx = self.stage_combo.findData(item.workflow_stage)
            if stage_idx >= 0:
                self.stage_combo.blockSignals(True)
                try:
                    self.stage_combo.setCurrentIndex(stage_idx)
                finally:
                    self.stage_combo.blockSignals(False)
        self.render_ocr_fields(item)
        self.update_duplicate_warning(item)
        self._refresh_selected_item_labels(item)
        logger.info(
            "TYPE_CHANGE_UI_REFRESH_DONE file=%s type=%s status=%s",
            item.file_name,
            item.document_type,
            item.status,
        )

    def _refresh_selected_item_labels(self, item):
        if _widget_alive(self.status_label):
            self.status_label.setText(item.error_text or "Ready.")
        if _widget_alive(self.preview_meta_label):
            self._update_preview_meta_label(item)
        if _widget_alive(self.preview_status_badge):
            self.preview_status_badge.setText(self.status_text(item))
            self.preview_status_badge.setProperty("status", item.status)
            _refresh_style(self.preview_status_badge)

    def _run_auto_ocr_after_type_change(self, index, document_type):
        if self._is_closing:
            return
        if self._busy:
            return
        if index < 0 or index >= len(self.controller.items):
            return
        item = self.controller.items[index]
        if item.document_type != document_type:
            logger.info(
                "TYPE_CHANGE_AUTO_OCR_CANCELLED index=%s expected_type=%s current_type=%s",
                index,
                document_type,
                item.document_type,
            )
            return
        logger.info(
            "TYPE_CHANGE_AUTO_OCR_BEGIN index=%s file=%s type=%s",
            index,
            item.file_name,
            item.document_type,
        )
        self._run_ocr_async(index, reason="auto")

    def _run_ocr_async(self, index, reason="manual", after=None):
        if self._busy or self._is_closing:
            return False
        if index < 0 or index >= len(self.controller.items):
            return False

        item = self.controller.items[index]
        if not self._item_can_autodetect(item):
            return False

        self.persist_current_editor_settings(item)
        item.status = "ocr"
        item.error_text = ""
        self._pending_save_after_ocr = after
        self.refresh_queue()
        self.update_progress()
        self._refresh_selected_item_labels(item)
        self.apply_ocr_banner("skipped", "Reading fields...")

        self._ocr_thread = QThread(self)
        self._ocr_worker = UploadOcrWorker(self.controller, index)
        self._ocr_worker.moveToThread(self._ocr_thread)
        self._ocr_thread.started.connect(self._ocr_worker.run)
        self._ocr_worker.finished.connect(
            lambda finished_index, ok, error, result, reason=reason: (
                self.ocr_finished_on_ui.emit(
                    finished_index,
                    ok,
                    error,
                    result,
                    reason,
                )
            )
        )
        self._ocr_worker.finished.connect(self._ocr_thread.quit)
        self._ocr_worker.finished.connect(self._ocr_worker.deleteLater)
        self._ocr_thread.finished.connect(self._ocr_thread.deleteLater)
        self._ocr_thread.finished.connect(
            lambda thread=self._ocr_thread: self._clear_ocr_worker_refs(thread)
        )

        self._set_busy(
            True,
            f"Reading fields from {item.file_name}...",
            content_loading_overlay=True,
            content_loading_messages=self._ocr_loading_messages(),
        )
        self._ocr_thread.start()
        return True

    def _clear_ocr_worker_refs(self, thread):
        if self._ocr_thread is thread:
            self._ocr_thread = None
            self._ocr_worker = None

    @Slot(int, bool, str, object, str)
    def _handle_ocr_finished(self, index, ok, error, result, reason):
        if self._is_closing:
            return
        item = (
            self.controller.items[index]
            if 0 <= index < len(self.controller.items)
            else None
        )
        pending = self._pending_save_after_ocr
        self._pending_save_after_ocr = None
        self._set_busy(False)

        result_type = getattr(result, "document_type", None)
        if (
            item is not None
            and result_type
            and item.document_type != result_type
        ):
            logger.info(
                "ASYNC_UPLOAD_OCR_STALE_RESULT reason=%s index=%s file=%s result_type=%s current_type=%s",
                reason,
                index,
                item.file_name,
                result_type,
                item.document_type,
            )
            self.refresh_queue()
            self.update_progress()
            self._update_action_states()
            return

        if item is not None:
            logger.info(
                "ASYNC_UPLOAD_OCR_DONE reason=%s index=%s file=%s ok=%s status=%s error=%s",
                reason,
                index,
                item.file_name,
                ok,
                item.status,
                error or item.error_text,
            )
            if self.controller.selected_index == index:
                self.render_ocr_fields(item)
                self.update_duplicate_warning(item)
                self._refresh_selected_item_labels(item)
            self.refresh_queue()
            self.update_progress()
            if _widget_alive(self.status_label):
                if ok:
                    self.status_label.setText(item.error_text or "Reading complete.")
                else:
                    self.status_label.setText(error or "Reading failed.")

        if pending == "all":
            self._save_all_next()

        self._update_action_states()

    def stage_changed(self, checked=False):
        item = self.controller.selected_item()
        if item is None or not _widget_alive(self.stage_combo):
            return
        item.workflow_stage = self.stage_combo.currentData() or "GENERAL"
        self.refresh_queue()
        self._update_action_states()

    def duplicate_changed(self, checked=False):
        item = self.controller.selected_item()
        if item is not None:
            item.duplicate_action = self.duplicate_combo.currentData()
        self._update_action_states()

    def _sync_current_ocr_data(self):
        if self._is_closing:
            return
        item = self.controller.selected_item()
        if item is not None and item.has_ocr_fields:
            self.collect_ocr_data(item)

    def update_duplicate_warning(self, item):
        if not _widget_alive(self.duplicate_warning):
            return
        if not item.document_type:
            self.duplicate_warning.hide()
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
        self._preview_zoom_mode = "fit_window"
        self._preview_scale = 1.0
        self._update_preview_zoom_label()
        self._set_page_controls_visible(False)
        if _widget_alive(self.page_combo):
            self.page_combo.blockSignals(True)
            self.page_combo.clear()

        path = Path(item.file_path)
        if not path.exists():
            self.current_pixmap = None
            self._preview_item = None
            if _widget_alive(self.page_combo):
                self.page_combo.blockSignals(False)
            self.update_preview()
            return

        if path.suffix.lower() == ".pdf":
            self.document = fitz.open(str(path))
            for page_index in range(len(self.document)):
                self.page_combo.addItem(f"Page {page_index + 1}", page_index)
            if _widget_alive(self.page_combo):
                page = int(item.export_settings.get("page", 0))
                page = min(page, len(self.document) - 1)
                self._set_page_controls_visible(len(self.document) > 1)
                self.page_combo.setCurrentIndex(page)
                self.page_combo.blockSignals(False)
                self.change_page(self.page_combo.currentIndex())
        else:
            if _widget_alive(self.page_combo):
                self.page_combo.blockSignals(False)
            self.current_pixmap = render_document_pixmap(
                str(path),
            )
            self.update_preview(reset_zoom=True)

    def close_document(self):
        if self.document:
            self.document.close()
        self.document = None

    def change_page(self, index):
        if self._is_closing:
            return
        item = self.controller.selected_item()
        if item is not None and index >= 0:
            item.export_settings["page"] = index
        if self.document is None or index < 0:
            self._update_preview_meta_label(item)
            return

        self.current_pixmap = render_pdf_page(self.document, index)
        self.update_preview()
        self._update_preview_meta_label(item)

    def go_to_previous_page(self, checked=False):
        if not _widget_alive(self.page_combo):
            return
        current = self.page_combo.currentIndex()
        if current > 0:
            self.page_combo.setCurrentIndex(current - 1)

    def go_to_next_page(self, checked=False):
        if not _widget_alive(self.page_combo):
            return
        current = self.page_combo.currentIndex()
        if current + 1 < self.page_combo.count():
            self.page_combo.setCurrentIndex(current + 1)

    def _set_page_controls_visible(self, visible):
        for widget in (
            getattr(self, "page_label", None),
            getattr(self, "page_combo", None),
            getattr(self, "page_prev_btn", None),
            getattr(self, "page_next_btn", None),
        ):
            if _widget_alive(widget):
                widget.setVisible(visible)

    def _set_preview_controls_enabled(self, enabled):
        for widget in (
            getattr(self, "preview_zoom_label", None),
            getattr(self, "preview_zoom_out_btn", None),
            getattr(self, "preview_zoom_in_btn", None),
            getattr(self, "preview_fit_width_btn", None),
            getattr(self, "preview_fit_window_btn", None),
            getattr(self, "preview_reset_btn", None),
        ):
            if _widget_alive(widget):
                widget.setEnabled(enabled)

    def update_preview(self, reset_zoom=False):
        if self._is_closing:
            return
        if not _widget_alive(self.scene):
            return
        if reset_zoom:
            self._preview_zoom_mode = "fit_window"
            self._preview_scale = 1.0
        self.scene.clear()
        self._preview_item = None
        if self.current_pixmap is None or self.current_pixmap.isNull():
            self.scene.addText("Preview unavailable")
            self._set_preview_controls_enabled(False)
            self.graphics_view.set_preview_interactions_enabled(False)
            self._update_preview_zoom_label()
            self._update_action_states()
            return

        pix_item = QGraphicsPixmapItem(self.current_pixmap)
        pix_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(pix_item)
        self.scene.setSceneRect(pix_item.boundingRect())
        self._preview_item = pix_item
        self._set_preview_controls_enabled(True)
        self.graphics_view.set_preview_interactions_enabled(True)
        self._apply_preview_zoom()
        self._update_action_states()

    def _preview_base_scale(self, mode):
        if self._preview_item is None or self.current_pixmap is None:
            return 1.0

        view_rect = self.graphics_view.viewport().rect()
        pix_rect = self.current_pixmap.rect()
        if (
            view_rect.width() <= 0
            or view_rect.height() <= 0
            or pix_rect.width() <= 0
            or pix_rect.height() <= 0
        ):
            return 1.0

        padding = 40
        width_scale = max((view_rect.width() - padding) / pix_rect.width(), 0.05)
        height_scale = max(
            (view_rect.height() - padding) / pix_rect.height(),
            0.05,
        )

        if mode == "fit_width":
            return width_scale
        return min(width_scale, height_scale)

    def _apply_preview_zoom(self, recenter=True, anchor_view_pos=None):
        if self._preview_item is None or self.current_pixmap is None:
            return

        anchor_item_pos = None
        if not recenter and anchor_view_pos is not None:
            anchor_scene_pos = self.graphics_view.mapToScene(anchor_view_pos)
            anchor_item_pos = self._preview_item.mapFromScene(anchor_scene_pos)

        if self._preview_zoom_mode in {"fit_window", "fit_width"}:
            scale = self._preview_base_scale(self._preview_zoom_mode)
            self._preview_scale = scale
        else:
            scale = min(
                max(self._preview_scale, PREVIEW_MIN_SCALE),
                PREVIEW_MAX_SCALE,
            )
            self._preview_scale = scale

        self._preview_item.setScale(scale)
        self.scene.setSceneRect(self._preview_item.sceneBoundingRect())
        if anchor_item_pos is not None:
            new_anchor_scene_pos = self._preview_item.mapToScene(anchor_item_pos)
            new_anchor_pos = self.graphics_view.mapFromScene(new_anchor_scene_pos)
            delta = new_anchor_pos - anchor_view_pos
            self.graphics_view.horizontalScrollBar().setValue(
                self.graphics_view.horizontalScrollBar().value() + delta.x()
            )
            self.graphics_view.verticalScrollBar().setValue(
                self.graphics_view.verticalScrollBar().value() + delta.y()
            )
        elif recenter:
            self.graphics_view.centerOn(self._preview_item)
        self._update_preview_zoom_label()

    def _update_preview_zoom_label(self):
        if not _widget_alive(self.preview_zoom_label):
            return

        percent = max(int(round(self._preview_scale * 100)), 1)
        if self._preview_zoom_mode == "fit_width":
            prefix = "Fit W"
        elif self._preview_zoom_mode == "fit_window":
            prefix = "Fit"
        else:
            prefix = ""

        self.preview_zoom_label.setText(
            f"{prefix} {percent}%".strip()
        )

    def _update_preview_meta_label(self, item):
        if not _widget_alive(self.preview_meta_label):
            return

        if item is None:
            self.preview_meta_label.setText("Add files to begin.")
            return

        parts = [
            self.document_type_text(item),
            item.file_size_text,
        ]
        page_count = getattr(self.document, "page_count", 0) if self.document else 0
        if page_count > 1 and _widget_alive(self.page_combo):
            current_page = self.page_combo.currentIndex() + 1
            parts.append(f"Page {current_page} of {page_count}")
        elif page_count == 1:
            parts.append("Single page")

        self.preview_meta_label.setText(" · ".join(parts))

    def zoom_in_preview(self, checked=False):
        self._zoom_preview_by(1.25)

    def zoom_out_preview(self, checked=False):
        self._zoom_preview_by(0.8)

    def _zoom_preview_by(self, factor, anchor_view_pos=None):
        if self.current_pixmap is None or self._preview_item is None:
            return
        self._preview_zoom_mode = "manual"
        self._preview_scale = min(
            max(self._preview_scale * factor, PREVIEW_MIN_SCALE),
            PREVIEW_MAX_SCALE,
        )
        self._apply_preview_zoom(
            recenter=anchor_view_pos is None,
            anchor_view_pos=anchor_view_pos,
        )

    def fit_preview_width(self, checked=False):
        if self.current_pixmap is None or self._preview_item is None:
            return
        self._preview_zoom_mode = "fit_width"
        self._apply_preview_zoom()

    def fit_preview_window(self, checked=False):
        if self.current_pixmap is None or self._preview_item is None:
            return
        self._preview_zoom_mode = "fit_window"
        self._apply_preview_zoom()

    def reset_preview_zoom(self, checked=False):
        if self.current_pixmap is None or self._preview_item is None:
            return
        self._preview_zoom_mode = "manual"
        self._preview_scale = 1.0
        self._apply_preview_zoom()

    def persist_current_editor_settings(self, item=None):
        if self._is_closing:
            return
        item = item or self.controller.selected_item()
        if item is None:
            return
        if _widget_alive(self.page_combo) and self.page_combo.isVisible():
            if self.page_combo.currentIndex() >= 0:
                item.export_settings["page"] = self.page_combo.currentIndex()
        if _widget_alive(getattr(self, "notes_editor", None)):
            item.notes = self.notes_editor.toPlainText().strip()

    def clear_ocr_form(self):
        try:
            while self.ocr_form.rowCount():
                self.ocr_form.removeRow(0)
        except RuntimeError:
            pass
        self.field_edits = {}
        self.date_edits = {}

    def render_ocr_fields(self, item):
        if self._is_closing:
            return
        self.clear_ocr_form()
        fields = DOCUMENTS.get(item.document_type, {}).get("ocr_fields", [])
        if not fields:
            if not item.document_type:
                self.apply_ocr_banner(
                    "skipped",
                    "Select a document type to enable OCR.",
                )
                return
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
                edit = create_date_picker()
                if hasattr(edit, "setMinimumDate"):
                    edit.setMinimumDate(DATE_PLACEHOLDER)
                if hasattr(edit, "setSpecialValueText"):
                    edit.setSpecialValueText("--")
                parsed = self._to_qdate(value)
                edit.setDate(parsed or DATE_PLACEHOLDER)
                if hasattr(edit, "dateChanged"):
                    edit.dateChanged.connect(
                        lambda _value, self=self: self._sync_current_ocr_data()
                    )
                self.date_edits[field] = edit
                if _widget_alive(self.ocr_form):
                    field_widget = QWidget()
                    field_layout = QVBoxLayout()
                    field_layout.setContentsMargins(0, 0, 0, 0)
                    field_layout.setSpacing(6)
                    field_widget.setLayout(field_layout)

                    field_label_widget = QLabel(label)
                    field_label_widget.setObjectName("UploadOcrFieldLabel")
                    field_layout.addWidget(field_label_widget)
                    field_layout.addWidget(edit)

                    self.ocr_form.addRow(field_widget)
            else:
                edit = create_line_edit()
                edit.setText(
                    normalize_passport_number(value)
                    if field == "passport_number"
                    else str(value or "")
                )
                if field == "passport_number":
                    edit.textChanged.connect(
                        lambda text, edit=edit: self._normalize_passport_edit(
                            edit, text
                        )
                    )
                edit.textChanged.connect(
                    lambda _text, self=self: self._sync_current_ocr_data()
                )
                self.field_edits[field] = edit
                if _widget_alive(self.ocr_form):
                    self.ocr_form.addRow(f"{label}", edit)

    @staticmethod
    def _normalize_passport_edit(edit, value):
        normalized = normalize_passport_number(value)
        if normalized == value:
            return
        cursor_position = edit.cursorPosition()
        edit.setText(normalized)
        edit.setCursorPosition(min(cursor_position, len(normalized)))

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
            value = edit.text().strip()
            data[field] = (
                normalize_passport_number(value)
                if field == "passport_number"
                else value
            )
        for field, edit in self.date_edits.items():
            qdate = self._date_picker_value(edit)
            if qdate.isValid() and qdate != DATE_PLACEHOLDER:
                data[field] = qdate.toString("yyyy-MM-dd")
        item.confirmed_data = data

    @staticmethod
    def _date_picker_value(edit):
        if hasattr(edit, "getDate"):
            return edit.getDate()
        return edit.date()

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

    def run_ocr_for_selected(self, checked=False):
        item = self.controller.selected_item()
        if item is None:
            return
        if not item.document_type:
            self.apply_ocr_banner(
                "skipped",
                "Select a document type before running OCR.",
            )
            if _widget_alive(self.status_label):
                self.status_label.setText(
                    "Select a document type before running OCR."
                )
            return
        self.persist_current_editor_settings(item)
        self._run_ocr_async(self.controller.selected_index, reason="manual")

    def save_all(self, checked=False):
        current = self.controller.selected_item()
        if current is not None:
            self.persist_current_item_state()

        self._save_all_total = self._count_save_all_items()
        self._save_all_completed = 0
        if self._save_all_total <= 0:
            self.update_progress()
            self._update_action_states()
            return

        self._saving_all = True
        self._save_all_index = 0
        self._set_busy(True, "Saving documents...")
        self._show_save_progress_dialog()
        self.hide()
        QTimer.singleShot(0, self._save_all_next)

    def _count_save_all_items(self):
        total = 0
        for item in self.controller.items:
            if item.status in {"saved", "skipped"}:
                continue
            if item.duplicate_action != "skip" and not item.document_type:
                continue
            total += 1
        return total

    def _show_save_progress_dialog(self):
        dialog = self._save_progress_dialog
        if not _widget_alive(dialog):
            parent = self.parentWidget()
            dialog = UploadSaveProgressDialog(parent)
            self._save_progress_dialog = dialog

        dialog.set_progress(
            self._save_all_completed,
            self._save_all_total,
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _update_save_progress_dialog(self, file_name=None):
        dialog = self._save_progress_dialog
        if not _widget_alive(dialog):
            return

        dialog.set_progress(
            self._save_all_completed,
            self._save_all_total,
            file_name=file_name,
        )

    def _hide_save_progress_dialog(self):
        dialog = self._save_progress_dialog
        if _widget_alive(dialog):
            dialog.hide()

    def _save_all_next(self):
        if self._is_closing or not self._saving_all:
            return

        total = len(self.controller.items)
        while self._save_all_index < total:
            index = self._save_all_index
            item = self.controller.items[index]
            self._save_all_index += 1

            if item.status in {"saved", "skipped"}:
                continue
            if item.duplicate_action != "skip" and not item.document_type:
                continue

            self.controller.select(index)
            self._set_queue_row(index)
            self.load_detail()

            if not item.has_ocr_fields:
                item.confirmed_data = {}

            self._update_save_progress_dialog(item.file_name)
            self._set_busy(
                True,
                f"Saving {index + 1} of {total}: {item.file_name}...",
            )
            self.controller.save_item(
                item,
                parent=self,
                run_ocr=False,
            )
            self._save_all_completed += 1
            self._update_save_progress_dialog()
            self.refresh_queue()
            self.update_progress()
            QTimer.singleShot(0, self._save_all_next)
            return

        self._saving_all = False
        self._save_all_index = 0
        self._set_busy(False)
        self.after_save(close_after=True, refresh_ui=False)
        self._hide_save_progress_dialog()

    def after_save(self, close_after=False, refresh_ui=True):
        if self._is_closing:
            return
        logger.info(
            "Post-save refresh selected_index=%s selected_file=%s selected_status=%s",
            self.controller.selected_index,
            getattr(self.controller.selected_item(), "file_name", None),
            getattr(self.controller.selected_item(), "status", None),
        )
        if refresh_ui:
            self.refresh_queue()
            if (
                self.controller.selected_item() is not None
                and self._detail_widgets_available()
            ):
                self.load_detail()
            else:
                self.clear_detail()
            self.update_progress()
            self._update_action_states()
        self._emit_appointment_dates_updated_if_needed()
        if close_after and not self._is_closing:
            self.accept()

    def _appointment_updated_fields(self):
        return sorted(
            set(self.controller.updated_fields)
            & APPOINTMENT_UPDATE_FIELDS
        )

    def _emit_appointment_dates_updated_if_needed(self):
        fields = set(self._appointment_updated_fields())
        new_fields = sorted(
            fields - self._emitted_appointment_update_fields
        )
        if not new_fields:
            return

        missionary_id = getattr(self.controller.missionary, "id", None)
        if missionary_id is None:
            return

        try:
            from services.appointment_service import AppointmentService

            AppointmentService().sync_from_missionary_dates(
                missionary_id,
                new_fields,
            )
        except Exception:
            logger.exception(
                "Failed to sync appointment attempts after upload"
            )

        self._emitted_appointment_update_fields.update(new_fields)
        self.appointment_dates_updated.emit(missionary_id, new_fields)

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
        self._set_progress_step(
            self.progress_step_files,
            "complete" if total else "idle",
            "Files added" if total else "Waiting",
        )
        ocr_active = any(item.status == "ocr" for item in self.controller.items)
        if ocr_active:
            review_state = "active"
            review_text = "Reading"
        elif review:
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

        if self._saving_all:
            save_state = "active"
            save_text = "Saving"
        elif saved:
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
        for label in labels:
            _refresh_style(label)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        self.add_files(supported_upload_files_from_paths(files))
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self._busy:
            if _widget_alive(getattr(self, "status_label", None)):
                self.status_label.setText("Please wait for the current upload action to finish.")
            event.ignore()
            return
        self._is_closing = True
        self._hide_content_loading_overlay()
        parent_window = getattr(self, "_tracked_parent_window", None)
        if _widget_alive(parent_window):
            parent_window.removeEventFilter(self)
        self._tracked_parent_window = None
        self.close_document()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_screen_tracking()
        self._schedule_responsive_shell_geometry()
        QTimer.singleShot(0, self._start_ocr_warmup)
        if self._preview_item is not None:
            QTimer.singleShot(0, self._apply_preview_zoom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._preview_item is not None and self._preview_zoom_mode in {
            "fit_window",
            "fit_width",
        }:
            self._apply_preview_zoom()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._ensure_screen_tracking()
        self._schedule_responsive_shell_geometry()

    def _onDone(self, code):
        on_done = getattr(super(), "_onDone", None)
        if callable(on_done):
            on_done(code)
            return
        QDialog.done(self, code)

    def accept(self):
        if self._busy:
            if _widget_alive(getattr(self, "status_label", None)):
                self.status_label.setText("Please wait for the current upload action to finish.")
            return
        self._is_closing = True
        self._hide_content_loading_overlay()
        self.close_document()
        accept = getattr(super(), "accept", None)
        if callable(accept):
            accept()
            return
        QDialog.done(self, QDialog.Accepted)

    def reject(self):
        if self._busy:
            if _widget_alive(getattr(self, "status_label", None)):
                self.status_label.setText("Please wait for the current upload action to finish.")
            return
        self._is_closing = True
        self._hide_content_loading_overlay()
        self.close_document()
        reject = getattr(super(), "reject", None)
        if callable(reject):
            reject()
            return
        QDialog.done(self, QDialog.Rejected)

    def saved_any(self):
        return self.controller.has_saved_items()

