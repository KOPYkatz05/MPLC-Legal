from pathlib import Path

import fitz
from shiboken6 import isValid as shiboken_is_valid

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.document_rendering import (
    SUPPORTED_IMAGE_EXTENSIONS,
    get_document_viewer_render_hints,
    render_document_pixmap,
    render_pdf_page,
)
from ui.foundation import (
    MaskDialogBase,
    SmoothScrollDelegate,
    create_button,
    create_card,
    create_combo_box,
    setup_dialog_shell,
    tune_fluent_scrollable,
)
from utils.logger import logger


PREVIEW_MIN_SCALE = 0.05
PREVIEW_MAX_SCALE = 8.0


def _widget_alive(widget):
    try:
        return widget is not None and shiboken_is_valid(widget)
    except Exception:
        return False


class DocumentPreviewGraphicsView(QGraphicsView):
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
        self.zoom_requested.emit(1.25 if delta > 0 else 0.8, event.position().toPoint())
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
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
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


class DocumentPreviewWidget(QWidget):
    def __init__(self, file_path, parent=None, show_header=True, close_callback=None):
        super().__init__(parent)
        self.file_path = str(file_path)
        self.path = Path(file_path)
        self.show_header = show_header
        self.close_callback = close_callback
        self.document = None
        self.current_pixmap = None
        self._preview_item = None
        self._preview_scale = 1.0
        self._preview_zoom_mode = "fit_window"
        self._is_closing = False
        self.setup_ui()
        self.load_document()

    def setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setLayout(root)

        self.header = QFrame()
        self.header.setObjectName("PageHeader")
        self.header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(24, 16, 24, 16)
        header_layout.setSpacing(12)
        self.header.setLayout(header_layout)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(4)
        self.preview_name_label = QLabel(self.path.name or "Document Viewer")
        self.preview_name_label.setObjectName("PanelTitle")
        self.preview_meta_label = QLabel("Loading document...")
        self.preview_meta_label.setObjectName("MutedText")
        title_stack.addWidget(self.preview_name_label)
        title_stack.addWidget(self.preview_meta_label)

        self.file_type_badge = QLabel("Document")
        self.file_type_badge.setObjectName("UploadStatusChip")
        self.file_type_badge.setProperty("status", "ready")
        self.file_type_badge.setAlignment(Qt.AlignCenter)
        self.file_type_badge.setMinimumWidth(72)

        self.close_btn = create_button("Close", "secondary")
        self.close_btn.clicked.connect(self.accept)

        header_layout.addLayout(title_stack, stretch=1)
        header_layout.addWidget(self.file_type_badge, alignment=Qt.AlignTop)
        header_layout.addWidget(self.close_btn, alignment=Qt.AlignTop)
        self.header.setVisible(self.show_header)
        root.addWidget(self.header)

        body = QFrame()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(18, 18, 18, 18)
        body_layout.setSpacing(12)
        body.setLayout(body_layout)

        self.preview_card = create_card(object_name="UploadSurfaceCard")
        self.preview_card.setAttribute(Qt.WA_StyledBackground, True)
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(12)
        self.preview_card.setLayout(card_layout)

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
        self.page_prev_btn = self._make_preview_button("<", self.go_to_previous_page, width=34, tooltip="Previous page")
        self.page_next_btn = self._make_preview_button(">", self.go_to_next_page, width=34, tooltip="Next page")
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
        self.preview_zoom_out_btn = self._make_preview_button("-", self.zoom_out_preview, width=34, tooltip="Zoom out")
        self.preview_zoom_in_btn = self._make_preview_button("+", self.zoom_in_preview, width=34, tooltip="Zoom in")
        self.preview_fit_width_btn = self._make_preview_button("Width", self.fit_preview_width, tooltip="Fit to width")
        self.preview_fit_window_btn = self._make_preview_button("Fit", self.fit_preview_window, tooltip="Fit whole page")
        self.preview_reset_btn = self._make_preview_button("100%", self.reset_preview_zoom, tooltip="Actual size")
        zoom_group.addWidget(self.preview_zoom_label)
        zoom_group.addWidget(self.preview_zoom_out_btn)
        zoom_group.addWidget(self.preview_zoom_in_btn)
        zoom_group.addWidget(self.preview_fit_width_btn)
        zoom_group.addWidget(self.preview_fit_window_btn)
        zoom_group.addWidget(self.preview_reset_btn)
        toolbar_layout.addLayout(zoom_group)
        card_layout.addWidget(self.preview_toolbar)

        self.scene = QGraphicsScene()
        self.graphics_view = DocumentPreviewGraphicsView()
        self.graphics_view.setScene(self.scene)
        self.graphics_view.setAlignment(Qt.AlignCenter)
        self.graphics_view.setRenderHints(
            self.graphics_view.renderHints() | get_document_viewer_render_hints()
        )
        self.graphics_view.setFrameShape(QFrame.NoFrame)
        self.graphics_view.setBackgroundBrush(Qt.GlobalColor.white)
        self.graphics_view.setObjectName("UploadPreviewCanvas")
        self.graphics_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.graphics_view.zoom_requested.connect(self._zoom_preview_by)
        card_layout.addWidget(self.graphics_view, stretch=1)

        self.preview_empty_label = QLabel("Preview unavailable.")
        self.preview_empty_label.setObjectName("UploadEmptyState")
        self.preview_empty_label.setAlignment(Qt.AlignCenter)
        self.preview_empty_label.setWordWrap(True)
        card_layout.addWidget(self.preview_empty_label, stretch=1)

        body_layout.addWidget(self.preview_card, stretch=1)
        root.addWidget(body, stretch=1)

    def _make_preview_button(self, text, slot, width=None, tooltip=""):
        button = create_button(text, "subtle", fixed_height=28)
        button.setObjectName("UploadNavButton")
        if width is not None:
            button.setFixedWidth(width)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(slot)
        return button

    def load_document(self):
        self.close_document()
        self._preview_zoom_mode = "fit_window"
        self._preview_scale = 1.0
        self._set_page_controls_visible(False)
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.blockSignals(False)

        if not self.path.exists():
            self._show_empty_state("Cannot open document file.")
            return

        suffix = self.path.suffix.lower()
        try:
            if suffix == ".pdf":
                self._load_pdf()
            elif suffix in SUPPORTED_IMAGE_EXTENSIONS:
                self._load_image()
            else:
                self._show_empty_state("Unsupported file format.")
        except Exception:
            logger.exception("Document load failed")
            self._show_empty_state("Failed to load document.")

    def _load_pdf(self):
        self.document = fitz.open(str(self.path))
        page_count = self.document.page_count
        if page_count <= 0:
            self._show_empty_state("Preview unavailable.")
            return
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for page_index in range(page_count):
            self.page_combo.addItem(f"Page {page_index + 1}", page_index)
        self.page_combo.setCurrentIndex(0)
        self.page_combo.blockSignals(False)
        self.file_type_badge.setText("PDF")
        self._set_page_controls_visible(page_count > 1)
        self.change_page(0)

    def _load_image(self):
        self.current_pixmap = render_document_pixmap(str(self.path))
        self.file_type_badge.setText("Image")
        self._update_preview_meta_label()
        self.update_preview(reset_zoom=True)

    def close_document(self):
        if self.document is not None:
            self.document.close()
        self.document = None

    def change_page(self, index):
        if self._is_closing:
            return
        if self.document is None or index < 0:
            self._update_preview_meta_label()
            return
        self.current_pixmap = render_pdf_page(self.document, index)
        self._update_preview_meta_label()
        self.update_preview(reset_zoom=True)

    def go_to_previous_page(self, checked=False):
        _ = checked
        current = self.page_combo.currentIndex()
        if current > 0:
            self.page_combo.setCurrentIndex(current - 1)

    def go_to_next_page(self, checked=False):
        _ = checked
        current = self.page_combo.currentIndex()
        if current + 1 < self.page_combo.count():
            self.page_combo.setCurrentIndex(current + 1)

    def _set_page_controls_visible(self, visible):
        for widget in (self.page_label, self.page_combo, self.page_prev_btn, self.page_next_btn):
            if _widget_alive(widget):
                widget.setVisible(visible)

    def _set_preview_controls_enabled(self, enabled):
        for widget in (
            self.preview_zoom_label,
            self.preview_zoom_out_btn,
            self.preview_zoom_in_btn,
            self.preview_fit_width_btn,
            self.preview_fit_window_btn,
            self.preview_reset_btn,
        ):
            if _widget_alive(widget):
                widget.setEnabled(enabled)

    def update_preview(self, reset_zoom=False):
        if self._is_closing or not _widget_alive(self.scene):
            return
        if reset_zoom:
            self._preview_zoom_mode = "fit_window"
            self._preview_scale = 1.0

        self.scene.clear()
        self._preview_item = None
        if self.current_pixmap is None or self.current_pixmap.isNull():
            self._show_empty_state("Preview unavailable.")
            return

        pix_item = QGraphicsPixmapItem(self.current_pixmap)
        pix_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(pix_item)
        self.scene.setSceneRect(pix_item.boundingRect())
        self._preview_item = pix_item
        self.preview_empty_label.hide()
        self.graphics_view.show()
        self._set_preview_controls_enabled(True)
        self.graphics_view.set_preview_interactions_enabled(True)
        self._apply_preview_zoom()

    def _show_empty_state(self, message):
        self.current_pixmap = None
        self._preview_item = None
        self.scene.clear()
        self.preview_empty_label.setText(message)
        self.preview_empty_label.show()
        self.graphics_view.hide()
        self._set_preview_controls_enabled(False)
        self.graphics_view.set_preview_interactions_enabled(False)
        self._update_preview_zoom_label()
        self.preview_meta_label.setText(message)
        self.file_type_badge.setText("Unavailable")

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
        width_scale = max((view_rect.width() - padding) / pix_rect.width(), PREVIEW_MIN_SCALE)
        height_scale = max((view_rect.height() - padding) / pix_rect.height(), PREVIEW_MIN_SCALE)
        return width_scale if mode == "fit_width" else min(width_scale, height_scale)

    def _apply_preview_zoom(self, recenter=True, anchor_view_pos=None):
        if self._preview_item is None or self.current_pixmap is None:
            return
        anchor_item_pos = None
        if not recenter and anchor_view_pos is not None:
            anchor_scene_pos = self.graphics_view.mapToScene(anchor_view_pos)
            anchor_item_pos = self._preview_item.mapFromScene(anchor_scene_pos)
        if self._preview_zoom_mode in {"fit_window", "fit_width"}:
            self._preview_scale = self._preview_base_scale(self._preview_zoom_mode)
        else:
            self._preview_scale = min(max(self._preview_scale, PREVIEW_MIN_SCALE), PREVIEW_MAX_SCALE)
        self._preview_item.setScale(self._preview_scale)
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
        prefix = ""
        if self._preview_zoom_mode == "fit_width":
            prefix = "Fit W"
        elif self._preview_zoom_mode == "fit_window":
            prefix = "Fit"
        self.preview_zoom_label.setText(f"{prefix} {percent}%".strip())

    def _update_preview_meta_label(self):
        if not _widget_alive(self.preview_meta_label):
            return
        parts = [self._file_kind_text(), self._file_size_text()]
        page_count = getattr(self.document, "page_count", 0) if self.document else 0
        if page_count > 1 and self.page_combo.currentIndex() >= 0:
            parts.append(f"Page {self.page_combo.currentIndex() + 1} of {page_count}")
        elif page_count == 1:
            parts.append("Single page")
        self.preview_meta_label.setText(" · ".join(part for part in parts if part))

    def _file_kind_text(self):
        if self.path.suffix.lower() == ".pdf":
            return "PDF document"
        if self.path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            return "Image document"
        return "Document"

    def _file_size_text(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return "Unknown size"
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"

    def zoom_in_preview(self, checked=False):
        _ = checked
        self._zoom_preview_by(1.25)

    def zoom_out_preview(self, checked=False):
        _ = checked
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
        _ = checked
        if self.current_pixmap is not None and self._preview_item is not None:
            self._preview_zoom_mode = "fit_width"
            self._apply_preview_zoom()

    def fit_preview_window(self, checked=False):
        _ = checked
        if self.current_pixmap is not None and self._preview_item is not None:
            self._preview_zoom_mode = "fit_window"
            self._apply_preview_zoom()

    def reset_preview_zoom(self, checked=False):
        _ = checked
        if self.current_pixmap is not None and self._preview_item is not None:
            self._preview_zoom_mode = "manual"
            self._preview_scale = 1.0
            self._apply_preview_zoom()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._preview_item is not None and self._preview_zoom_mode in {"fit_window", "fit_width"}:
            self._apply_preview_zoom()

    def showEvent(self, event):
        super().showEvent(event)
        if self._preview_item is not None:
            QTimer.singleShot(0, self._apply_preview_zoom)

    def closeEvent(self, event):
        self._is_closing = True
        self.close_document()
        super().closeEvent(event)

    def accept(self):
        if callable(self.close_callback):
            self.close_callback()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Plus:
            self.zoom_in_preview()
        elif event.key() == Qt.Key_Minus:
            self.zoom_out_preview()
        elif event.key() == Qt.Key_0:
            self.fit_preview_window()
        else:
            super().keyPressEvent(event)


class DocumentViewerDialog(MaskDialogBase):
    _PREVIEW_DELEGATED_ATTRS = {
        "file_path",
        "path",
        "document",
        "current_pixmap",
        "_preview_item",
        "_preview_scale",
        "_preview_zoom_mode",
        "_is_closing",
    }

    def __init__(self, file_path, parent=None):
        owned_parent = None
        dialog_parent = parent
        if dialog_parent is None:
            owned_parent = QApplication.activeWindow() or QWidget()
            owned_parent.resize(1040, 760)
        super().__init__(dialog_parent or owned_parent)
        self._owned_mask_parent = owned_parent
        self._active_screen = None
        self._screen_changed_connected = False
        self._tracked_parent_window = None
        self._responsive_geometry_timer = QTimer(self)
        self._responsive_geometry_timer.setSingleShot(True)
        self._responsive_geometry_timer.setInterval(80)
        self._responsive_geometry_timer.timeout.connect(self._apply_responsive_shell_geometry)

        self.setWindowTitle("Document Viewer")
        self.surface = setup_dialog_shell(
            self,
            shell_object_name="UploadWorkspaceDialog",
            surface_object_name="UploadWorkspaceSurface",
            use_masked_shell=True,
            fit_to_content=False,
            surface_min_width=900,
            surface_min_height=640,
            responsive_margins=(96, 48),
            responsive_width_ratio=0.82,
            responsive_height_ratio=0.84,
            responsive_fill_parent=True,
        )
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.surface.setLayout(root)
        self.preview_widget = DocumentPreviewWidget(
            file_path,
            parent=self.surface,
            show_header=True,
            close_callback=self.accept,
        )
        root.addWidget(self.preview_widget)
        self._ensure_screen_tracking()
        self._apply_responsive_shell_geometry()

    def __getattr__(self, name):
        preview = self.__dict__.get("preview_widget")
        if preview is not None and hasattr(preview, name):
            return getattr(preview, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        preview = self.__dict__.get("preview_widget")
        if preview is not None and name in self._PREVIEW_DELEGATED_ATTRS:
            setattr(preview, name, value)
            return
        super().__setattr__(name, value)

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
        return parent.window() if parent is not None else None

    def _parent_container(self):
        return self.parentWidget()

    def _screen_for_widget(self, widget):
        if not _widget_alive(widget):
            return None
        rect = widget.rect()
        if rect.isValid() and not rect.isEmpty():
            screen = QApplication.screenAt(widget.mapToGlobal(rect.center()))
            if screen is not None:
                return screen
        window_handle = widget.windowHandle()
        return window_handle.screen() if window_handle is not None else None

    def _responsive_screen(self):
        for widget in (self._parent_container(), self._parent_window(), self):
            screen = self._screen_for_widget(widget)
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
                current.availableGeometryChanged.disconnect(self._on_screen_geometry_changed)
            except (TypeError, RuntimeError):
                pass
        self._active_screen = screen
        if _widget_alive(screen):
            try:
                screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)
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
        if timer is not None:
            timer.start()

    def _apply_responsive_shell_geometry(self):
        if not _widget_alive(getattr(self, "surface", None)):
            return
        sizer = getattr(self.surface, "_dialog_surface_sizer", None)
        if sizer is not None:
            sizer.apply()

    def _clear_screen_tracking(self):
        parent_window = getattr(self, "_tracked_parent_window", None)
        if _widget_alive(parent_window):
            parent_window.removeEventFilter(self)
        self._tracked_parent_window = None

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_tracked_parent_window", None):
            if event.type() in {QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show}:
                self._ensure_screen_tracking()
                self._schedule_responsive_shell_geometry()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        preview = getattr(self, "preview_widget", None)
        if (
            preview is not None
            and preview._preview_item is not None
            and preview._preview_zoom_mode in {"fit_window", "fit_width"}
        ):
            preview._apply_preview_zoom()

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_screen_tracking()
        self._schedule_responsive_shell_geometry()
        if self.preview_widget._preview_item is not None:
            QTimer.singleShot(0, self.preview_widget._apply_preview_zoom)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._ensure_screen_tracking()
        self._schedule_responsive_shell_geometry()

    def closeEvent(self, event):
        self._clear_screen_tracking()
        self.preview_widget._is_closing = True
        self.preview_widget.close_document()
        super().closeEvent(event)

    def accept(self):
        self._clear_screen_tracking()
        self.preview_widget._is_closing = True
        self.preview_widget.close_document()
        accept = getattr(super(), "accept", None)
        if callable(accept):
            accept()
            return
        self.done(self.Accepted)

    def reject(self):
        self._clear_screen_tracking()
        self.preview_widget._is_closing = True
        self.preview_widget.close_document()
        reject = getattr(super(), "reject", None)
        if callable(reject):
            reject()
            return
        self.done(self.Rejected)

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key_Plus, Qt.Key_Minus, Qt.Key_0}:
            self.preview_widget.keyPressEvent(event)
        elif event.key() == Qt.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)
