from copy import deepcopy

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.foundation import (
    SmoothScrollDelegate,
    create_button,
    create_check_box,
    create_scroll_area,
    create_search_edit,
    tune_fluent_scrollable,
)
from utils.language_helper import ui_text as tr


class EditableCanvasState:
    def __init__(
        self,
        zoom=1.0,
        min_zoom=0.4,
        max_zoom=2.5,
        zoom_step=0.1,
        base_grid_size=96,
        min_grid_size=24,
        max_grid_size=240,
    ):
        self.zoom = float(zoom)
        self.min_zoom = float(min_zoom)
        self.max_zoom = float(max_zoom)
        self.zoom_step = float(zoom_step)
        self.base_grid_size = int(base_grid_size)
        self.min_grid_size = int(min_grid_size)
        self.max_grid_size = int(max_grid_size)
        self.grid_visible = True

    def set_zoom(self, value):
        self.zoom = max(self.min_zoom, min(self.max_zoom, float(value)))
        return self.zoom

    def zoom_in(self):
        return self.set_zoom(self.zoom + self.zoom_step)

    def zoom_out(self):
        return self.set_zoom(self.zoom - self.zoom_step)

    def reset_zoom(self):
        return self.set_zoom(1.0)

    def fit_width_zoom(self, viewport_width, content_width, padding=36):
        usable_width = max(1, int(viewport_width) - int(padding))
        content_width = max(1, int(content_width))
        return self.set_zoom(usable_width / content_width)

    def set_grid_visible(self, visible):
        self.grid_visible = bool(visible)
        return self.grid_visible

    def set_grid_size(self, value):
        try:
            grid_size = int(value)
        except (TypeError, ValueError):
            grid_size = self.base_grid_size
        self.base_grid_size = max(
            self.min_grid_size,
            min(self.max_grid_size, grid_size),
        )
        return self.base_grid_size

    def scaled_grid_size(self):
        return int(self.base_grid_size * self.zoom)


class EditableCanvasScrollArea(QScrollArea):
    zoomRequested = Signal(float, QPoint)

    def __init__(self, parent=None, wheel_requires_control=True):
        super().__init__(parent)
        self._wheel_requires_control = wheel_requires_control
        self._canvas_interactions_enabled = True
        self._is_middle_panning = False
        self._last_pan_pos = QPoint()
        self.scrollDelegate = None
        self.setWidgetResizable(True)
        if SmoothScrollDelegate is not None:
            self.scrollDelegate = SmoothScrollDelegate(self)
            tune_fluent_scrollable(self)
        self.viewport().installEventFilter(self)

    def set_canvas_interactions_enabled(self, enabled):
        self._canvas_interactions_enabled = bool(enabled)
        if not enabled:
            self._stop_middle_pan()

    def eventFilter(self, watched, event):
        if watched == self.viewport():
            if self._handle_viewport_event(event):
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if not self._handle_wheel_zoom(event):
            super().wheelEvent(event)

    def _handle_viewport_event(self, event):
        event_type = event.type()
        if event_type == QEvent.Type.Wheel:
            return self._handle_wheel_zoom(event)
        if (
            event_type == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MiddleButton
        ):
            return self._start_middle_pan(event)
        if event_type == QEvent.Type.MouseMove and self._is_middle_panning:
            return self._continue_middle_pan(event)
        if (
            event_type == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MiddleButton
            and self._is_middle_panning
        ):
            self._stop_middle_pan()
            event.accept()
            return True
        return False

    def _handle_wheel_zoom(self, event):
        if not self._canvas_interactions_enabled:
            return False
        if (
            self._wheel_requires_control
            and not event.modifiers() & Qt.ControlModifier
        ):
            return False
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            return False
        factor = 1.25 if delta > 0 else 0.8
        self.zoomRequested.emit(factor, event.position().toPoint())
        event.accept()
        return True

    def _start_middle_pan(self, event):
        if not self._canvas_interactions_enabled:
            return False
        self._is_middle_panning = True
        self._last_pan_pos = event.position().toPoint()
        self.viewport().setCursor(Qt.ClosedHandCursor)
        event.accept()
        return True

    def _continue_middle_pan(self, event):
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
        return True

    def _stop_middle_pan(self):
        if not self._is_middle_panning:
            return
        self._is_middle_panning = False
        self.viewport().unsetCursor()


