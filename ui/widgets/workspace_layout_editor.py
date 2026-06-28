from copy import deepcopy
from uuid import uuid4
from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRubberBand,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.workspace_service import new_block
from services.workspace_layout import (
    WORKSPACE_GRID_COLUMNS,
    first_available_layout,
    normalize_workspace_layout,
    update_block_layout,
    validate_block_layout,
)
from utils.language_helper import ui_text as tr


CANVAS_OUTER = "#FBFBFC"
CANVAS_SURFACE = "#FFFFFF"
GRID_MINOR = "#ECECEC"
GRID_MAJOR = "#DADADF"
GRID_EDGE = "#9BE3E6"
ACCENT_TEAL = "#0EA5AC"
ACCENT_TEAL_SOFT = QColor(14, 165, 172, 28)
ACCENT_GROUP = "#7A6EEC"
ACCENT_GROUP_SOFT = QColor(122, 110, 236, 30)
ACCENT_WARNING = "#D97706"
ACCENT_WARNING_SOFT = QColor(217, 119, 6, 30)
SELECTION_MUTED = "#A1A1AA"
DARK_CHIP = "#18181B"
WHITE = "#FFFFFF"
HIDDEN_OVERLAY = QColor(251, 251, 252, 180)


def _event_position(event):
    return event.position().toPoint() if hasattr(event, "position") else event.pos()


def _event_global_position(event):
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


