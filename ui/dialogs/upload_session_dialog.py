from pathlib import Path

import fitz
from shiboken6 import isValid as shiboken_is_valid

from PySide6.QtCore import (
    QDate,
    QEvent,
    QPoint,
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
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from services.settings_service import SettingsService
from services.upload_pipeline import (
    OCR_MODE_SUBPROCESS,
    UploadPipelineResult,
    finalize_ocr_ingestion,
    finalize_saved_ocr_follow_up,
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
    setup_dialog_shell,
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
)
from utils.constants import (
    DOCUMENTS,
    MISSIONARY_DATE_FIELDS,
    WORKFLOW_STAGES,
    requires_fbi_document,
    visible_document_keys_for_missionary,
)
from ui.file_dialogs import downloads_folder
from ui.dialogs.passport_photo_review_dialog import PassportPhotoReviewDialog
from ui.dialogs.upload_session.models import UploadQueueItem, UploadSaveResult
from ui.dialogs.upload_session.controller import UploadSessionController
from ui.dialogs.upload_session.orchestration import (
    UploadBatchCoordinator,
    UploadOcrWorkerCoordinator,
    UploadSaveWorkerCoordinator,
)
from ui.dialogs.upload_session.preview import UploadPreviewGraphicsView
from ui.dialogs.upload_session.progress import UploadSaveProgressDialog
from ui.dialogs.upload_session.workers import (
    UploadOcrWarmupWorker as _UploadOcrWarmupWorker,
    UploadOcrWorker,
    UploadSaveWorker,
)
from utils.document_files import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    document_file_dialog_filter,
    sha256_file,
    validate_document_file,
)
from utils.i18n import field_label, get_i18n, tr
from utils.logger import logger
from utils.passport_numbers import normalize_passport_number


SUPPORTED_EXTENSIONS = SUPPORTED_DOCUMENT_EXTENSIONS
DATE_PLACEHOLDER = QDate(1900, 1, 1)
PREVIEW_MIN_SCALE = 0.05
PREVIEW_MAX_SCALE = 8.0
APPOINTMENT_UPDATE_FIELDS = {
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
}
OCR_HIDDEN_REVIEW_FIELDS = {
    "PASSPORT": {"full_name"},
}


def document_type_menu_sections(missionary):
    """Return the compact upload-menu hierarchy for a missionary."""
    visible_keys = set(visible_document_keys_for_missionary(missionary))
    sections = []

    for stage in WORKFLOW_STAGES:
        keys = [
            key
            for key, config in DOCUMENTS.items()
            if key in visible_keys
            and config.get("stage") == stage
            and (
                config.get("required")
                or key == "CONSTANCIA_DE_PRORROGA"
            )
            and key != "TAM"
        ]
        if stage == "INTERPOL" and "FBI" in visible_keys:
            keys.insert(0, "FBI")
        sections.append((stage, list(dict.fromkeys(keys))))

    sections.append(("GENERAL", ["TAM", "PASSPORT"]))
    direct_items = [("DNI", DOCUMENTS["DNI"]["label"])]
    other_keys = ["PHOTO", "OTHER"]
    sections.append(
        ("OTHER", [key for key in other_keys if key in visible_keys])
    )
    return sections, direct_items


class DocumentTypeMenuPicker(QWidget):
    """Button-backed selector using the same menus as contextual actions."""

    currentIndexChanged = Signal(int)

    def __init__(self, missionary, parent=None):
        super().__init__(parent)
        self._items = [("Select document type...", None)]
        self._current_index = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = create_button("Select document type...", "secondary")
        self.button.setObjectName("UploadFieldInput")
        layout.addWidget(self.button, stretch=1)

        menu = create_menu("", self.button)
        sections, direct_items = document_type_menu_sections(missionary)
        stage_and_general_sections = sections[:-1]
        other_section = sections[-1]
        for title, keys in stage_and_general_sections:
            submenu = create_menu(title.title(), menu)
            for key in keys:
                self._add_document_action(submenu, key)
            menu.addMenu(submenu)

        for key, _label in direct_items:
            self._add_document_action(menu, key)

        title, keys = other_section
        submenu = create_menu(title.title(), menu)
        for key in keys:
            self._add_document_action(submenu, key)
        menu.addMenu(submenu)

        self.button.setMenu(menu)

    def _add_document_action(self, menu, key):
        label = DOCUMENTS[key]["label"]
        index = len(self._items)
        self._items.append((label, key))
        action = QAction(label, menu)
        action.triggered.connect(
            lambda checked=False, item_index=index: self.setCurrentIndex(
                item_index
            )
        )
        menu.addAction(action)

    def currentData(self):
        return self._items[self._current_index][1]

    def findData(self, value):
        for index, (_, data) in enumerate(self._items):
            if data == value:
                return index
        return -1

    def setCurrentData(self, value):
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)

    def setCurrentIndex(self, index):
        if not 0 <= index < len(self._items):
            return
        changed = index != self._current_index
        self._current_index = index
        self.button.setText(self._items[index][0])
        if changed:
            self.currentIndexChanged.emit(index)