class EditableCanvasControls(QWidget):
    zoomOutRequested = Signal()
    zoomResetRequested = Signal()
    zoomInRequested = Signal()
    zoomFitRequested = Signal()
    gridVisibleChanged = Signal(bool)
    gridSizeChanged = Signal(int)

    def __init__(
        self,
        parent=None,
        show_grid=False,
        grid_min=56,
        grid_max=180,
        grid_step=8,
        grid_value=96,
        grid_suffix=None,
    ):
        super().__init__(parent)
        self.setObjectName("EditableCanvasControls")
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setLayout(layout)

        self.zoom_out_btn = create_button("-", "secondary")
        self.zoom_reset_btn = create_button("100%", "secondary")
        self.zoom_in_btn = create_button("+", "secondary")
        self.zoom_fit_btn = create_button(tr("workspace_zoom_fit"), "secondary")
        for button in (
            self.zoom_out_btn,
            self.zoom_reset_btn,
            self.zoom_in_btn,
            self.zoom_fit_btn,
        ):
            button.setFixedHeight(30)
            layout.addWidget(button)

        self.zoom_out_btn.clicked.connect(
            lambda checked=False: self.zoomOutRequested.emit()
        )
        self.zoom_reset_btn.clicked.connect(
            lambda checked=False: self.zoomResetRequested.emit()
        )
        self.zoom_in_btn.clicked.connect(
            lambda checked=False: self.zoomInRequested.emit()
        )
        self.zoom_fit_btn.clicked.connect(
            lambda checked=False: self.zoomFitRequested.emit()
        )

        self.grid_toggle = None
        self.grid_size_spin = None
        if show_grid:
            self.grid_toggle = create_check_box(
                tr("workspace_show_grid"),
                "WorkspaceGridToggle",
            )
            self.grid_toggle.setChecked(True)
            self.grid_toggle.toggled.connect(self.gridVisibleChanged.emit)
            layout.addWidget(self.grid_toggle)

            self.grid_size_spin = QSpinBox()
            self.grid_size_spin.setObjectName("WorkspaceGridSizeSpin")
            self.grid_size_spin.setRange(grid_min, grid_max)
            self.grid_size_spin.setSingleStep(grid_step)
            self.grid_size_spin.setValue(grid_value)
            self.grid_size_spin.setSuffix(
                f" {grid_suffix or tr('workspace_grid_px')}"
            )
            self.grid_size_spin.valueChanged.connect(self.gridSizeChanged.emit)
            layout.addWidget(self.grid_size_spin)

    def set_zoom_percent(self, value):
        self.zoom_reset_btn.setText(f"{round(float(value) * 100)}%")

    def retranslate_ui(self):
        self.zoom_fit_btn.setText(tr("workspace_zoom_fit"))
        if self.grid_toggle is not None:
            self.grid_toggle.setText(tr("workspace_show_grid"))
        if self.grid_size_spin is not None:
            self.grid_size_spin.setSuffix(f" {tr('workspace_grid_px')}")


class EditableBlockLibraryPanel(QWidget):
    blockAddRequested = Signal(str)

    def __init__(
        self,
        categories,
        label_for_type,
        button_factory,
        title_text,
        hint_text,
        search_placeholder,
        empty_text,
        parent=None,
    ):
        super().__init__(parent)
        self.categories = categories
        self.label_for_type = label_for_type
        self.button_factory = button_factory
        self.empty_text = empty_text

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.setLayout(root)

        header = QVBoxLayout()
        header.setContentsMargins(0, 6, 0, 0)
        header.setSpacing(2)
        self.title_label = QLabel(title_text)
        self.title_label.setObjectName("WorkspacePanelTitle")
        self.hint_label = QLabel(hint_text)
        self.hint_label.setObjectName("WorkspacePanelHint")
        self.hint_label.setWordWrap(True)
        header.addWidget(self.title_label)
        header.addWidget(self.hint_label)
        root.addLayout(header)

        self.search = create_search_edit(search_placeholder)
        self.search.textChanged.connect(self.refresh)
        root.addWidget(self.search)

        self.scroll = create_scroll_area("WorkspacePaletteScroll", transparent=True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        self.body.setLayout(self.body_layout)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, stretch=1)

    def set_texts(self, title_text, hint_text, search_placeholder, empty_text):
        self.title_label.setText(title_text)
        self.hint_label.setText(hint_text)
        self.search.setPlaceholderText(search_placeholder)
        self.empty_text = empty_text

    def refresh(self):
        query = self.search.text().strip().lower()
        self._clear_layout(self.body_layout)
        shown = 0
        for category, block_types in self.categories.items():
            matching = [
                block_type
                for block_type in block_types
                if (
                    not query
                    or query in category.lower()
                    or query in block_type.lower()
                    or query in self.label_for_type(block_type).lower()
                )
            ]
            if not matching:
                continue
            label = QLabel(category)
            label.setObjectName("WorkspacePaletteCategory")
            self.body_layout.addWidget(label)
            for block_type in matching:
                button = self.button_factory(block_type)
                button.addRequested.connect(self.blockAddRequested.emit)
                self.body_layout.addWidget(button)
                shown += 1
        if shown == 0:
            empty = QLabel(self.empty_text)
            empty.setObjectName("MutedText")
            empty.setWordWrap(True)
            self.body_layout.addWidget(empty)
        self.body_layout.addStretch()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)