class WorkspacePaletteButton(QFrame):
    addRequested = Signal(str)

    def __init__(self, block_type, label, parent=None):
        super().__init__(parent)
        self.block_type = block_type
        self._drag_start = QPoint()
        self._dragging = False
        self.setObjectName("WorkspacePaletteButton")
        self.setCursor(Qt.OpenHandCursor)
        self.setMinimumHeight(46)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(1)
        self.setLayout(layout)

        title = QLabel(label, self)
        title.setObjectName("StrongText")
        title.setWordWrap(True)
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        hint = QLabel("Click to add or drag to canvas", self)
        hint.setObjectName("MutedText")
        hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(title)
        layout.addWidget(hint)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = _event_global_position(event)
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.LeftButton:
            return
        if (_event_global_position(event) - self._drag_start).manhattanLength() < 8:
            return
        self._dragging = True
        drag = QDrag(self)
        data = QMimeData()
        data.setData("application/x-workspace-block-type", self.block_type.encode("utf-8"))
        drag.setMimeData(data)
        drag.exec(Qt.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._dragging:
            self.addRequested.emit(self.block_type)
            event.accept()
            return
        self._dragging = False
        super().mouseReleaseEvent(event)


class WorkspaceCanvasSurface(QFrame):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setObjectName("WorkspaceCanvasSurface")
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(920, 560)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._marquee_origin = QPoint()
        self._marquee_additive = False
        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.editor.canvas_rect()
        painter.fillRect(self.rect(), QColor(CANVAS_OUTER))
        painter.fillRect(rect, QColor(CANVAS_SURFACE))

        minor_pen = QPen(QColor(GRID_MINOR))
        major_pen = QPen(QColor(GRID_MAJOR))
        cell_width = self.editor.cell_width()
        for col in range(WORKSPACE_GRID_COLUMNS + 1):
            x = int(rect.left() + col * cell_width)
            painter.setPen(major_pen if col in (0, WORKSPACE_GRID_COLUMNS) else minor_pen)
            painter.drawLine(x, rect.top(), x, rect.bottom())
        rows = max(10, int(rect.height() / self.editor.row_height) + 1)
        for row in range(rows + 1):
            y = rect.top() + row * self.editor.row_height
            painter.setPen(major_pen if row == 0 else minor_pen)
            painter.drawLine(rect.left(), y, rect.right(), y)

        painter.setPen(QPen(QColor(GRID_EDGE), 2))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        alignment_guides = self.editor.alignment_guides
        if alignment_guides.get("vertical") or alignment_guides.get("horizontal"):
            painter.setRenderHint(QPainter.Antialiasing, False)
            guide_pen = QPen(QColor(ACCENT_GROUP), 2, Qt.DashLine)
            painter.setPen(guide_pen)
            for col in alignment_guides.get("vertical", []):
                x = int(rect.left() + (col * cell_width))
                painter.drawLine(x, rect.top(), x, rect.bottom())
            for row in alignment_guides.get("horizontal", []):
                y = int(rect.top() + (row * self.editor.row_height))
                painter.drawLine(rect.left(), y, rect.right(), y)

        guide_layout = self.editor.placement_guide_layout
        if guide_layout:
            guide_rect = self.editor.layout_to_rect(guide_layout)
            adjusted = self.editor.placement_guide_status == "adjusted"
            snapped = self.editor.placement_guide_status == "snapped"
            accent = (
                QColor(ACCENT_WARNING)
                if adjusted
                else QColor(ACCENT_GROUP)
                if snapped
                else QColor(ACCENT_TEAL)
            )
            fill = (
                ACCENT_WARNING_SOFT
                if adjusted
                else ACCENT_GROUP_SOFT
                if snapped
                else ACCENT_TEAL_SOFT
            )
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setBrush(QBrush(fill))
            painter.setPen(QPen(accent, 2, Qt.DashLine))
            painter.drawRoundedRect(guide_rect.adjusted(1, 1, -2, -2), 12, 12)

            chip = (
                f"R{guide_layout['row'] + 1} C{guide_layout['col'] + 1} "
                f"{guide_layout['col_span']}x{guide_layout['row_span']}"
            )
            chip_rect = QRect(
                guide_rect.left(),
                max(rect.top(), guide_rect.top() - 26),
                116,
                22,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(chip_rect, 8, 8)
            painter.setPen(QColor(WHITE))
            painter.drawText(chip_rect, Qt.AlignCenter, chip)

            if adjusted:
                note_rect = QRect(chip_rect.right() + 6, chip_rect.top(), 138, 22)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(DARK_CHIP))
                painter.drawRoundedRect(note_rect, 8, 8)
                painter.setPen(QColor(WHITE))
                painter.drawText(note_rect, Qt.AlignCenter, "Moved to open spot")

            dimensions = (
                f"{guide_layout['col_span']} columns x "
                f"{guide_layout['row_span']} rows"
            )
            dimensions_rect = QRect(
                guide_rect.right() - 146,
                min(rect.bottom() - 24, guide_rect.bottom() + 6),
                146,
                22,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(DARK_CHIP))
            painter.drawRoundedRect(dimensions_rect, 8, 8)
            painter.setPen(QColor(WHITE))
            painter.drawText(dimensions_rect, Qt.AlignCenter, dimensions)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-workspace-block-type"):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-workspace-block-type"):
            block_type = bytes(
                event.mimeData().data("application/x-workspace-block-type")
            ).decode("utf-8")
            row, col = self.editor.position_to_grid(_event_position(event))
            self.editor.preview_new_block(block_type, row=row, col=col)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.editor.clear_placement_guide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-workspace-block-type"):
            super().dropEvent(event)
            return
        block_type = bytes(
            event.mimeData().data("application/x-workspace-block-type")
        ).decode("utf-8")
        row, col = self.editor.position_to_grid(_event_position(event))
        self.editor.clear_placement_guide()
        self.editor.add_block_at(block_type, row=row, col=col)
        event.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            child = self.childAt(_event_position(event))
            if child is None or child is self:
                self._marquee_origin = _event_position(event)
                self._marquee_additive = bool(event.modifiers() & Qt.ControlModifier)
                self._rubber_band.setGeometry(QRect(self._marquee_origin, self._marquee_origin))
                self._rubber_band.show()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._rubber_band.isVisible():
            self._rubber_band.setGeometry(
                QRect(self._marquee_origin, _event_position(event)).normalized()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._rubber_band.isVisible():
            rect = self._rubber_band.geometry()
            self._rubber_band.hide()
            if rect.width() > 6 or rect.height() > 6:
                self.editor.select_blocks_in_rect(rect, additive=self._marquee_additive)
            elif not self._marquee_additive:
                self.editor.select_block(None)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class WorkspaceLayoutTile(QFrame):
    def __init__(self, block, label, editor):
        super().__init__(editor.surface)
        self.block = block
        self.editor = editor
        self._drag_start = QPoint()
        self._drag_start_global = QPoint()
        self._start_layout = None
        self._start_group_layouts = {}
        self._mode = None
        self._hover_handle = None
        self.setObjectName("WorkspaceLayoutTile")
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)
        self.setLayout(layout)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        title = QLabel(block.get("title") or tr("workspace_title"), self)
        title.setObjectName("WorkspaceTileTitle")
        title.setWordWrap(True)
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        top.addWidget(title, stretch=1)
        for text, callback in (
            ("Edit", lambda: editor.request_edit(block.get("id"))),
            ("Copy", lambda: editor.duplicate_block(block.get("id"))),
            ("Front", lambda: editor.move_block_layer(block.get("id"), 1)),
            ("Back", lambda: editor.move_block_layer(block.get("id"), -1)),
            ("Del", lambda: editor.delete_block(block.get("id"))),
        ):
            button = QPushButton(text, self)
            button.setObjectName("WorkspaceTileEditButton")
            button.setFixedHeight(24)
            button.clicked.connect(callback)
            top.addWidget(button)
            button.setVisible(block.get("id") == editor.selected_block_id)
        layout.addLayout(top)

        summary = QLabel(label, self)
        summary.setObjectName("MutedText")
        summary.setWordWrap(True)
        summary.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(summary)

        preview = QWidget(self)
        preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(0, 4, 0, 0)
        preview_layout.setSpacing(4)
        preview.setLayout(preview_layout)
        self._add_preview_lines(preview_layout)
        layout.addWidget(preview, stretch=1)

        chip = QLabel(
            f"{validate_block_layout(block)['col_span']}x{validate_block_layout(block)['row_span']}",
            self,
        )
        chip.setObjectName("WorkspaceTileSizeChip")
        chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(chip, alignment=Qt.AlignLeft)

    def _add_preview_lines(self, layout):
        parent = layout.parentWidget()
        for text, kind in self.preview_lines():
            row = QLabel(text, parent)
            row.setObjectName("WorkspaceTilePreviewStrong" if kind == "strong" else "WorkspaceTilePreviewLine")
            row.setWordWrap(True)
            row.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            layout.addWidget(row)
        layout.addStretch()

    def preview_lines(self):
        block_type = self.block.get("type")
        if self.block.get("visible") is False:
            return [("Hidden on runtime workspace", "strong"), ("Use Layers to show it again", "line")]
        if block_type == "personal_info":
            fields = self.block.get("fields") or ["full_name", "nationality", "passport_number"]
            return [(field.replace("_", " ").title(), "line") for field in fields[:4]]
        if block_type == "document_viewer":
            doc_type = self.block.get("document_type") or "First available document"
            return [(doc_type.replace("_", " ").title(), "strong"), ("Embedded preview", "line")]
        if block_type == "web_viewer":
            return [(self.block.get("web_url") or "https://", "strong"), ("Embedded website", "line")]
        if block_type in {"documents", "document_checklist", "missing_documents"}:
            return [("Passport", "line"), ("Photo", "line"), ("Stage documents", "line")]
        if block_type in {"workflow", "workflow_next_steps"}:
            return [("Current stage", "strong"), ("Next actions", "line"), ("Status update", "line")]
        if block_type in {"open_tasks", "task_board"}:
            return [("High priority task", "strong"), ("Due soon", "line"), ("Assigned work", "line")]
        if block_type == "quick_actions":
            actions = (self.block.get("settings") or {}).get("actions") or ["add_task", "open_folder"]
            return [(action.replace("_", " ").title(), "line") for action in actions[:4]]
        if block_type == "link_list":
            links = (self.block.get("settings") or {}).get("links") or []
            if links:
                return [(link.get("label") or link.get("url") or "Link", "line") for link in links[:4]]
            return [("Add useful links", "line")]
        if block_type == "appointments":
            return [("Interpol appointment", "line"), ("Biometric appointment", "line")]
        if block_type == "status_summary":
            return [("Stage + missing docs", "strong"), ("Open tasks", "line")]
        if block_type == "recent_activity":
            return [("Recent uploads", "line"), ("Task updates", "line")]
        if block_type == "contact_info":
            return [("Email", "line"), ("Phone", "line"), ("Folder path", "line")]
        if block_type in {"notes", "notes_editor"}:
            return [("Missionary notes", "line"), ("Editable text", "line")]
        if block_type == "residency_timeline":
            return [("Residency events", "line"), ("Expiration dates", "line")]
        return [("Workspace block", "line")]

    def resize_handle(self, pos):
        margin = 14
        left = pos.x() <= margin
        right = pos.x() >= self.width() - margin
        top = pos.y() <= margin
        bottom = pos.y() >= self.height() - margin
        if top and left:
            return "nw"
        if top and right:
            return "ne"
        if bottom and left:
            return "sw"
        if bottom and right:
            return "se"
        if left:
            return "w"
        if right:
            return "e"
        if top:
            return "n"
        if bottom:
            return "s"
        return None

    def cursor_for_handle(self, handle):
        if handle in {"nw", "se"}:
            return Qt.SizeFDiagCursor
        if handle in {"ne", "sw"}:
            return Qt.SizeBDiagCursor
        if handle in {"e", "w"}:
            return Qt.SizeHorCursor
        if handle in {"n", "s"}:
            return Qt.SizeVerCursor
        return Qt.OpenHandCursor

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        selected = self.block.get("id") in self.editor.selected_block_ids
        hidden = self.block.get("visible") is False
        locked = bool(self.block.get("locked"))
        if hidden:
            painter.fillRect(self.rect(), HIDDEN_OVERLAY)
        color = QColor(ACCENT_TEAL) if selected else QColor(SELECTION_MUTED)
        painter.setPen(QPen(color, 2, Qt.DashLine if hidden else Qt.SolidLine))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 12, 12)
        if locked or hidden:
            badges = []
            if locked:
                badges.append("Locked")
            if hidden:
                badges.append("Hidden")
            badge_text = " / ".join(badges)
            badge_rect = QRect(self.width() - 112, self.height() - 30, 100, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(DARK_CHIP))
            painter.drawRoundedRect(badge_rect, 8, 8)
            painter.setPen(QColor(WHITE))
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
        if selected:
            painter.setPen(Qt.NoPen)
            handles = {
                "nw": (4, 4),
                "n": (self.width() // 2 - 5, 4),
                "ne": (self.width() - 14, 4),
                "w": (4, self.height() // 2 - 5),
                "e": (self.width() - 14, self.height() // 2 - 5),
                "sw": (4, self.height() - 14),
                "s": (self.width() // 2 - 5, self.height() - 14),
                "se": (self.width() - 14, self.height() - 14),
            }
            active_handle = self._mode if self._mode != "move" else self._hover_handle
            for handle, (x, y) in handles.items():
                active = handle == active_handle
                size = 14 if active else 10
                offset = 2 if active else 0
                painter.setBrush(
                    QColor(ACCENT_GROUP) if active else QColor(ACCENT_TEAL)
                )
                painter.drawRoundedRect(
                    QRect(x - offset, y - offset, size, size),
                    5,
                    5,
                )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            block_id = self.block.get("id")
            additive = bool(event.modifiers() & Qt.ControlModifier)
            self.editor.select_block_for_drag(block_id, additive=additive)
            if self.block.get("locked"):
                self.editor._set_interaction_state(verb="Locked block")
                event.accept()
                return
            self._drag_start = _event_position(event)
            self._drag_start_global = _event_global_position(event)
            self._start_layout = validate_block_layout(self.block)
            self._start_group_layouts = {
                selected.get("id"): validate_block_layout(selected)
                for selected in self.editor._selected_blocks()
                if selected.get("id") and not selected.get("locked")
            }
            self._mode = self.resize_handle(self._drag_start) or "move"
            self.editor.begin_interaction()
            self.setCursor(self.cursor_for_handle(self._mode) if self._mode != "move" else Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.LeftButton or not self._start_layout:
            handle = self.resize_handle(_event_position(event))
            if handle != self._hover_handle:
                self._hover_handle = handle
                self.update()
            self.setCursor(self.cursor_for_handle(handle))
            return
        delta = _event_global_position(event) - self._drag_start_global
        if self._mode != "move":
            col_delta = round(delta.x() / max(1, self.editor.cell_width()))
            row_delta = round(delta.y() / max(1, self.editor.row_height))
            layout = dict(self._start_layout)
            if "e" in self._mode:
                layout["col_span"] = max(1, self._start_layout["col_span"] + col_delta)
            if "s" in self._mode:
                layout["row_span"] = max(1, self._start_layout["row_span"] + row_delta)
            if "w" in self._mode:
                next_col = max(0, self._start_layout["col"] + col_delta)
                right_edge = self._start_layout["col"] + self._start_layout["col_span"]
                layout["col"] = min(next_col, right_edge - 1)
                layout["col_span"] = max(1, right_edge - layout["col"])
            if "n" in self._mode:
                next_row = max(0, self._start_layout["row"] + row_delta)
                bottom_edge = self._start_layout["row"] + self._start_layout["row_span"]
                layout["row"] = min(next_row, bottom_edge - 1)
                layout["row_span"] = max(1, bottom_edge - layout["row"])
            self.editor.set_placement_guide(
                layout,
                block_id=self.block.get("id"),
                verb="Resize block",
            )
            self.editor.preview_layout(self.block.get("id"), **layout)
        else:
            col_delta = round(delta.x() / max(1, self.editor.cell_width()))
            row_delta = round(delta.y() / max(1, self.editor.row_height))
            layout = dict(self._start_layout)
            layout["col"] = max(0, self._start_layout["col"] + col_delta)
            layout["row"] = max(0, self._start_layout["row"] + row_delta)
            if len(self._start_group_layouts) > 1:
                self.editor.preview_selected_move(
                    self._start_group_layouts,
                    row_delta=row_delta,
                    col_delta=col_delta,
                    anchor_id=self.block.get("id"),
                )
                event.accept()
                return
            self.editor.set_placement_guide(
                layout,
                block_id=self.block.get("id"),
                verb="Move block",
            )
            self.editor.preview_layout(self.block.get("id"), **layout)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._mode:
            self.editor.commit_interaction()
            self.editor.clear_placement_guide()
            self._mode = None
            self._start_layout = None
            self._start_group_layouts = {}
            self._hover_handle = self.resize_handle(_event_position(event))
            self.setCursor(Qt.OpenHandCursor)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._mode is None and self._hover_handle is not None:
            self._hover_handle = None
            self.update()
        super().leaveEvent(event)


class WorkspaceLayoutEditor(QWidget):
    layoutChanged = Signal()
    blockSelected = Signal(str)
    editRequested = Signal(str)
    interactionChanged = Signal()

    def __init__(self, block_label_for_type, parent=None):
        super().__init__(parent)
        self.block_label_for_type = block_label_for_type
        self.workspace = None
        self.selected_block_id = None
        self.selected_block_ids = []
        self.zoom = 1.0
        self.base_row_height = 96
        self._undo_stack = []
        self._redo_stack = []
        self._interaction_snapshot = None
        self._clipboard_block = None
        self._clipboard_blocks = []
        self.placement_guide_layout = None
        self.placement_guide_status = "clear"
        self.alignment_guides = {"vertical": [], "horizontal": []}
        self.interaction_hint = "Ready"

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.setLayout(root)

        self.surface = WorkspaceCanvasSurface(self)
        self.setFocusPolicy(Qt.StrongFocus)
        root.addWidget(self.surface)

    def canvas_rect(self):
        margin = 28
        return self.surface.rect().adjusted(margin, margin, -margin, -margin)

    @property
    def row_height(self):
        return int(self.base_row_height * self.zoom)

    def cell_width(self):
        rect = self.canvas_rect()
        return max(1, rect.width() / WORKSPACE_GRID_COLUMNS)

    def set_zoom(self, value):
        self.zoom = max(0.6, min(1.6, float(value)))
        self.surface.setMinimumWidth(int(920 * self.zoom))
        self.render()

    def zoom_in(self):
        self.set_zoom(self.zoom + 0.1)

    def zoom_out(self):
        self.set_zoom(self.zoom - 0.1)

    def reset_zoom(self):
        self.set_zoom(1.0)

    def position_to_grid(self, pos):
        rect = self.canvas_rect()
        col = int((pos.x() - rect.left()) / self.cell_width())
        row = int((pos.y() - rect.top()) / self.row_height)
        return max(0, row), max(0, min(WORKSPACE_GRID_COLUMNS - 1, col))

    def snap_layout_to_alignment(self, layout, block_id=None, tolerance=1):
        if not self.workspace:
            return validate_block_layout({"layout": layout}), False
        target = validate_block_layout({"layout": layout})
        best_col = None
        best_col_distance = tolerance + 1
        best_row = None
        best_row_distance = tolerance + 1

        target_vertical = (
            ("left", target["col"], 0),
            ("center", target["col"] + (target["col_span"] / 2), target["col_span"] / 2),
            ("right", target["col"] + target["col_span"], target["col_span"]),
        )
        target_horizontal = (
            ("top", target["row"], 0),
            ("middle", target["row"] + (target["row_span"] / 2), target["row_span"] / 2),
            ("bottom", target["row"] + target["row_span"], target["row_span"]),
        )

        for block in self.workspace.get("blocks", []):
            if block.get("id") == block_id:
                continue
            other = validate_block_layout(block)
            other_vertical = (
                other["col"],
                other["col"] + (other["col_span"] / 2),
                other["col"] + other["col_span"],
            )
            other_horizontal = (
                other["row"],
                other["row"] + (other["row_span"] / 2),
                other["row"] + other["row_span"],
            )
            for _, target_value, offset in target_vertical:
                for other_value in other_vertical:
                    distance = abs(target_value - other_value)
                    if distance <= tolerance and distance < best_col_distance:
                        best_col_distance = distance
                        best_col = round(other_value - offset)
            for _, target_value, offset in target_horizontal:
                for other_value in other_horizontal:
                    distance = abs(target_value - other_value)
                    if distance <= tolerance and distance < best_row_distance:
                        best_row_distance = distance
                        best_row = round(other_value - offset)

        snapped = dict(target)
        if best_col is not None:
            snapped["col"] = max(
                0,
                min(WORKSPACE_GRID_COLUMNS - snapped["col_span"], best_col),
            )
        if best_row is not None:
            snapped["row"] = max(0, best_row)
        changed = snapped["col"] != target["col"] or snapped["row"] != target["row"]
        return snapped, changed

    def resolve_placement(self, layout, block_id=None):
        desired = validate_block_layout({"layout": layout})
        blocks = self.workspace.get("blocks", []) if self.workspace else []
        resolved = first_available_layout(
            blocks,
            desired,
            block_id=block_id,
            columns=WORKSPACE_GRID_COLUMNS,
        )
        adjusted = (
            resolved["row"] != desired["row"]
            or resolved["col"] != desired["col"]
        )
        return resolved, adjusted

    def is_block_locked(self, block_id):
        block = self._block(block_id)
        return bool(block and block.get("locked"))

    def unlocked_selected_ids(self):
        return [
            block_id
            for block_id in self.selected_block_ids
            if not self.is_block_locked(block_id)
        ]

    def set_selected_locked(self, locked=True):
        if not self.workspace or not self.selected_block_ids:
            return
        self._push_undo()
        selected_ids = set(self.selected_block_ids)
        for block in self.workspace.get("blocks", []):
            if block.get("id") in selected_ids:
                block["locked"] = bool(locked)
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def toggle_selected_locked(self):
        selected = self._selected_blocks()
        if not selected:
            return
        next_locked = not all(bool(block.get("locked")) for block in selected)
        self.set_selected_locked(next_locked)

    def set_selected_visible(self, visible=True):
        if not self.workspace or not self.selected_block_ids:
            return
        self._push_undo()
        selected_ids = set(self.selected_block_ids)
        for block in self.workspace.get("blocks", []):
            if block.get("id") in selected_ids:
                block["visible"] = bool(visible)
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def toggle_selected_visible(self):
        selected = self._selected_blocks()
        if not selected:
            return
        next_visible = all(block.get("visible") is False for block in selected)
        self.set_selected_visible(next_visible)

    def group_selected(self):
        selected = self._selected_blocks()
        if len(selected) < 2:
            return None
        self._push_undo()
        group_id = uuid4().hex
        selected_ids = {block.get("id") for block in selected}
        for block in self.workspace.get("blocks", []):
            if block.get("id") in selected_ids:
                block["group_id"] = group_id
        self._sync_source()
        self.layoutChanged.emit()
        self.render()
        return group_id

    def ungroup_selected(self):
        selected = self._selected_blocks()
        group_ids = {
            block.get("group_id")
            for block in selected
            if block.get("group_id")
        }
        if not group_ids:
            return False
        self._push_undo()
        for block in self.workspace.get("blocks", []):
            if block.get("group_id") in group_ids:
                block.pop("group_id", None)
        self._sync_source()
        self.layoutChanged.emit()
        self.render()
        return True

    def group_member_ids(self, block_id):
        block = self._block(block_id)
        group_id = block.get("group_id") if block else None
        if not group_id:
            return []
        return [
            candidate.get("id")
            for candidate in self.workspace.get("blocks", [])
            if candidate.get("group_id") == group_id and candidate.get("id")
        ]

    def calculate_alignment_guides(self, layout, block_id=None):
        if not self.workspace:
            return {"vertical": [], "horizontal": []}
        target = validate_block_layout({"layout": layout})
        target_vertical = {
            target["col"],
            target["col"] + target["col_span"],
            target["col"] + (target["col_span"] / 2),
        }
        target_horizontal = {
            target["row"],
            target["row"] + target["row_span"],
            target["row"] + (target["row_span"] / 2),
        }
        vertical = []
        horizontal = []
        for block in self.workspace.get("blocks", []):
            if block.get("id") == block_id:
                continue
            other = validate_block_layout(block)
            other_vertical = {
                other["col"],
                other["col"] + other["col_span"],
                other["col"] + (other["col_span"] / 2),
            }
            other_horizontal = {
                other["row"],
                other["row"] + other["row_span"],
                other["row"] + (other["row_span"] / 2),
            }
            vertical.extend(
                value
                for value in target_vertical
                if value in other_vertical and value not in vertical
            )
            horizontal.extend(
                value
                for value in target_horizontal
                if value in other_horizontal and value not in horizontal
            )
        return {
            "vertical": sorted(vertical),
            "horizontal": sorted(horizontal),
        }

    def _set_interaction_state(
        self,
        layout=None,
        block_id=None,
        adjusted=False,
        snapped=False,
        verb="Ready",
    ):
        self.alignment_guides = (
            self.calculate_alignment_guides(layout, block_id=block_id)
            if layout
            else {"vertical": [], "horizontal": []}
        )
        if layout:
            if adjusted:
                prefix = "Moved to open spot"
            elif snapped:
                prefix = "Snapped"
            else:
                prefix = verb
            self.interaction_hint = (
                f"{prefix}: R{layout['row'] + 1} C{layout['col'] + 1} "
                f"{layout['col_span']}x{layout['row_span']}"
            )
        else:
            self.interaction_hint = verb
        self.interactionChanged.emit()

    def preview_new_block(self, block_type, row=0, col=0):
        block = new_block(block_type)
        layout = validate_block_layout(block)
        layout.update({"row": row, "col": col})
        snapped_layout, snapped = self.snap_layout_to_alignment(layout)
        resolved, adjusted = self.resolve_placement(snapped_layout)
        self.placement_guide_layout = resolved
        self.placement_guide_status = "adjusted" if adjusted else "snapped" if snapped else "clear"
        self._set_interaction_state(
            resolved,
            adjusted=adjusted,
            snapped=snapped,
            verb="Place block",
        )
        self.surface.update()

    def set_placement_guide(self, layout, block_id=None, verb="Move block"):
        snapped_layout, snapped = self.snap_layout_to_alignment(layout, block_id=block_id)
        resolved, adjusted = self.resolve_placement(snapped_layout, block_id=block_id)
        self.placement_guide_layout = resolved
        self.placement_guide_status = "adjusted" if adjusted else "snapped" if snapped else "clear"
        self._set_interaction_state(
            resolved,
            block_id=block_id,
            adjusted=adjusted,
            snapped=snapped,
            verb=verb,
        )
        self.surface.update()

    def clear_placement_guide(self):
        if self.placement_guide_layout is None:
            return
        self.placement_guide_layout = None
        self.placement_guide_status = "clear"
        self._set_interaction_state(verb="Ready")
        self.surface.update()

    def add_block_at(self, block_type, row=0, col=0):
        if not self.workspace:
            return None
        self._push_undo()
        block = new_block(block_type)
        layout = validate_block_layout(block)
        layout.update({"row": row, "col": col})
        layout, _ = self.snap_layout_to_alignment(layout)
        layout, _ = self.resolve_placement(layout)
        block["layout"] = layout
        self.workspace.setdefault("blocks", []).append(block)
        self.workspace["blocks"] = update_block_layout(
            self.workspace.get("blocks", []), block.get("id"), layout
        )
        self.selected_block_id = block.get("id")
        self.selected_block_ids = [self.selected_block_id]
        self._sync_source()
        self.blockSelected.emit(self.selected_block_id or "")
        self.layoutChanged.emit()
        self.render()
        return block

    def request_edit(self, block_id):
        self.editRequested.emit(block_id or "")

    def _duplicate_payloads(self, source_blocks):
        group_map = {}
        duplicates = []
        for source in source_blocks:
            duplicate = deepcopy(source)
            fresh = new_block(duplicate.get("type", "personal_info"))
            duplicate["id"] = fresh["id"]
            duplicate["title"] = f"{duplicate.get('title', tr('workspace_title'))} Copy"
            group_id = duplicate.get("group_id")
            if group_id:
                group_map.setdefault(group_id, uuid4().hex)
                duplicate["group_id"] = group_map[group_id]
            layout = validate_block_layout(duplicate)
            layout["row"] += 1
            layout["col"] = min(WORKSPACE_GRID_COLUMNS - layout["col_span"], layout["col"] + 1)
            duplicate["layout"] = layout
            duplicates.append(duplicate)
        if len(duplicates) == 1:
            duplicates[0].pop("group_id", None)
        return duplicates

    def _append_duplicates(self, duplicates):
        if not duplicates:
            return None
        self.workspace.setdefault("blocks", []).extend(duplicates)
        for duplicate in duplicates:
            self.workspace["blocks"] = update_block_layout(
                self.workspace.get("blocks", []),
                duplicate["id"],
                duplicate["layout"],
            )
        self.selected_block_ids = [block["id"] for block in duplicates]
        self.selected_block_id = self.selected_block_ids[-1] if self.selected_block_ids else None
        self._sync_source()
        self.blockSelected.emit(self.selected_block_id or "")
        self.layoutChanged.emit()
        self.render()
        return duplicates[-1]

    def duplicate_block(self, block_id=None):
        if not self.workspace:
            return None
        if block_id is None and len(self.selected_block_ids) > 1:
            source_blocks = self._selected_blocks()
        else:
            source = self._block(block_id or self.selected_block_id)
            source_blocks = [source] if source else []
        if not source_blocks:
            return None
        self._push_undo()
        return self._append_duplicates(self._duplicate_payloads(source_blocks))

    def copy_selected(self):
        selected = self._selected_blocks()
        if not selected:
            return False
        self._clipboard_blocks = deepcopy(selected)
        self._clipboard_block = deepcopy(selected[-1])
        return True

    def paste_copied(self):
        if not self.workspace or not (self._clipboard_blocks or self._clipboard_block):
            return None
        self._push_undo()
        source_blocks = self._clipboard_blocks or [self._clipboard_block]
        return self._append_duplicates(self._duplicate_payloads(source_blocks))

    def align_selected(self, edge):
        if not self.workspace or not self.selected_block_ids:
            return
        if edge not in {"left", "right", "top", "fit_width", "center"}:
            return
        editable_ids = set(self.unlocked_selected_ids())
        if not editable_ids:
            self._set_interaction_state(verb="Locked block")
            return
        self._push_undo()
        updated = []
        for block in self.workspace.get("blocks", []):
            next_block = deepcopy(block)
            if next_block.get("id") in editable_ids:
                layout = validate_block_layout(next_block)
                if edge == "left":
                    layout["col"] = 0
                elif edge == "right":
                    layout["col"] = max(0, WORKSPACE_GRID_COLUMNS - layout["col_span"])
                elif edge == "top":
                    layout["row"] = 0
                elif edge == "fit_width":
                    layout["col"] = 0
                    layout["col_span"] = WORKSPACE_GRID_COLUMNS
                elif edge == "center":
                    layout["col"] = max(0, (WORKSPACE_GRID_COLUMNS - layout["col_span"]) // 2)
                next_block["layout"] = layout
            updated.append(next_block)
        self.workspace["blocks"] = updated
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def distribute_selected(self, axis="horizontal"):
        selected = [
            block
            for block in self._selected_blocks()
            if not block.get("locked")
        ]
        if len(selected) < 3:
            return
        self._push_undo()
        layouts = {block.get("id"): validate_block_layout(block) for block in selected}
        if axis == "horizontal":
            ordered = sorted(selected, key=lambda block: layouts[block.get("id")]["col"])
            start = layouts[ordered[0].get("id")]["col"]
            end_layout = layouts[ordered[-1].get("id")]
            end = end_layout["col"] + end_layout["col_span"]
            step = max(1, round((end - start) / max(1, len(ordered) - 1)))
            for index, block in enumerate(ordered):
                layout = layouts[block.get("id")]
                layout["col"] = min(
                    WORKSPACE_GRID_COLUMNS - layout["col_span"],
                    start + (index * step),
                )
                block["layout"] = layout
        elif axis == "vertical":
            ordered = sorted(selected, key=lambda block: layouts[block.get("id")]["row"])
            start = layouts[ordered[0].get("id")]["row"]
            end_layout = layouts[ordered[-1].get("id")]
            end = end_layout["row"] + end_layout["row_span"]
            step = max(1, round((end - start) / max(1, len(ordered) - 1)))
            for index, block in enumerate(ordered):
                layout = layouts[block.get("id")]
                layout["row"] = start + (index * step)
                block["layout"] = layout
        else:
            return
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def nudge_selected(self, row_delta=0, col_delta=0):
        if not self.workspace or not self.selected_block_ids:
            return
        editable_ids = set(self.unlocked_selected_ids())
        if not editable_ids:
            self._set_interaction_state(verb="Locked block")
            return
        self._push_undo()
        updated = []
        for block in self.workspace.get("blocks", []):
            next_block = deepcopy(block)
            if next_block.get("id") in editable_ids:
                layout = validate_block_layout(next_block)
                layout["row"] = max(0, layout["row"] + row_delta)
                layout["col"] = max(0, layout["col"] + col_delta)
                next_block["layout"] = layout
            updated.append(next_block)
        self.workspace["blocks"] = updated
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def preview_selected_move(self, start_layouts, row_delta=0, col_delta=0, anchor_id=None):
        if not self.workspace or not start_layouts:
            return
        updated = []
        moved_ids = set(start_layouts.keys())
        anchor_layout = None
        for block in self.workspace.get("blocks", []):
            next_block = deepcopy(block)
            block_id = next_block.get("id")
            if block_id in moved_ids:
                layout = dict(start_layouts[block_id])
                layout["row"] = max(0, layout["row"] + row_delta)
                layout["col"] = max(
                    0,
                    min(
                        WORKSPACE_GRID_COLUMNS - layout["col_span"],
                        layout["col"] + col_delta,
                    ),
                )
                next_block["layout"] = validate_block_layout({"layout": layout})
                if block_id == anchor_id:
                    anchor_layout = next_block["layout"]
            updated.append(next_block)
        self.workspace["blocks"] = updated
        self._sync_source()
        if anchor_layout is None and moved_ids:
            anchor_layout = validate_block_layout(
                next(
                    block
                    for block in self.workspace.get("blocks", [])
                    if block.get("id") in moved_ids
                )
            )
        if anchor_layout:
            self.placement_guide_layout = anchor_layout
            self.placement_guide_status = "clear"
            self._set_interaction_state(
                anchor_layout,
                block_id=anchor_id,
                verb=f"Move {len(moved_ids)} blocks",
            )
        self.refresh_tile_geometries()

    def delete_block(self, block_id=None):
        target_id = block_id or self.selected_block_id
        if not self.workspace or not target_id:
            return
        if self.is_block_locked(target_id):
            self._set_interaction_state(verb="Locked block")
            return
        self._push_undo()
        self.workspace["blocks"] = [
            block
            for block in self.workspace.get("blocks", [])
            if block.get("id") != target_id
        ]
        if self.selected_block_id == target_id:
            self.selected_block_ids = [
                block_id
                for block_id in self.selected_block_ids
                if block_id != target_id
            ]
            self.selected_block_id = self.selected_block_ids[-1] if self.selected_block_ids else None
            self.blockSelected.emit("")
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def clear_blocks(self):
        if not self.workspace or not self.workspace.get("blocks"):
            return
        self._push_undo()
        self.workspace["blocks"] = []
        self.selected_block_id = None
        self.selected_block_ids = []
        self._sync_source()
        self.blockSelected.emit("")
        self.layoutChanged.emit()
        self.render()

    def move_block_layer(self, block_id=None, direction=1):
        if block_id is None and len(self.selected_block_ids) > 1:
            self.arrange_selected_layers(direction=direction)
            return
        target_id = block_id or self.selected_block_id
        if self.is_block_locked(target_id):
            self._set_interaction_state(verb="Locked block")
            return
        blocks = self.workspace.get("blocks", []) if self.workspace else []
        index = next((i for i, block in enumerate(blocks) if block.get("id") == target_id), -1)
        target_index = index + direction
        if index < 0 or target_index < 0 or target_index >= len(blocks):
            return
        self._push_undo()
        blocks[index], blocks[target_index] = blocks[target_index], blocks[index]
        self.workspace["blocks"] = blocks
        self.selected_block_id = target_id
        self.selected_block_ids = [target_id]
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def arrange_selected_layers(self, direction=1, to_edge=False):
        if not self.workspace or not self.selected_block_ids:
            return
        selected_ids = [
            block_id
            for block_id in self.selected_block_ids
            if not self.is_block_locked(block_id)
        ]
        if not selected_ids:
            self._set_interaction_state(verb="Locked block")
            return
        selected_set = set(selected_ids)
        blocks = list(self.workspace.get("blocks", []))
        selected_blocks = [block for block in blocks if block.get("id") in selected_set]
        remaining = [block for block in blocks if block.get("id") not in selected_set]
        if not selected_blocks:
            return

        self._push_undo()
        if to_edge:
            blocks = (
                remaining + selected_blocks
                if direction > 0
                else selected_blocks + remaining
            )
        elif direction > 0:
            for index in range(len(blocks) - 2, -1, -1):
                if (
                    blocks[index].get("id") in selected_set
                    and blocks[index + 1].get("id") not in selected_set
                ):
                    blocks[index], blocks[index + 1] = blocks[index + 1], blocks[index]
        elif direction < 0:
            for index in range(1, len(blocks)):
                if (
                    blocks[index].get("id") in selected_set
                    and blocks[index - 1].get("id") not in selected_set
                ):
                    blocks[index], blocks[index - 1] = blocks[index - 1], blocks[index]
        else:
            return

        self.workspace["blocks"] = blocks
        self.selected_block_ids = [block_id for block_id in self.selected_block_ids if block_id in selected_set]
        self.selected_block_id = self.selected_block_ids[-1] if self.selected_block_ids else None
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def resize_selected(self, col_delta=0, row_delta=0):
        block = self._block(self.selected_block_id)
        if not block:
            return
        if block.get("locked"):
            self._set_interaction_state(verb="Locked block")
            return
        layout = validate_block_layout(block)
        self.update_selected_layout(
            col_span=max(1, layout["col_span"] + col_delta),
            row_span=max(1, layout["row_span"] + row_delta),
        )

    def delete_selected(self):
        if not self.workspace or not self.selected_block_ids:
            return
        editable_ids = set(self.unlocked_selected_ids())
        if not editable_ids:
            self._set_interaction_state(verb="Locked block")
            return
        self._push_undo()
        self.workspace["blocks"] = [
            block
            for block in self.workspace.get("blocks", [])
            if block.get("id") not in editable_ids
        ]
        self.selected_block_ids = [
            block_id
            for block_id in self.selected_block_ids
            if block_id not in editable_ids
        ]
        self.selected_block_id = self.selected_block_ids[-1] if self.selected_block_ids else None
        self._sync_source()
        self.blockSelected.emit("")
        self.layoutChanged.emit()
        self.render()

    def undo(self):
        if not self._undo_stack or not self.workspace:
            return
        self._redo_stack.append(deepcopy(self.workspace.get("blocks", [])))
        self.workspace["blocks"] = self._undo_stack.pop()
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def redo(self):
        if not self._redo_stack or not self.workspace:
            return
        self._undo_stack.append(deepcopy(self.workspace.get("blocks", [])))
        self.workspace["blocks"] = self._redo_stack.pop()
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def _push_undo(self):
        if self.workspace:
            self._undo_stack.append(deepcopy(self.workspace.get("blocks", [])))
            self._redo_stack.clear()

    def begin_interaction(self):
        if self.workspace and self._interaction_snapshot is None:
            self._interaction_snapshot = deepcopy(self.workspace.get("blocks", []))

    def commit_interaction(self):
        if self._interaction_snapshot is not None:
            self._undo_stack.append(self._interaction_snapshot)
            self._redo_stack.clear()
            self._interaction_snapshot = None
            self.layoutChanged.emit()
        self._sync_source()
        self.render()

    def preview_layout(self, block_id, **changes):
        if not self.workspace or not block_id:
            return
        if self.is_block_locked(block_id):
            self._set_interaction_state(verb="Locked block")
            return
        block = self._block(block_id)
        if not block:
            return
        layout = validate_block_layout(block)
        layout.update(changes)
        layout, _ = self.snap_layout_to_alignment(layout, block_id=block_id)
        layout, _ = self.resolve_placement(layout, block_id=block_id)
        self.workspace["blocks"] = update_block_layout(
            self.workspace.get("blocks", []),
            block_id,
            layout,
        )
        self._sync_source()
        self.refresh_tile_geometries()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.select_block(None)
            return
        if event.key() == Qt.Key_Delete and self.workspace and self.selected_block_id:
            self.delete_selected()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_A:
            self.select_all()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Z:
            if event.modifiers() & Qt.ShiftModifier:
                self.redo()
            else:
                self.undo()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Y:
            self.redo()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self.copy_selected()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self.paste_copied()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_D:
            self.duplicate_block()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_G:
            if event.modifiers() & Qt.ShiftModifier:
                self.ungroup_selected()
            else:
                self.group_selected()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_L:
            self.toggle_selected_locked()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_H:
            self.toggle_selected_visible()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_BracketRight:
            self.arrange_selected_layers(
                direction=1,
                to_edge=bool(event.modifiers() & Qt.ShiftModifier),
            )
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_BracketLeft:
            self.arrange_selected_layers(
                direction=-1,
                to_edge=bool(event.modifiers() & Qt.ShiftModifier),
            )
            return
        arrows = {Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1), Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0)}
        if event.key() in arrows and self.selected_block_id:
            dr, dc = arrows[event.key()]
            block = self._block(self.selected_block_id)
            layout = validate_block_layout(block)
            if event.modifiers() & Qt.ShiftModifier:
                self.update_selected_layout(col_span=layout["col_span"] + dc, row_span=layout["row_span"] + dr)
            else:
                self.nudge_selected(row_delta=dr, col_delta=dc)
            return
        super().keyPressEvent(event)

    def set_workspace(self, workspace):
        self._source_workspace = workspace
        self.workspace = normalize_workspace_layout(workspace) if workspace else None
        self.placement_guide_layout = None
        self.placement_guide_status = "clear"
        self.alignment_guides = {"vertical": [], "horizontal": []}
        self.interaction_hint = "Ready"
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._interaction_snapshot = None
        valid_ids = {
            block.get("id")
            for block in self.workspace.get("blocks", [])
        } if self.workspace else set()
        self.selected_block_ids = [
            block_id
            for block_id in self.selected_block_ids
            if block_id in valid_ids
        ]
        self.selected_block_id = self.selected_block_ids[-1] if self.selected_block_ids else None
        self._sync_source()
        self.render()

    def set_selected_block(self, block_id):
        self.selected_block_id = block_id
        self.selected_block_ids = [block_id] if block_id else []
        self.render()

    def select_block(self, block_id, additive=False):
        if additive and block_id:
            if block_id in self.selected_block_ids:
                self.selected_block_ids = [
                    existing
                    for existing in self.selected_block_ids
                    if existing != block_id
                ]
            else:
                self.selected_block_ids.append(block_id)
            self.selected_block_id = self.selected_block_ids[-1] if self.selected_block_ids else None
        else:
            group_ids = self.group_member_ids(block_id) if block_id else []
            self.selected_block_id = block_id
            self.selected_block_ids = group_ids or ([block_id] if block_id else [])
        self.blockSelected.emit(block_id or "")
        self.render()

    def select_block_for_drag(self, block_id, additive=False):
        if not block_id:
            self.select_block(None)
            return
        if additive:
            if block_id in self.selected_block_ids:
                self.selected_block_ids = [
                    existing
                    for existing in self.selected_block_ids
                    if existing != block_id
                ]
            else:
                self.selected_block_ids.append(block_id)
            self.selected_block_id = self.selected_block_ids[-1] if self.selected_block_ids else None
        elif block_id in self.selected_block_ids and len(self.selected_block_ids) > 1:
            self.selected_block_id = block_id
        else:
            group_ids = self.group_member_ids(block_id)
            self.selected_block_id = block_id
            self.selected_block_ids = group_ids or [block_id]
        self.blockSelected.emit(self.selected_block_id or "")
        self.refresh_tile_selection_state()

    def select_all(self):
        if not self.workspace:
            return
        self.selected_block_ids = [
            block.get("id")
            for block in self.workspace.get("blocks", [])
            if block.get("id")
        ]
        self.selected_block_id = (
            self.selected_block_ids[-1] if self.selected_block_ids else None
        )
        self.blockSelected.emit(self.selected_block_id or "")
        self.render()

    def select_blocks_in_rect(self, rect, additive=False):
        if not self.workspace:
            return
        matched_ids = []
        for block in self.workspace.get("blocks", []):
            block_id = block.get("id")
            if not block_id:
                continue
            if self.layout_to_rect(validate_block_layout(block)).intersects(rect):
                matched_ids.append(block_id)

        if additive:
            selected_ids = list(self.selected_block_ids)
            for block_id in matched_ids:
                if block_id not in selected_ids:
                    selected_ids.append(block_id)
            self.selected_block_ids = selected_ids
        else:
            self.selected_block_ids = matched_ids

        self.selected_block_id = (
            self.selected_block_ids[-1] if self.selected_block_ids else None
        )
        self.blockSelected.emit(self.selected_block_id or "")
        self.render()

    def drop_block(self, block_id, global_pos):
        if not self.workspace or not block_id:
            return
        if self.is_block_locked(block_id):
            self._set_interaction_state(verb="Locked block")
            return
        self._push_undo()
        pos = self.surface.mapFromGlobal(global_pos)
        row, col = self.position_to_grid(pos)
        block = self._block(block_id)
        if not block:
            return
        current = validate_block_layout(block)
        current["row"] = row
        current["col"] = min(col, max(0, WORKSPACE_GRID_COLUMNS - current["col_span"]))
        current, _ = self.snap_layout_to_alignment(current, block_id=block_id)
        current, _ = self.resolve_placement(current, block_id=block_id)
        self.workspace["blocks"] = update_block_layout(
            self.workspace.get("blocks", []),
            block_id,
            current,
        )
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def update_selected_layout(self, **changes):
        if not self.workspace or not self.selected_block_id:
            return
        if self.is_block_locked(self.selected_block_id):
            self._set_interaction_state(verb="Locked block")
            return
        block = self._block(self.selected_block_id)
        if not block:
            return
        self._push_undo()
        layout = validate_block_layout(block)
        layout.update(changes)
        layout, _ = self.snap_layout_to_alignment(layout, block_id=self.selected_block_id)
        layout, _ = self.resolve_placement(layout, block_id=self.selected_block_id)
        self.workspace["blocks"] = update_block_layout(
            self.workspace.get("blocks", []),
            self.selected_block_id,
            layout,
        )
        self._sync_source()
        self.layoutChanged.emit()
        self.render()

    def render(self):
        self._clear_grid()
        if not self.workspace:
            empty = QLabel(tr("workspace_no_workspaces"))
            empty.setObjectName("MutedText")
            empty.setParent(self.surface)
            empty.setAlignment(Qt.AlignCenter)
            empty.setGeometry(self.canvas_rect())
            empty.show()
            self.surface.update()
            return
        blocks = self.workspace.get("blocks", [])
        if not blocks:
            empty = QLabel(
                "Blank canvas\nDrag a block from the left palette or use Add Block to begin."
            )
            empty.setObjectName("WorkspaceCanvasEmptyState")
            empty.setParent(self.surface)
            empty.setAlignment(Qt.AlignCenter)
            empty.setGeometry(self.canvas_rect())
            empty.show()
            self.surface.update()
            return
        max_row = 0
        for block in blocks:
            layout = validate_block_layout(block)
            max_row = max(max_row, layout["row"] + layout["row_span"])
            tile = WorkspaceLayoutTile(
                block,
                self.block_label_for_type(block.get("type")),
                self,
            )
            tile.setProperty("selected", block.get("id") in self.selected_block_ids)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
            tile.setGeometry(self.layout_to_rect(layout))
            tile.show()
        self.surface.setMinimumHeight(max(560, (max_row + 2) * self.row_height + 56))
        self.surface.update()

    def refresh_tile_geometries(self):
        """Move existing tiles during pointer interactions without recreating them."""
        if not self.workspace:
            self.surface.update()
            return
        tiles = {
            tile.block.get("id"): tile
            for tile in self.surface.findChildren(
                WorkspaceLayoutTile,
                options=Qt.FindDirectChildrenOnly,
            )
            if tile.block.get("id")
        }
        if not tiles:
            self.render()
            return
        max_row = 0
        for block in self.workspace.get("blocks", []):
            block_id = block.get("id")
            layout = validate_block_layout(block)
            max_row = max(max_row, layout["row"] + layout["row_span"])
            tile = tiles.get(block_id)
            if tile is None:
                self.render()
                return
            tile.block = block
            tile.setProperty("selected", block_id in self.selected_block_ids)
            tile.setGeometry(self.layout_to_rect(layout))
            tile.update()
        self.surface.setMinimumHeight(max(560, (max_row + 2) * self.row_height + 56))
        self.surface.update()

    def refresh_tile_selection_state(self):
        for tile in self.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        ):
            selected = tile.block.get("id") in self.selected_block_ids
            active = tile.block.get("id") == self.selected_block_id
            tile.setProperty("selected", selected)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
            for button in tile.findChildren(QPushButton, "WorkspaceTileEditButton"):
                button.setVisible(active)
            tile.update()
        self.surface.update()

    def layout_to_rect(self, layout):
        rect = self.canvas_rect()
        x = rect.left() + int(layout["col"] * self.cell_width())
        y = rect.top() + int(layout["row"] * self.row_height)
        width = int(layout["col_span"] * self.cell_width()) - 10
        height = int(layout["row_span"] * self.row_height) - 10
        return QRect(x + 5, y + 5, max(96, width), max(64, height))

    def _block(self, block_id):
        for block in self.workspace.get("blocks", []) if self.workspace else []:
            if block.get("id") == block_id:
                return block
        return None

    def _selected_blocks(self):
        selected_ids = set(self.selected_block_ids)
        return [
            block
            for block in self.workspace.get("blocks", [])
            if block.get("id") in selected_ids
        ] if self.workspace else []

    def selection_summary(self):
        selected = self._selected_blocks()
        if not selected:
            return {
                "count": 0,
                "text": "No selection",
            }
        layouts = [validate_block_layout(block) for block in selected]
        left = min(layout["col"] for layout in layouts)
        top = min(layout["row"] for layout in layouts)
        right = max(layout["col"] + layout["col_span"] for layout in layouts)
        bottom = max(layout["row"] + layout["row_span"] for layout in layouts)
        return {
            "count": len(selected),
            "row": top,
            "col": left,
            "row_span": bottom - top,
            "col_span": right - left,
            "text": f"{len(selected)} selected | x {left}, y {top}, w {right - left}, h {bottom - top}",
        }

    def _sync_source(self):
        if not self.workspace:
            return
        source = getattr(self, "_source_workspace", None)
        if source is not None:
            source["blocks"] = self.workspace.get("blocks", [])

    def _clear_grid(self):
        for child in self.surface.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            if child is self.surface._rubber_band:
                continue
            child.setParent(None)
            child.deleteLater()