def classify_upload_paths(paths):
    """Expand selected paths into accepted files and explicit rejections."""

    files = []
    rejected = []
    for raw_path in paths or []:
        path = Path(raw_path)
        if path.is_dir():
            try:
                children = [
                    child
                    for child in sorted(
                        path.rglob("*"),
                        key=lambda child_path: (
                            len(child_path.relative_to(path).parts),
                            str(child_path).lower(),
                        ),
                    )
                    if child.is_file()
                ]
            except OSError:
                rejected.append((str(path), "The folder could not be read."))
                continue
            if not children:
                rejected.append((str(path), "The folder contains no files."))
                continue
            for child in children:
                if child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files.append(str(child))
                else:
                    rejected.append(
                        (
                            str(child),
                            f"Unsupported file type: {child.suffix or 'no extension'}",
                        )
                    )
        elif path.is_file():
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(str(path))
            else:
                rejected.append(
                    (
                        str(path),
                        f"Unsupported file type: {path.suffix or 'no extension'}",
                    )
                )
        else:
            rejected.append(
                (str(path), "The file is missing or is not a regular file.")
            )
    return files, rejected


def supported_upload_files_from_paths(paths):
    files, _rejected = classify_upload_paths(paths)
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


class UploadOcrWarmupWorker(_UploadOcrWarmupWorker):
    """Compatibility wrapper preserving the dialog module's patch seam."""

    def __init__(self):
        super().__init__(service_factory=lambda **kwargs: get_ocr_service(**kwargs))