class FreeLayoutEditSession:
    def __init__(
        self,
        canvas_width,
        padding=24,
        spacing=12,
        block_key=None,
        block_tab=None,
        rect_for_block=None,
        layout_from_rect=None,
        bound_rect=None,
    ):
        self.canvas_width = canvas_width
        self.padding = padding
        self.spacing = spacing
        self.block_key = block_key or (
            lambda block: block.get("type") or block.get("id")
        )
        self.block_tab = block_tab or (
            lambda block: block.get("tab", "overview")
        )
        self.rect_for_block = rect_for_block
        self.layout_from_rect = layout_from_rect
        self.bound_rect = bound_rect or (lambda rect: QRect(rect))
        self.edit_payload = None
        self.preview_payload = None
        self.drag_base_payload = None

    def set_payload(self, payload):
        self.edit_payload = deepcopy(payload) if payload else None
        self.preview_payload = None
        self.drag_base_payload = None

    def set_drag_base(self, payload):
        self.drag_base_payload = deepcopy(payload) if payload else None

    def current_payload(self):
        return self.preview_payload or self.edit_payload

    def block_for_section(self, section_key, payload=None):
        payload = payload or self.current_payload() or {}
        for block in payload.get("blocks", []):
            if self.block_key(block) == section_key:
                return block
        return None

    def preview(self, section_key, rect, source_payload=None):
        if self.rect_for_block is None or self.layout_from_rect is None:
            return None
        source = (
            source_payload
            or self.drag_base_payload
            or self.edit_payload
        )
        if not source:
            return None
        self.preview_payload = deepcopy(source)
        block = self.block_for_section(section_key, self.preview_payload)
        if block is None:
            self.preview_payload = None
            return None

        bounded = self.bound_rect(QRect(rect))
        block["free_layout"] = self.layout_from_rect(bounded)
        self.resolve_overlaps(self.block_tab(block), section_key, self.preview_payload)
        return self.preview_payload

    def resolve_overlaps(self, tab_key, moving_section_key, payload=None):
        if self.rect_for_block is None or self.layout_from_rect is None:
            return
        payload = payload or self.preview_payload or self.edit_payload
        if not payload:
            return
        tab_blocks = [
            block
            for block in payload.get("blocks", [])
            if self.block_tab(block) == tab_key
        ]
        rects = {
            self.block_key(block): self.rect_for_block(block)
            for block in tab_blocks
        }
        if moving_section_key not in rects:
            return

        resolved_rects = resolve_overlapping_free_rects(
            rects,
            moving_section_key,
            self.canvas_width,
            padding=self.padding,
            spacing=self.spacing,
        )
        for block in tab_blocks:
            section_key = self.block_key(block)
            if section_key == moving_section_key:
                continue
            resolved = resolved_rects.get(section_key)
            original = rects.get(section_key)
            if resolved is None or original is None or resolved == original:
                continue
            block["free_layout"] = self.layout_from_rect(self.bound_rect(resolved))

    def commit(self):
        if self.preview_payload is not None:
            self.edit_payload = self.preview_payload
        self.preview_payload = None
        self.drag_base_payload = None
        return self.edit_payload

    def rebound(self):
        self.preview_payload = None
        self.drag_base_payload = None
        return self.edit_payload


class GridLayoutEditSession:
    def __init__(self, block_key=None):
        self.block_key = block_key or (lambda block: block.get("id"))
        self.snapshot_blocks = None

    def begin(self, blocks):
        if self.snapshot_blocks is None:
            self.snapshot_blocks = deepcopy(blocks or [])

    def has_snapshot(self):
        return self.snapshot_blocks is not None

    def preview_block(self, blocks, block_id, layout):
        updated = []
        for block in blocks or []:
            next_block = deepcopy(block)
            if self.block_key(next_block) == block_id:
                next_block["layout"] = deepcopy(layout)
            updated.append(next_block)
        return updated

    def preview_many(self, blocks, layouts_by_id):
        updated = []
        layouts_by_id = layouts_by_id or {}
        for block in blocks or []:
            next_block = deepcopy(block)
            block_id = self.block_key(next_block)
            if block_id in layouts_by_id:
                next_block["layout"] = deepcopy(layouts_by_id[block_id])
            updated.append(next_block)
        return updated

    def commit(self):
        snapshot = self.snapshot_blocks
        self.snapshot_blocks = None
        return snapshot

    def rebound(self):
        snapshot = self.snapshot_blocks
        self.snapshot_blocks = None
        return deepcopy(snapshot) if snapshot is not None else None


