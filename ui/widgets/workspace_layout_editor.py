from copy import deepcopy
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from services.workspace_service import new_block
from services.workspace_layout import (
    WORKSPACE_GRID_COLUMNS,
    normalize_workspace_layout,
    update_block_layout,
    validate_block_layout,
)
from ui.foundation import create_card
from utils.language_helper import ui_text as tr


class WorkspaceLayoutTile(QFrame):
    def __init__(self, block, label, editor):
        super().__init__(editor)
        self.block = block
        self.editor = editor
        self._drag_start = QPoint()
        self.setObjectName("WorkspaceLayoutTile")
        self.setCursor(Qt.OpenHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(56)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        self.setLayout(layout)

        title = QLabel(block.get("title") or tr("workspace_title"))
        title.setObjectName("StrongText")
        title.setWordWrap(True)
        summary = QLabel(label)
        summary.setObjectName("MutedText")
        summary.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(summary)
        layout.addStretch()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            self.editor.select_block(self.block.get("id"))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.OpenHandCursor)
            if (event.position().toPoint() - self._drag_start).manhattanLength() > 8:
                self.editor.drop_block(self.block.get("id"), self.mapToGlobal(event.position().toPoint()))
            event.accept()
            return
        super().mouseReleaseEvent(event)


class WorkspaceLayoutEditor(QWidget):
    layoutChanged = Signal()
    blockSelected = Signal(str)

    def __init__(self, block_label_for_type, parent=None):
        super().__init__(parent)
        self.block_label_for_type = block_label_for_type
        self.workspace = None
        self.selected_block_id = None
        self.row_height = 66
        self._undo_stack = []
        self._redo_stack = []

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.setLayout(root)

        self.surface = create_card()
        self.surface.setObjectName("WorkspaceLayoutEditorSurface")
        self.surface.setMinimumHeight(220)
        self.surface.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(12, 12, 12, 12)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.surface.setLayout(self.grid)
        root.addWidget(self.surface)

        for col in range(WORKSPACE_GRID_COLUMNS):
            self.grid.setColumnStretch(col, 1)


    def add_block_at(self, block_type, row=0, col=0):
        if not self.workspace:
            return None
        self._push_undo()
        block = new_block(block_type)
        layout = validate_block_layout(block)
        layout.update({"row": row, "col": col})
        block["layout"] = layout
        self.workspace.setdefault("blocks", []).append(block)
        self.workspace["blocks"] = update_block_layout(
            self.workspace.get("blocks", []), block.get("id"), layout
        )
        self.selected_block_id = block.get("id")
        self._sync_source()
        self.blockSelected.emit(self.selected_block_id or "")
        self.layoutChanged.emit()
        self.render()
        return block

    def resize_selected(self, col_delta=0, row_delta=0):
        block = self._block(self.selected_block_id)
        if not block:
            return
        layout = validate_block_layout(block)
        self.update_selected_layout(
            col_span=max(1, layout["col_span"] + col_delta),
            row_span=max(1, layout["row_span"] + row_delta),
        )

    def undo(self):
        if not self._undo_stack or not self.workspace:
            return
        self._redo_stack.append(deepcopy(self.workspace.get("blocks", [])))
        self.workspace["blocks"] = self._undo_stack.pop()
        self._sync_source(); self.layoutChanged.emit(); self.render()

    def redo(self):
        if not self._redo_stack or not self.workspace:
            return
        self._undo_stack.append(deepcopy(self.workspace.get("blocks", [])))
        self.workspace["blocks"] = self._redo_stack.pop()
        self._sync_source(); self.layoutChanged.emit(); self.render()

    def _push_undo(self):
        if self.workspace:
            self._undo_stack.append(deepcopy(self.workspace.get("blocks", [])))
            self._redo_stack.clear()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and self.workspace and self.selected_block_id:
            self._push_undo()
            self.workspace["blocks"] = [b for b in self.workspace.get("blocks", []) if b.get("id") != self.selected_block_id]
            self.selected_block_id = None
            self._sync_source(); self.layoutChanged.emit(); self.render(); return
        arrows = {Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1), Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0)}
        if event.key() in arrows and self.selected_block_id:
            dr, dc = arrows[event.key()]
            block = self._block(self.selected_block_id)
            layout = validate_block_layout(block)
            if event.modifiers() & Qt.ShiftModifier:
                self.update_selected_layout(col_span=layout["col_span"] + dc, row_span=layout["row_span"] + dr)
            else:
                self.update_selected_layout(row=max(0, layout["row"] + dr), col=max(0, layout["col"] + dc))
            return
        super().keyPressEvent(event)

    def set_workspace(self, workspace):
        self._source_workspace = workspace
        self.workspace = normalize_workspace_layout(workspace) if workspace else None
        self._undo_stack.clear(); self._redo_stack.clear()
        self._sync_source()
        self.render()

    def set_selected_block(self, block_id):
        self.selected_block_id = block_id
        self.render()

    def select_block(self, block_id):
        self.selected_block_id = block_id
        self.blockSelected.emit(block_id or "")
        self.render()

    def drop_block(self, block_id, global_pos):
        if not self.workspace or not block_id:
            return
        self._push_undo()
        pos = self.surface.mapFromGlobal(global_pos)
        available_width = max(1, self.surface.width() - 24)
        cell_width = max(1, available_width / WORKSPACE_GRID_COLUMNS)
        row = max(0, int((pos.y() - 12) / self.row_height))
        col = max(0, min(WORKSPACE_GRID_COLUMNS - 1, int((pos.x() - 12) / cell_width)))
        block = self._block(block_id)
        if not block:
            return
        current = validate_block_layout(block)
        current["row"] = row
        current["col"] = min(col, max(0, WORKSPACE_GRID_COLUMNS - current["col_span"]))
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
        block = self._block(self.selected_block_id)
        if not block:
            return
        self._push_undo()
        layout = validate_block_layout(block)
        layout.update(changes)
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
            self.grid.addWidget(empty, 0, 0, 1, WORKSPACE_GRID_COLUMNS)
            return
        blocks = self.workspace.get("blocks", [])
        max_row = 0
        for block in blocks:
            layout = validate_block_layout(block)
            max_row = max(max_row, layout["row"] + layout["row_span"])
            tile = WorkspaceLayoutTile(
                block,
                self.block_label_for_type(block.get("type")),
                self,
            )
            tile.setProperty("selected", block.get("id") == self.selected_block_id)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
            self.grid.addWidget(
                tile,
                layout["row"],
                layout["col"],
                layout["row_span"],
                layout["col_span"],
            )
        self.surface.setMinimumHeight(max(220, (max_row + 1) * self.row_height + 24))

    def _block(self, block_id):
        for block in self.workspace.get("blocks", []) if self.workspace else []:
            if block.get("id") == block_id:
                return block
        return None

    def _sync_source(self):
        if not self.workspace:
            return
        source = getattr(self, "_source_workspace", None)
        if source is not None:
            source["blocks"] = self.workspace.get("blocks", [])

    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