class UploadSessionDialog(MaskDialogBase):
    ocr_finished_on_ui = Signal(int, bool, str, object, str)
    appointment_dates_updated = Signal(int, list)
    document_uploaded = Signal(int, int)
    document_saved = Signal(int, object)

    def _batch_coordinator(self):
        coordinator = self.__dict__.get("_batch")
        if coordinator is None:
            coordinator = UploadBatchCoordinator()
            self.__dict__["_batch"] = coordinator
        return coordinator

    def _ocr_worker_coordinator(self):
        coordinator = self.__dict__.get("_ocr_coordinator")
        if coordinator is None:
            coordinator = UploadOcrWorkerCoordinator(
                None,
                thread_factory=lambda parent: QThread(parent),
                worker_factory=lambda controller, index: UploadOcrWorker(
                    controller,
                    index,
                ),
            )
            coordinator.result_ready.connect(
                self.ocr_finished_on_ui.emit,
                Qt.ConnectionType.QueuedConnection,
            )
            self.__dict__["_ocr_coordinator"] = coordinator
        return coordinator

    @property
    def _saving_all(self):
        return self._batch_coordinator().saving

    @_saving_all.setter
    def _saving_all(self, value):
        coordinator = self._batch_coordinator()
        if value:
            coordinator.begin(coordinator.total)
        else:
            coordinator.finish()

    @property
    def _save_all_index(self):
        return self._batch_coordinator().next_index

    @_save_all_index.setter
    def _save_all_index(self, value):
        self._batch_coordinator().next_index = int(value)

    @property
    def _save_all_total(self):
        return self._batch_coordinator().total

    @_save_all_total.setter
    def _save_all_total(self, value):
        self._batch_coordinator().total = int(value)

    @property
    def _save_all_completed(self):
        return self._batch_coordinator().completed

    @_save_all_completed.setter
    def _save_all_completed(self, value):
        self._batch_coordinator().completed = int(value)

    @property
    def _save_all_results(self):
        return self._batch_coordinator().results

    @_save_all_results.setter
    def _save_all_results(self, value):
        self._batch_coordinator().results = list(value)

    def __init__(self, missionary, initial_files=None, parent=None):
        super().__init__(parent)
        main_window = getattr(parent, "main_window", None)
        self._batch = UploadBatchCoordinator()
        active_language = get_i18n().get_language()
        self.settings_service = (
            getattr(main_window, "settings_service", None)
            or SettingsService()
        )
        # Constructing a fallback SettingsService reads persisted settings.
        # An already-active UI language is authoritative for this dialog.
        get_i18n().set_language(active_language)
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
        self._ocr_coordinator = None
        self._ocr_warmup_thread = None
        self._ocr_warmup_worker = None
        self._ocr_warmup_started = False
        self._pending_save_after_ocr = None
        self._saving_all = False
        self._save_all_index = 0
        self._save_all_total = 0
        self._save_all_completed = 0
        self._save_all_results = []
        self._save_coordinator = UploadSaveWorkerCoordinator(self)
        self._save_coordinator.result_ready.connect(
            self._handle_save_worker_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._save_coordinator.idle.connect(
            self._save_worker_thread_finished,
        )
        self._save_progress_dialog = None
        self._active_screen = None
        self._screen_changed_connected = False
        self._tracked_parent_window = None
        self._emitted_appointment_update_fields = set()
        self._derived_temp_paths = set()
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
            self.add_files(initial_files)

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
        self._build_footer(root)
        self._ensure_screen_tracking()
        self._apply_responsive_shell_geometry()
        self._set_page_controls_visible(False)
        self._set_preview_controls_enabled(False)
        self._set_busy(False)
        self.clear_detail()
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

        self.type_combo = DocumentTypeMenuPicker(
            self.controller.missionary,
            self.middle_panel,
        )
        self.type_combo.setObjectName("UploadFieldInput")
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
        self.duplicate_combo.addItem("Keep both", "keep")
        self.duplicate_combo.addItem("Replace existing", "replace")
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
        return True

    def _item_can_autodetect(self, item):
        return bool(
            item
            and item.document_type
            and item.has_ocr_fields
            and item.status not in {"saved", "skipped", "ocr", "unknown"}
        )

    def _has_unsaved_valid_items(self):
        return any(
            item.status not in {"saved", "skipped", "ocr"}
            or (item.status == "saved" and bool(item.warnings))
            for item in self.controller.items
        )

    def _has_unknown_outcomes(self):
        return any(
            item.status == "unknown"
            for item in self.controller.items
        )

    def _block_close_for_unknown_outcomes(self, event=None):
        if not self._has_unknown_outcomes():
            return False
        if _widget_alive(getattr(self, "status_label", None)):
            self.status_label.setText(
                "One or more uploads are still being verified. Click Save All "
                "to reconcile them before closing this window."
            )
        if event is not None:
            event.ignore()
        return True

    def _update_action_states(self):
        if self._is_closing:
            return

        item = self.controller.selected_item()
        has_items = bool(self.controller.items)
        has_selection = item is not None
        can_edit = has_selection and not self._busy
        can_modify = can_edit and item.status not in {
            "saved",
            "skipped",
            "unknown",
        }
        can_autodetect = can_modify and self._item_can_autodetect(item)
        for name in (
            "type_combo",
            "stage_combo",
            "duplicate_combo",
            "notes_editor",
        ):
            self._set_widget_enabled(name, can_modify)
        for field_edit in (
            list(self.field_edits.values()) + list(self.date_edits.values())
        ):
            if _widget_alive(field_edit):
                field_edit.setEnabled(can_modify)

        self._set_widget_enabled(
            "remove_btn",
            can_edit and item.status != "unknown",
        )
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
                self._preview_item is not None and can_modify,
            )

    def pick_files(self, checked=False):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Documents",
            downloads_folder(),
            document_file_dialog_filter(),
        )
        self.add_files(files)

    def pick_folder(self, checked=False):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder",
            downloads_folder(),
        )
        if not folder:
            return

        self.add_files([folder])

    def add_files(self, files):
        accepted, rejected = classify_upload_paths(files)
        added = self.controller.add_files(accepted)
        rejected_items = self.controller.add_rejected_files(rejected)
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
            if rejected_items:
                names = ", ".join(
                    item.file_name for item in rejected_items[:3]
                )
                remainder = len(rejected_items) - 3
                more = f" and {remainder} more" if remainder > 0 else ""
                self.status_label.setText(
                    f"Rejected {len(rejected_items)} file(s): {names}{more}. "
                    "Select each failed item for details or remove it."
                )
            elif added:
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
            status = self.status_text(item)
            list_item.setText(
                f"{prefix}  {item.file_name}  |  {document_type}  |  "
                f"{item.file_size_text}  |  {status}"
            )
            list_item.setToolTip(
                f"{item.file_name}\n{document_type}\n{item.file_size_text}"
                f"\n{status}"
                + (f"\n{item.error_text}" if item.error_text else "")
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
        except Exception:
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
        if item.status == "saved" and item.warnings:
            return "Saved with warning"
        return {
            "pending": "Queued",
            "ocr": "Reading",
            "ready": "Ready",
            "review": "Needs review",
            "saved": "Saved",
            "failed": "Failed",
            "unknown": "Needs verification",
            "rejected": "Rejected",
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

        self._set_busy(
            True,
            f"Reading fields from {item.file_name}...",
            content_loading_overlay=True,
            content_loading_messages=self._ocr_loading_messages(),
        )
        return self._ocr_worker_coordinator().start(
            self.controller,
            index,
            reason,
        )

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
            photo_reviewed = None
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
            photo_item = self.controller.add_passport_photo_candidate(
                item,
                getattr(result, "passport_photo_candidate", None),
            )
            if photo_item is not None:
                self._derived_temp_paths.add(photo_item.file_path)
                photo_reviewed = self._review_passport_photo(photo_item)
            self.refresh_queue()
            self.update_progress()
            if _widget_alive(self.status_label):
                if ok:
                    if photo_reviewed is True:
                        self.status_label.setText(
                            "Reading complete. The approved passport photo was "
                            "added to the upload queue."
                        )
                    elif photo_reviewed is False:
                        self.status_label.setText(
                            "Reading complete. The passport photo crop was rejected."
                        )
                    else:
                        self.status_label.setText(
                            item.error_text or "Reading complete."
                        )
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
            duplicate_action = self.duplicate_combo.currentData()
            if item.duplicate_action != duplicate_action:
                item.supersedes_document_id = None
                item.replacement_target_resolved = False
            item.duplicate_action = duplicate_action
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

    def _cleanup_derived_temp_files(self):
        for value in list(getattr(self, "_derived_temp_paths", set())):
            try:
                Path(value).unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not remove derived passport photo temp file: %s",
                    value,
                )
        self._derived_temp_paths.clear()

    def _review_passport_photo(self, photo_item):
        dialog = PassportPhotoReviewDialog(photo_item.file_path, self)
        if dialog.exec() == QDialog.Accepted:
            photo_item.derived_photo_approved = True
            photo_item.status = "pending"
            photo_item.error_text = ""
            logger.info(
                "PASSPORT_PHOTO_APPROVED source_upload=%s photo=%s",
                photo_item.derived_from_upload_id,
                photo_item.file_name,
            )
            return True

        photo_path = photo_item.file_path
        try:
            index = self.controller.items.index(photo_item)
        except ValueError:
            index = -1
        if index >= 0:
            self.controller.remove_item(index)
        self._derived_temp_paths.discard(photo_path)
        try:
            Path(photo_path).unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove rejected passport photo crop: %s",
                photo_path,
            )
        logger.info(
            "PASSPORT_PHOTO_REJECTED source_upload=%s",
            photo_item.derived_from_upload_id,
        )
        return False

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
            if field in OCR_HIDDEN_REVIEW_FIELDS.get(item.document_type, set()):
                continue
            value = item.confirmed_data.get(field, "")
            label = field_label(field)
            if field in MISSIONARY_DATE_FIELDS or field == "date_of_birth":
                edit = create_date_picker()
                if hasattr(edit, "setMinimumDate"):
                    edit.setMinimumDate(DATE_PLACEHOLDER)
                if hasattr(edit, "setSpecialValueText"):
                    edit.setSpecialValueText("--")
                parsed = self._to_qdate(value)
                edit.blockSignals(True)
                edit.setDate(parsed or DATE_PLACEHOLDER)
                edit.blockSignals(False)
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
                if hasattr(edit, "dateChanged"):
                    edit.dateChanged.connect(
                        lambda _value, self=self: self._sync_current_ocr_data()
                    )
            else:
                edit = create_line_edit()
                edit.blockSignals(True)
                edit.setText(
                    normalize_passport_number(value)
                    if field == "passport_number"
                    else str(value or "")
                )
                edit.blockSignals(False)
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
        hidden_fields = OCR_HIDDEN_REVIEW_FIELDS.get(item.document_type, set())
        data = {
            field: item.confirmed_data[field]
            for field in hidden_fields
            if field in item.confirmed_data
        }
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

        invalid_indexes = self._preflight_save_all()
        if invalid_indexes:
            first_index = invalid_indexes[0]
            self.controller.select(first_index)
            self._set_queue_row(first_index)
            self.refresh_queue()
            self.update_progress()
            if _widget_alive(self.status_label):
                self.status_label.setText(
                    f"Cannot save: {len(invalid_indexes)} file(s) need attention. "
                    "Select each failed item for details."
                )
            self._update_action_states()
            return

        self._save_all_total = self._count_save_all_items()
        self._save_all_completed = 0
        self._save_all_results = []
        if self._save_all_total <= 0:
            self.update_progress()
            self._update_action_states()
            return

        self._saving_all = True
        self._save_all_index = 0
        self._set_busy(True, "Saving documents...")
        self._show_save_progress_dialog()
        QTimer.singleShot(0, self._save_all_next)

    def _preflight_save_all(self):
        invalid = {}
        queued_by_type = {}

        for index, item in enumerate(self.controller.items):
            if item.status == "skipped" or (
                item.status == "saved" and not item.warnings
            ):
                continue
            if item.duplicate_action == "skip":
                item.error_text = ""
                continue

            is_saved_follow_up = bool(
                item.status == "saved"
                and item.warnings
                and item.saved_document_id is not None
            )
            is_source_independent_reconciliation = bool(
                item.status == "unknown"
                and item.content_sha256
                and item.file_size is not None
            )
            reason = (
                None
                if is_source_independent_reconciliation or is_saved_follow_up
                else validate_document_file(item.file_path)
            )
            if reason is None and item.document_type not in DOCUMENTS:
                reason = "Select a document type before saving this file."
            if (
                reason is None
                and item.derived_kind == "passport_photo"
                and not item.derived_photo_approved
            ):
                reason = (
                    "Approve or reject the passport photo crop before saving."
                )
            if (
                reason is None
                and item.document_type == "FBI"
                and not requires_fbi_document(self.controller.missionary)
            ):
                reason = (
                    "FBI documents are only available for USA or Canada "
                    "missionaries."
                )

            if reason:
                item.status = "failed"
                item.error_text = reason
                invalid[index] = reason
                continue

            if not is_saved_follow_up:
                queued_by_type.setdefault(item.document_type, []).append(index)

            if item.status != "unknown":
                item.error_text = ""
            if item.status in {"failed", "rejected"}:
                if item.ocr_result is not None:
                    self.controller._apply_post_ocr_state(item)
                else:
                    item.status = "pending"

        for document_type, indexes in queued_by_type.items():
            replace_indexes = [
                index
                for index in indexes
                if self.controller.items[index].duplicate_action == "replace"
            ]
            if not replace_indexes or len(indexes) <= 1:
                continue
            label = DOCUMENTS.get(document_type, {}).get(
                "label", document_type
            )
            reason = (
                f"Replace cannot be mixed with another queued {label} file. "
                "Choose Keep both for all of them, or save the replacement "
                "separately."
            )
            for index in indexes:
                item = self.controller.items[index]
                item.status = "failed"
                item.error_text = reason
                invalid[index] = reason

        self.controller._recount_results()
        return sorted(invalid)

    def _count_save_all_items(self):
        return sum(
            item.status not in {"saved", "skipped"}
            or (item.status == "saved" and bool(item.warnings))
            for item in self.controller.items
        )

    def _show_save_progress_dialog(self):
        dialog = self._save_progress_dialog
        if not _widget_alive(dialog):
            parent = self.parentWidget()
            dialog = UploadSaveProgressDialog(parent)
            self._save_progress_dialog = dialog

        dialog.set_progress(
            self._save_all_completed,
            self._save_all_total,
            saved=0,
            failed=0,
            skipped=0,
            warnings=0,
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _update_save_progress_dialog(self, file_name=None):
        dialog = self._save_progress_dialog
        if not _widget_alive(dialog):
            return

        counts = self._batch_coordinator().counts()
        dialog.set_progress(
            self._save_all_completed,
            self._save_all_total,
            file_name=file_name,
            **counts,
        )

    def _hide_save_progress_dialog(self):
        dialog = self._save_progress_dialog
        if _widget_alive(dialog):
            dialog.hide()

    def _save_all_next(self):
        if self._is_closing or not self._saving_all:
            return
        if self._save_coordinator.running:
            return

        total = len(self.controller.items)
        while self._save_all_index < total:
            index = self._save_all_index
            item = self.controller.items[index]
            self._save_all_index += 1

            if item.status == "skipped" or (
                item.status == "saved" and not item.warnings
            ):
                continue

            self.controller.select(index)
            self._set_queue_row(index)

            if not item.has_ocr_fields:
                item.confirmed_data = {}

            self._update_save_progress_dialog(item.file_name)
            self._set_busy(
                True,
                f"Saving {index + 1} of {total}: {item.file_name}...",
            )
            self._start_save_worker(index)
            return

        self._finish_save_all()

    def _start_save_worker(self, index):
        self._save_coordinator.start(self.controller, index)

    def _handle_save_worker_finished(self, index, result):
        self._batch_coordinator().record(result)
        document_id = getattr(result.document, "id", None)
        missionary_id = getattr(self.controller.missionary, "id", None)
        if (
            result.succeeded
            and document_id is not None
            and missionary_id is not None
        ):
            self.document_saved.emit(missionary_id, result.document)
            self.document_uploaded.emit(missionary_id, document_id)
        self._update_save_progress_dialog()
        self.refresh_queue()
        self.update_progress()

    def _save_worker_thread_finished(self):
        if self._saving_all and not self._is_closing:
            QTimer.singleShot(0, self._save_all_next)

    def _finish_save_all(self):
        self._saving_all = False
        self.controller._recount_results()
        counts = self._batch_coordinator().counts()
        saved = counts["saved"]
        failed = counts["failed"]
        skipped = counts["skipped"]
        warnings = counts["warnings"]
        summary = (
            f"Processed {self._save_all_completed} file(s): "
            f"{saved} saved, {failed} failed, {skipped} skipped."
        )
        if warnings:
            summary += f" {warnings} saved file(s) need follow-up."
        self._set_busy(False, summary)
        self._hide_save_progress_dialog()
        self.refresh_queue()
        self.update_progress()
        self.after_save(
            close_after=failed == 0 and warnings == 0,
            refresh_ui=False,
        )
        if failed or warnings:
            attention_index = next(
                (
                    index
                    for index, item in enumerate(self.controller.items)
                    if (
                        item.status not in {"saved", "skipped"}
                        or bool(item.warnings)
                    )
                ),
                -1,
            )
            if attention_index >= 0:
                self.controller.select(attention_index)
                self._set_queue_row(attention_index)
            if _widget_alive(self.status_label):
                follow_up = (
                    " Failed files remain in the queue and can be retried."
                    if failed
                    else " The documents are saved; review the follow-up warning."
                )
                self.status_label.setText(summary + follow_up)
            self._update_action_states()

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
        # Retained as a compatibility hook for upload flows and focused tests.
        # Save progress is presented by UploadSaveProgressDialog instead.
        return

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
        if self._busy:
            if _widget_alive(getattr(self, "status_label", None)):
                self.status_label.setText("Please wait for the current upload action to finish.")
            event.ignore()
            return
        if self._block_close_for_unknown_outcomes(event):
            return
        self._is_closing = True
        self._hide_content_loading_overlay()
        parent_window = getattr(self, "_tracked_parent_window", None)
        if _widget_alive(parent_window):
            parent_window.removeEventFilter(self)
        self._tracked_parent_window = None
        self.close_document()
        self._cleanup_derived_temp_files()
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
        if self._block_close_for_unknown_outcomes():
            return
        self._is_closing = True
        self._hide_content_loading_overlay()
        self.close_document()
        self._cleanup_derived_temp_files()
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
        if self._block_close_for_unknown_outcomes():
            return
        self._is_closing = True
        self._hide_content_loading_overlay()
        self.close_document()
        self._cleanup_derived_temp_files()
        reject = getattr(super(), "reject", None)
        if callable(reject):
            reject()
            return
        QDialog.done(self, QDialog.Rejected)

    def saved_any(self):
        return self.controller.has_saved_items()