class EditableCanvasEditorKit:
    def __init__(
        self,
        state=None,
        state_kwargs=None,
        parent=None,
    ):
        self.parent = parent
        self.state = state or EditableCanvasState(**(state_kwargs or {}))
        self.controls = None
        self.scroll = None
        self.block_library = None
        self.free_layout_session = None
        self.grid_layout_session = None

    def create_controls(self, **kwargs):
        self.controls = EditableCanvasControls(parent=self.parent, **kwargs)
        self.controls.set_zoom_percent(self.state.zoom)
        return self.controls

    def create_scroll_area(self, **kwargs):
        self.scroll = EditableCanvasScrollArea(parent=self.parent, **kwargs)
        return self.scroll

    def create_block_library(self, *args, **kwargs):
        self.block_library = EditableBlockLibraryPanel(*args, parent=self.parent, **kwargs)
        return self.block_library

    def create_free_layout_session(self, *args, **kwargs):
        self.free_layout_session = FreeLayoutEditSession(*args, **kwargs)
        return self.free_layout_session

    def create_grid_layout_session(self, *args, **kwargs):
        self.grid_layout_session = GridLayoutEditSession(*args, **kwargs)
        return self.grid_layout_session


def resolve_overlapping_free_rects(
    rects,
    moving_key,
    canvas_width,
    padding=24,
    spacing=12,
):
    if moving_key not in rects:
        return {key: QRect(rect) for key, rect in rects.items()}

    resolved = {key: QRect(rect) for key, rect in rects.items()}
    moving_rect = QRect(resolved[moving_key])
    placed = [(moving_key, moving_rect)]

    ordered = sorted(
        (
            (key, QRect(rect))
            for key, rect in resolved.items()
            if key != moving_key
        ),
        key=lambda item: (item[1].y(), item[1].x()),
    )
    for key, rect in ordered:
        candidate = QRect(rect)
        for _, placed_rect in placed:
            if not candidate.intersects(placed_rect):
                continue
            candidate.moveTop(placed_rect.bottom() + spacing)
            max_x = max(padding, canvas_width - candidate.width() - padding)
            candidate.moveLeft(max(padding, min(candidate.x(), max_x)))
        resolved[key] = candidate
        placed.append((key, candidate))
    return resolved


def align_rect_to_peer(rect, peer_rects, edge, bounds=None):
    if edge not in {"left", "right", "top", "bottom", "center", "middle"}:
        return QRect(rect), False
    peers = [QRect(peer) for peer in peer_rects]
    if not peers:
        return QRect(rect), False

    aligned = QRect(rect)
    if edge in {"left", "right", "center"}:
        offset = {
            "left": 0,
            "right": aligned.width(),
            "center": aligned.width() / 2,
        }[edge]
        current_value = aligned.x() + offset
        peer_values = [
            {
                "left": peer.x(),
                "right": peer.x() + peer.width(),
                "center": peer.x() + (peer.width() / 2),
            }[edge]
            for peer in peers
        ]
        target_value = min(peer_values, key=lambda value: abs(value - current_value))
        aligned.moveLeft(round(target_value - offset))
    else:
        offset = {
            "top": 0,
            "bottom": aligned.height(),
            "middle": aligned.height() / 2,
        }[edge]
        current_value = aligned.y() + offset
        peer_values = [
            {
                "top": peer.y(),
                "bottom": peer.y() + peer.height(),
                "middle": peer.y() + (peer.height() / 2),
            }[edge]
            for peer in peers
        ]
        target_value = min(peer_values, key=lambda value: abs(value - current_value))
        aligned.moveTop(round(target_value - offset))

    if bounds is not None:
        bounded = QRect(bounds)
        aligned.moveLeft(
            max(bounded.left(), min(aligned.left(), bounded.right() - aligned.width() + 1))
        )
        aligned.moveTop(max(bounded.top(), min(aligned.top(), bounded.bottom() - aligned.height() + 1)))
    return aligned, aligned != rect
