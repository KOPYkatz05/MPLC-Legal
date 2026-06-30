from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from services.settings_service import SettingsService
from services.workspace_block_registry import BLOCK_CATEGORIES, BLOCK_LABELS
from services.workspace_layout import WORKSPACE_GRID_COLUMNS, validate_block_layout
from services.workspace_service import WorkspaceService, new_workspace
from ui.foundation import (
    DialogFooter,
    create_button,
    create_combo_box,
    create_line_edit,
    create_list_widget,
    create_plain_text_edit,
    create_search_edit,
    create_scroll_area,
    show_message,
)
from ui.widgets.workspace_layout_editor import WorkspaceLayoutEditor, WorkspacePaletteButton
from utils.constants import DOCUMENTS
from utils.language_helper import ui_text as tr


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


class WorkspaceBlockPropertiesDialog(QDialog):
    def __init__(self, block, parent=None):
        super().__init__(parent)
        self.block = deepcopy(block or {})
        self.setWindowTitle(tr("workspace_properties_title"))
        self.resize(520, 540)
        self.setObjectName("WorkspacePropertiesDialog")

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setLayout(root)

        header = QFrame()
        header.setObjectName("WorkspacePropertiesHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(4)
        header.setLayout(header_layout)

        title = QLabel(tr("workspace_properties_title"))
        title.setObjectName("WorkspacePropertiesTitle")
        header_layout.addWidget(title)
        helper = QLabel(tr("workspace_properties_hint"))
        helper.setObjectName("WorkspacePropertiesSubtitle")
        helper.setWordWrap(True)
        header_layout.addWidget(helper)
        root.addWidget(header)

        body = QFrame()
        body.setObjectName("WorkspacePropertiesBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(18, 16, 18, 16)
        body_layout.setSpacing(12)
        body.setLayout(body_layout)

        form = QFormLayout()
        form.setSpacing(10)
        body_layout.addLayout(form, stretch=1)

        self.title_input = create_line_edit(
            tr("workspace_block_title"),
            "WorkspaceBlockTitleDialogInput",
        )
        self.title_input.setText(self.block.get("title", ""))
        form.addRow(tr("workspace_properties_title_field"), self.title_input)

        layout_data = validate_block_layout(self.block)
        self.row_spin = QSpinBox()
        self.row_spin.setRange(0, 99)
        self.row_spin.setValue(layout_data["row"])
        self.col_spin = QSpinBox()
        self.col_spin.setRange(0, WORKSPACE_GRID_COLUMNS - 1)
        self.col_spin.setValue(layout_data["col"])
        self.col_span_spin = QSpinBox()
        self.col_span_spin.setRange(1, WORKSPACE_GRID_COLUMNS)
        self.col_span_spin.setValue(layout_data["col_span"])
        self.row_span_spin = QSpinBox()
        self.row_span_spin.setRange(1, 8)
        self.row_span_spin.setValue(layout_data["row_span"])
        layout_row = QHBoxLayout()
        for label, widget in (
            ("Row", self.row_spin),
            ("Col", self.col_spin),
            ("W", self.col_span_spin),
            ("H", self.row_span_spin),
        ):
            stack = QVBoxLayout()
            stack.setContentsMargins(0, 0, 0, 0)
            stack.addWidget(QLabel(label))
            stack.addWidget(widget)
            layout_row.addLayout(stack)
        form.addRow(tr("workspace_properties_canvas"), layout_row)

        self.fields_input = create_plain_text_edit(tr("workspace_block_fields"))
        self.fields_input.setPlainText("\n".join(self.block.get("fields", [])))
        form.addRow(tr("workspace_block_fields"), self.fields_input)

        self.document_combo = create_combo_box()
        self.document_combo.addItem(tr("workspace_first_available_document"), "")
        for document_type, config in DOCUMENTS.items():
            self.document_combo.addItem(config.get("label", document_type), document_type)
        doc_idx = self.document_combo.findData(self.block.get("document_type", ""))
        self.document_combo.setCurrentIndex(max(doc_idx, 0))
        form.addRow(tr("workspace_properties_document"), self.document_combo)

        self.web_url_input = create_line_edit(
            tr("workspace_block_web_url"),
            "WorkspaceWebUrlDialogInput",
        )
        self.web_url_input.setText(self.block.get("web_url", ""))
        form.addRow(tr("workspace_properties_website"), self.web_url_input)

        self.links_input = create_plain_text_edit(tr("workspace_properties_links"))
        links = (self.block.get("settings") or {}).get("links", [])
        self.links_input.setPlainText(
            "\n".join(
                f"{link.get('label', '')}|{link.get('url', '')}"
                for link in links
                if isinstance(link, dict)
            )
        )
        form.addRow(tr("workspace_properties_links"), self.links_input)

        self.actions_input = create_plain_text_edit(tr("workspace_properties_actions"))
        actions = (self.block.get("settings") or {}).get("actions", [])
        self.actions_input.setPlainText("\n".join(actions))
        form.addRow(tr("workspace_properties_actions"), self.actions_input)

        block_type = self.block.get("type")
        for widget, visible in (
            (self.fields_input, block_type == "personal_info"),
            (self.document_combo, block_type == "document_viewer"),
            (self.web_url_input, block_type == "web_viewer"),
            (self.links_input, block_type == "link_list"),
            (self.actions_input, block_type == "quick_actions"),
        ):
            try:
                form.setRowVisible(widget, visible)
            except AttributeError:
                widget.setVisible(visible)

        footer = DialogFooter()
        cancel_btn = create_button(tr("missionary_detail_cancel"), "secondary")
        apply_btn = create_button(tr("workspace_apply"), "primary")
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.accept)
        footer.add_action(cancel_btn)
        footer.add_action(apply_btn)
        body_layout.addWidget(footer)
        root.addWidget(body, stretch=1)

    def updated_block(self):
        block = deepcopy(self.block)
        block["title"] = self.title_input.text().strip() or block.get("title", "")
        block["layout"] = validate_block_layout({
            **block,
            "layout": {
                "row": self.row_spin.value(),
                "col": self.col_spin.value(),
                "col_span": self.col_span_spin.value(),
                "row_span": self.row_span_spin.value(),
            },
        })
        if block.get("type") == "personal_info":
            block["fields"] = [
                line.strip()
                for line in self.fields_input.toPlainText().splitlines()
                if line.strip()
            ]
        if block.get("type") == "document_viewer":
            block["document_type"] = self.document_combo.currentData() or ""
        if block.get("type") == "web_viewer":
            block["web_url"] = self.web_url_input.text().strip()
        if block.get("type") == "link_list":
            links = []
            for line in self.links_input.toPlainText().splitlines():
                if not line.strip():
                    continue
                label, _, url = line.partition("|")
                links.append({"label": label.strip() or url.strip(), "url": url.strip() or label.strip()})
            block.setdefault("settings", {})["links"] = links
        if block.get("type") == "quick_actions":
            block.setdefault("settings", {})["actions"] = [
                line.strip()
                for line in self.actions_input.toPlainText().splitlines()
                if line.strip()
            ]
        return block


class WorkspacesPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.setObjectName("WorkspacesPage")
        self.main_window = main_window
        self.settings_service = (
            main_window.settings_service if main_window else SettingsService()
        )
        self.workspace_service = (
            getattr(main_window, "workspace_service", None) if main_window else None
        ) or WorkspaceService()
        self._workspaces = []
        self._selected_workspace_id = None
        self._refreshing_layers = False
        self.setup_ui()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.workspace_layout_editor.select_block(None)
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_A:
            self.workspace_layout_editor.select_all()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Z:
            if event.modifiers() & Qt.ShiftModifier:
                self._redo()
            else:
                self._undo()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Y:
            self._redo()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self._copy_selected_block()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self._paste_block()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_D:
            self._duplicate_selected_block()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_G:
            if event.modifiers() & Qt.ShiftModifier:
                self._ungroup_selected_blocks()
            else:
                self._group_selected_blocks()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_L:
            self._toggle_selected_locked()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_H:
            self._toggle_selected_visible()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_BracketRight:
            self._move_selected_layer(1, to_edge=bool(event.modifiers() & Qt.ShiftModifier))
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_BracketLeft:
            self._move_selected_layer(-1, to_edge=bool(event.modifiers() & Qt.ShiftModifier))
            return
        if event.key() == Qt.Key_Delete:
            self._remove_workspace_block()
            return
        super().keyPressEvent(event)

    def setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(12, 10, 16, 16)
        root.setSpacing(12)
        self.setLayout(root)

        top = QFrame()
        top.setObjectName("WorkspaceTopBar")
        top.setAttribute(Qt.WA_StyledBackground, True)
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        top.setLayout(top_layout)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)
        self.workspace_page_title = QLabel(tr("workspace_builder_title"))
        title = self.workspace_page_title
        title.setObjectName("WorkspacePageTitle")
        self.workspace_page_subtitle = QLabel(tr("workspace_builder_subtitle"))
        subtitle = self.workspace_page_subtitle
        subtitle.setObjectName("WorkspacePageSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        top_layout.addLayout(title_stack, stretch=1)

        self.workspace_name_input = create_line_edit(
            tr("workspace_name_placeholder"),
            "WorkspaceNameInput",
        )
        self.workspace_name_input.setFixedHeight(30)
        self.workspace_name_input.setMaximumWidth(280)
        self.workspace_name_input.textChanged.connect(self._update_workspace_name)
        top_layout.addWidget(self.workspace_name_input)
        self.workspace_size_combo = create_combo_box()
        self.workspace_size_combo.setFixedHeight(30)
        for label, value in (
            (tr("workspace_size_medium"), "medium"),
            (tr("workspace_size_large"), "large"),
            (tr("workspace_size_wide"), "wide"),
        ):
            self.workspace_size_combo.addItem(label, value)
        self.workspace_size_combo.currentIndexChanged.connect(self._update_workspace_size)
        top_layout.addWidget(self.workspace_size_combo)
        self.workspace_save_btn = create_button(tr("workspace_save"), "primary")
        self.workspace_save_btn.setFixedHeight(30)
        self.workspace_save_btn.clicked.connect(self._save_current_workspace)
        top_layout.addWidget(self.workspace_save_btn)
        root.addWidget(top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("WorkspaceBuilderSplitter")
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        left = QFrame()
        left.setObjectName("WorkspaceLeftRail")
        left.setAttribute(Qt.WA_StyledBackground, True)
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)
        left.setLayout(left_layout)
        left.setMinimumWidth(250)
        left.setMaximumWidth(340)

        workspaces_header = QHBoxLayout()
        self.workspace_new_btn = create_button(tr("workspace_new"), "primary")
        self.workspace_duplicate_btn = create_button(tr("workspace_duplicate"), "secondary")
        self.workspace_delete_btn = create_button(tr("workspace_delete"), "danger")
        self.workspace_new_btn.clicked.connect(self._new_workspace)
        self.workspace_duplicate_btn.clicked.connect(self._duplicate_workspace)
        self.workspace_delete_btn.clicked.connect(self._delete_workspace)
        workspaces_header.addWidget(self.workspace_new_btn)
        workspaces_header.addWidget(self.workspace_duplicate_btn)
        workspaces_header.addWidget(self.workspace_delete_btn)
        left_layout.addLayout(workspaces_header)

        self.workspaces_list = create_list_widget("WorkspaceBuilderList")
        self.workspaces_list.currentItemChanged.connect(self._workspace_selection_changed)
        left_layout.addWidget(self.workspaces_list, stretch=1)

        self.palette_label = QLabel(tr("workspace_blocks"))
        palette_label = self.palette_label
        palette_label.setObjectName("WorkspacePanelTitle")
        left_layout.addWidget(palette_label)
        self.palette_search = create_search_edit(tr("workspace_search_blocks"))
        self.palette_search.textChanged.connect(self._refresh_palette)
        left_layout.addWidget(self.palette_search)
        palette_scroll = create_scroll_area("WorkspacePaletteScroll", transparent=True)
        self.palette_body = QWidget()
        self.palette_body_layout = QVBoxLayout()
        self.palette_body_layout.setContentsMargins(0, 0, 0, 0)
        self.palette_body_layout.setSpacing(8)
        self.palette_body.setLayout(self.palette_body_layout)
        palette_scroll.setWidget(self.palette_body)
        left_layout.addWidget(palette_scroll, stretch=2)
        splitter.addWidget(left)

        center = QFrame()
        center.setObjectName("WorkspaceCanvasCard")
        center.setAttribute(Qt.WA_StyledBackground, True)
        center_layout = QVBoxLayout()
        center_layout.setContentsMargins(12, 0, 12, 0)
        center_layout.setSpacing(10)
        center.setLayout(center_layout)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("WorkspaceToolbar")
        toolbar_frame.setAttribute(Qt.WA_StyledBackground, True)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 7, 10, 7)
        toolbar.setSpacing(4)
        toolbar_frame.setLayout(toolbar)
        self.undo_btn = create_button(tr("workspace_undo"), "secondary")
        self.redo_btn = create_button(tr("workspace_redo"), "secondary")
        self.zoom_out_btn = create_button("-", "secondary")
        self.zoom_reset_btn = create_button("100%", "secondary")
        self.zoom_in_btn = create_button("+", "secondary")
        self.copy_btn = create_button(tr("workspace_copy"), "secondary")
        self.paste_btn = create_button(tr("workspace_paste"), "secondary")
        self.clear_canvas_btn = create_button(tr("workspace_clear_canvas"), "danger")
        self.add_selected_btn = create_button(tr("workspace_add_block"), "secondary")
        self.block_add_combo = create_combo_box()
        self.block_add_combo.setFixedHeight(30)
        for block_type in BLOCK_LABELS:
            self.block_add_combo.addItem(self._block_label(block_type), block_type)
        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn.clicked.connect(self._redo)
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_reset_btn.clicked.connect(self._zoom_reset)
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        self.copy_btn.clicked.connect(self._copy_selected_block)
        self.paste_btn.clicked.connect(self._paste_block)
        self.clear_canvas_btn.clicked.connect(self._clear_canvas)
        self.add_selected_btn.clicked.connect(self._add_workspace_block)
        for button in (
            self.undo_btn,
            self.redo_btn,
            self.zoom_out_btn,
            self.zoom_reset_btn,
            self.zoom_in_btn,
            self.copy_btn,
            self.paste_btn,
            self.clear_canvas_btn,
            self.add_selected_btn,
        ):
            button.setFixedHeight(30)
        toolbar.addWidget(self.undo_btn)
        toolbar.addWidget(self.redo_btn)
        toolbar.addWidget(self.zoom_out_btn)
        toolbar.addWidget(self.zoom_reset_btn)
        toolbar.addWidget(self.zoom_in_btn)
        toolbar.addWidget(self.copy_btn)
        toolbar.addWidget(self.paste_btn)
        toolbar.addWidget(self.clear_canvas_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.block_add_combo)
        toolbar.addWidget(self.add_selected_btn)
        center_layout.addWidget(toolbar_frame)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        self.selection_metrics_label = QLabel(tr("workspace_no_selection"))
        self.selection_metrics_label.setObjectName("WorkspaceSelectionMetrics")
        self.shortcut_hint_label = QLabel(
            tr("workspace_shortcut_hint")
        )
        self.shortcut_hint_label.setObjectName("WorkspaceShortcutHint")
        status_row.addWidget(self.selection_metrics_label)
        status_row.addStretch()
        status_row.addWidget(self.shortcut_hint_label)
        center_layout.addLayout(status_row)

        canvas_scroll = create_scroll_area("WorkspaceCanvasScroll", transparent=True)
        canvas_shell = QWidget()
        canvas_shell_layout = QVBoxLayout()
        canvas_shell_layout.setContentsMargins(0, 0, 0, 0)
        canvas_shell.setLayout(canvas_shell_layout)
        self.workspace_layout_editor = WorkspaceLayoutEditor(self._block_label)
        self.workspace_layout_editor.blockSelected.connect(self._select_block_from_layout)
        self.workspace_layout_editor.editRequested.connect(self._edit_block_properties)
        self.workspace_layout_editor.layoutChanged.connect(self._workspace_layout_changed)
        self.workspace_layout_editor.interactionChanged.connect(self._refresh_selection_metrics)
        canvas_shell_layout.addWidget(self.workspace_layout_editor)
        canvas_scroll.setWidget(canvas_shell)
        center_layout.addWidget(canvas_scroll, stretch=1)
        splitter.addWidget(center)

        inspector = QFrame()
        inspector.setObjectName("WorkspaceInspector")
        inspector.setAttribute(Qt.WA_StyledBackground, True)
        inspector_layout = QVBoxLayout()
        inspector_layout.setContentsMargins(12, 12, 12, 12)
        inspector_layout.setSpacing(10)
        inspector.setLayout(inspector_layout)
        inspector.setMinimumWidth(260)
        inspector.setMaximumWidth(360)
        self.inspector_title = QLabel(tr("workspace_inspector"))
        inspector_title = self.inspector_title
        inspector_title.setObjectName("WorkspacePanelTitle")
        inspector_layout.addWidget(inspector_title)
        self.selected_block_label = QLabel(tr("workspace_select_block"))
        self.selected_block_label.setWordWrap(True)
        inspector_layout.addWidget(self.selected_block_label)

        self.layers_label = QLabel(tr("workspace_layers"))
        layers_label = self.layers_label
        layers_label.setObjectName("WorkspacePanelTitle")
        inspector_layout.addWidget(layers_label)
        self.layers_list = create_list_widget("WorkspaceLayersList")
        self.layers_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.layers_list.currentItemChanged.connect(self._layer_selection_changed)
        inspector_layout.addWidget(self.layers_list, stretch=1)

        self.block_title_input = create_line_edit(
            tr("workspace_block_title"),
            "WorkspaceBlockTitleInput",
        )
        self.block_title_input.textChanged.connect(self._update_block_title)
        inspector_layout.addWidget(self.block_title_input)
        form = QFormLayout()
        self.block_col_span_spin = QSpinBox()
        self.block_col_span_spin.setRange(1, WORKSPACE_GRID_COLUMNS)
        self.block_col_span_spin.valueChanged.connect(self._update_block_col_span)
        self.block_row_span_spin = QSpinBox()
        self.block_row_span_spin.setRange(1, 8)
        self.block_row_span_spin.valueChanged.connect(self._update_block_row_span)
        form.addRow(tr("workspace_block_columns"), self.block_col_span_spin)
        form.addRow(tr("workspace_block_rows"), self.block_row_span_spin)
        inspector_layout.addLayout(form)
        self.edit_properties_btn = create_button(
            tr("workspace_properties_title"),
            "primary",
        )
        self.edit_properties_btn.clicked.connect(lambda: self._edit_block_properties(self._current_block_id()))
        self.duplicate_block_btn = create_button(tr("workspace_duplicate"), "secondary")
        self.duplicate_block_btn.clicked.connect(self._duplicate_selected_block)
        self.lock_block_btn = create_button(tr("workspace_lock"), "secondary")
        self.lock_block_btn.clicked.connect(self._toggle_selected_locked)
        self.visibility_block_btn = create_button(tr("workspace_hide"), "secondary")
        self.visibility_block_btn.clicked.connect(self._toggle_selected_visible)
        self.group_block_btn = create_button(tr("workspace_group"), "secondary")
        self.group_block_btn.clicked.connect(self._group_selected_blocks)
        self.ungroup_block_btn = create_button(tr("workspace_ungroup"), "secondary")
        self.ungroup_block_btn.clicked.connect(self._ungroup_selected_blocks)
        self.bring_forward_btn = create_button(tr("workspace_bring_forward"), "secondary")
        self.bring_forward_btn.clicked.connect(lambda: self._move_selected_layer(1))
        self.send_backward_btn = create_button(tr("workspace_send_backward"), "secondary")
        self.send_backward_btn.clicked.connect(lambda: self._move_selected_layer(-1))
        self.bring_to_front_btn = create_button(tr("workspace_to_front"), "secondary")
        self.bring_to_front_btn.clicked.connect(lambda: self._move_selected_layer(1, to_edge=True))
        self.send_to_back_btn = create_button(tr("workspace_to_back"), "secondary")
        self.send_to_back_btn.clicked.connect(lambda: self._move_selected_layer(-1, to_edge=True))
        align_row = QHBoxLayout()
        align_row.setContentsMargins(0, 0, 0, 0)
        self.align_left_btn = create_button(tr("workspace_align_left"), "secondary")
        self.align_center_btn = create_button(tr("workspace_align_center"), "secondary")
        self.align_right_btn = create_button(tr("workspace_align_right"), "secondary")
        self.align_top_btn = create_button(tr("workspace_align_top"), "secondary")
        self.fit_width_btn = create_button(tr("workspace_fit_width"), "secondary")
        self.distribute_h_btn = create_button(tr("workspace_space_h"), "secondary")
        self.distribute_v_btn = create_button(tr("workspace_space_v"), "secondary")
        for button, edge in (
            (self.align_left_btn, "left"),
            (self.align_center_btn, "center"),
            (self.align_right_btn, "right"),
            (self.align_top_btn, "top"),
            (self.fit_width_btn, "fit_width"),
        ):
            button.clicked.connect(lambda checked=False, value=edge: self._align_selected(value))
            align_row.addWidget(button)
        self.distribute_h_btn.clicked.connect(lambda: self._distribute_selected("horizontal"))
        self.distribute_v_btn.clicked.connect(lambda: self._distribute_selected("vertical"))
        align_row.addWidget(self.distribute_h_btn)
        align_row.addWidget(self.distribute_v_btn)
        self.remove_block_btn = create_button(tr("workspace_remove_block"), "danger")
        self.remove_block_btn.clicked.connect(self._remove_workspace_block)
        inspector_layout.addWidget(self.edit_properties_btn)
        inspector_layout.addWidget(self.duplicate_block_btn)
        inspector_layout.addWidget(self.lock_block_btn)
        inspector_layout.addWidget(self.visibility_block_btn)
        inspector_layout.addWidget(self.group_block_btn)
        inspector_layout.addWidget(self.ungroup_block_btn)
        inspector_layout.addWidget(self.bring_forward_btn)
        inspector_layout.addWidget(self.send_backward_btn)
        inspector_layout.addWidget(self.bring_to_front_btn)
        inspector_layout.addWidget(self.send_to_back_btn)
        inspector_layout.addLayout(align_row)
        inspector_layout.addWidget(self.remove_block_btn)
        inspector_layout.addStretch()
        splitter.addWidget(inspector)
        splitter.setSizes([280, 900, 300])

        self.block_remove_btn = self.remove_block_btn
        self.block_add_btn = self.add_selected_btn
        self.block_up_btn = create_button(tr("workspace_move_up"), "secondary")
        self.block_down_btn = create_button(tr("workspace_move_down"), "secondary")
        self.field_add_btn = create_button(tr("workspace_add_field"), "secondary")
        self.field_up_btn = create_button(tr("workspace_move_up"), "secondary")
        self.field_down_btn = create_button(tr("workspace_move_down"), "secondary")
        self.field_remove_btn = create_button(tr("workspace_remove_field"), "secondary")
        self.workspace_preview_title = QLabel(tr("workspace_preview_title"))
        self.workspace_preview_grid = QVBoxLayout()
        self.workspace_preview_grid.addWidget(
            QLabel(tr("workspace_canvas_preview_live"))
        )
        self.block_web_url_input = create_line_edit(
            tr("workspace_block_web_url"),
            "WorkspaceBlockWebUrlInput",
        )
        self.block_web_url_input.textChanged.connect(self._update_block_web_url)
        self.block_document_combo = create_combo_box()
        self.block_document_combo.addItem(tr("workspace_first_available_document"), "")
        for document_type, config in DOCUMENTS.items():
            self.block_document_combo.addItem(config.get("label", document_type), document_type)
        self.block_document_combo.currentIndexChanged.connect(self._update_block_document_type)

        self._load_workspaces()
        self._refresh_palette()

    def _block_label(self, block_type):
        return tr(BLOCK_LABELS.get(block_type, "workspace_block_unsupported"))

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _refresh_palette(self):
        if not hasattr(self, "palette_body_layout"):
            return
        query = self.palette_search.text().strip().lower() if hasattr(self, "palette_search") else ""
        self._clear_layout(self.palette_body_layout)
        shown = 0
        for category, block_types in BLOCK_CATEGORIES.items():
            matching = [
                block_type
                for block_type in block_types
                if (
                    not query
                    or query in category.lower()
                    or query in block_type.lower()
                    or query in self._block_label(block_type).lower()
                )
            ]
            if not matching:
                continue
            label = QLabel(category)
            label.setObjectName("MutedText")
            self.palette_body_layout.addWidget(label)
            for block_type in matching:
                palette = WorkspacePaletteButton(block_type, self._block_label(block_type))
                palette.addRequested.connect(self._add_palette_block)
                self.palette_body_layout.addWidget(palette)
                shown += 1
        if shown == 0:
            empty = QLabel(tr("workspace_no_blocks_match"))
            empty.setObjectName("MutedText")
            empty.setWordWrap(True)
            self.palette_body_layout.addWidget(empty)
        self.palette_body_layout.addStretch()

    def load_data(self):
        self._load_workspaces()

    def retranslate_ui(self):
        self.workspace_page_title.setText(tr("workspace_builder_title"))
        self.workspace_page_subtitle.setText(tr("workspace_builder_subtitle"))
        self.workspace_name_input.setPlaceholderText(tr("workspace_name_placeholder"))
        self.workspace_save_btn.setText(tr("workspace_save"))
        self.workspace_new_btn.setText(tr("workspace_new"))
        self.workspace_duplicate_btn.setText(tr("workspace_duplicate"))
        self.workspace_delete_btn.setText(tr("workspace_delete"))
        self.palette_label.setText(tr("workspace_blocks"))
        self.palette_search.setPlaceholderText(tr("workspace_search_blocks"))
        self.undo_btn.setText(tr("workspace_undo"))
        self.redo_btn.setText(tr("workspace_redo"))
        self.copy_btn.setText(tr("workspace_copy"))
        self.paste_btn.setText(tr("workspace_paste"))
        self.clear_canvas_btn.setText(tr("workspace_clear_canvas"))
        self.add_selected_btn.setText(tr("workspace_add_block"))
        self.inspector_title.setText(tr("workspace_inspector"))
        self.layers_label.setText(tr("workspace_layers"))
        self.edit_properties_btn.setText(tr("workspace_properties_title"))
        self.duplicate_block_btn.setText(tr("workspace_duplicate"))
        self.group_block_btn.setText(tr("workspace_group"))
        self.ungroup_block_btn.setText(tr("workspace_ungroup"))
        self.bring_forward_btn.setText(tr("workspace_bring_forward"))
        self.send_backward_btn.setText(tr("workspace_send_backward"))
        self.bring_to_front_btn.setText(tr("workspace_to_front"))
        self.send_to_back_btn.setText(tr("workspace_to_back"))
        self.align_left_btn.setText(tr("workspace_align_left"))
        self.align_center_btn.setText(tr("workspace_align_center"))
        self.align_right_btn.setText(tr("workspace_align_right"))
        self.align_top_btn.setText(tr("workspace_align_top"))
        self.fit_width_btn.setText(tr("workspace_fit_width"))
        self.distribute_h_btn.setText(tr("workspace_space_h"))
        self.distribute_v_btn.setText(tr("workspace_space_v"))
        self.remove_block_btn.setText(tr("workspace_remove_block"))
        self._populate_block_options()

    def _load_workspaces(self):
        self._workspaces = self.workspace_service.list_workspaces()
        self.workspaces_list.blockSignals(True)
        self.workspaces_list.clear()
        for workspace in self._workspaces:
            item = QListWidgetItem(workspace.get("name", tr("workspace_title")))
            item.setData(Qt.UserRole, workspace.get("id"))
            self.workspaces_list.addItem(item)
        self.workspaces_list.blockSignals(False)
        if self._workspaces:
            self.workspaces_list.setCurrentRow(0)
        else:
            workspace = self.workspace_service.save_workspace(new_workspace(tr("workspace_default_name")))
            self._workspaces = [workspace]
            self._load_workspaces()

    def _current_workspace(self):
        return next(
            (
                workspace
                for workspace in self._workspaces
                if workspace.get("id") == self._selected_workspace_id
            ),
            None,
        )

    def _current_block_id(self):
        return self.workspace_layout_editor.selected_block_id

    def _current_block(self):
        workspace = self._current_workspace()
        block_id = self._current_block_id()
        if not workspace or not block_id:
            return None
        return next((b for b in workspace.get("blocks", []) if b.get("id") == block_id), None)

    def _workspace_selection_changed(self, current, previous):
        _ = previous
        self._selected_workspace_id = current.data(Qt.UserRole) if current else None
        self._populate_workspace_editor()

    def _populate_workspace_editor(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        self.workspace_name_input.blockSignals(True)
        self.workspace_name_input.setText(workspace.get("name", ""))
        self.workspace_name_input.blockSignals(False)
        idx = self.workspace_size_combo.findData(workspace.get("dialog_size", "large"))
        self.workspace_size_combo.blockSignals(True)
        self.workspace_size_combo.setCurrentIndex(max(idx, 0))
        self.workspace_size_combo.blockSignals(False)
        self.workspace_layout_editor.set_workspace(workspace)
        first_block = (workspace.get("blocks") or [{}])[0].get("id")
        self.workspace_layout_editor.set_selected_block(first_block)
        self._refresh_layers_list()
        self._populate_block_options()

    def _select_block_from_layout(self, block_id):
        _ = block_id
        self._populate_block_options()

    def _populate_block_options(self):
        block = self._current_block()
        self._refresh_selection_metrics()
        self._sync_layer_selection()
        enabled = block is not None
        for widget in (
            self.block_title_input,
            self.block_col_span_spin,
            self.block_row_span_spin,
            self.edit_properties_btn,
            self.duplicate_block_btn,
            self.lock_block_btn,
            self.visibility_block_btn,
            self.group_block_btn,
            self.ungroup_block_btn,
            self.bring_forward_btn,
            self.send_backward_btn,
            self.bring_to_front_btn,
            self.send_to_back_btn,
            self.align_left_btn,
            self.align_center_btn,
            self.align_right_btn,
            self.align_top_btn,
            self.fit_width_btn,
            self.distribute_h_btn,
            self.distribute_v_btn,
            self.remove_block_btn,
        ):
            widget.setEnabled(enabled)
        if not block:
            self.selected_block_label.setText(tr("workspace_select_block"))
            self.block_title_input.clear()
            return
        selected_count = len(self.workspace_layout_editor.selected_block_ids)
        label = self._block_label(block.get("type"))
        self.selected_block_label.setText(
            tr("workspace_blocks_selected", count=selected_count)
            if selected_count > 1
            else label
        )
        selected_blocks = self.workspace_layout_editor._selected_blocks()
        all_locked = bool(selected_blocks) and all(
            bool(selected.get("locked")) for selected in selected_blocks
        )
        all_hidden = bool(selected_blocks) and all(
            selected.get("visible") is False for selected in selected_blocks
        )
        any_locked = any(bool(selected.get("locked")) for selected in selected_blocks)
        any_grouped = any(selected.get("group_id") for selected in selected_blocks)
        self.lock_block_btn.setText(
            tr("workspace_unlock") if all_locked else tr("workspace_lock")
        )
        self.visibility_block_btn.setText(
            tr("workspace_show") if all_hidden else tr("workspace_hide")
        )
        self.group_block_btn.setEnabled(enabled and selected_count > 1)
        self.ungroup_block_btn.setEnabled(enabled and any_grouped)
        for widget in (
            self.block_col_span_spin,
            self.block_row_span_spin,
            self.bring_forward_btn,
            self.send_backward_btn,
            self.bring_to_front_btn,
            self.send_to_back_btn,
            self.align_left_btn,
            self.align_center_btn,
            self.align_right_btn,
            self.align_top_btn,
            self.fit_width_btn,
            self.distribute_h_btn,
            self.distribute_v_btn,
            self.remove_block_btn,
        ):
            widget.setEnabled(enabled and not any_locked)
        self.block_title_input.blockSignals(True)
        self.block_title_input.setText(block.get("title", ""))
        self.block_title_input.blockSignals(False)
        layout = validate_block_layout(block)
        self.block_col_span_spin.blockSignals(True)
        self.block_col_span_spin.setValue(layout["col_span"])
        self.block_col_span_spin.blockSignals(False)
        self.block_row_span_spin.blockSignals(True)
        self.block_row_span_spin.setValue(layout["row_span"])
        self.block_row_span_spin.blockSignals(False)
        self.block_web_url_input.blockSignals(True)
        self.block_web_url_input.setText(block.get("web_url", ""))
        self.block_web_url_input.blockSignals(False)
        doc_idx = self.block_document_combo.findData(block.get("document_type", ""))
        self.block_document_combo.blockSignals(True)
        self.block_document_combo.setCurrentIndex(max(doc_idx, 0))
        self.block_document_combo.blockSignals(False)

    def _refresh_layers_list(self):
        if not hasattr(self, "layers_list"):
            return
        workspace = self._current_workspace()
        self._refreshing_layers = True
        self.layers_list.clear()
        if workspace:
            for block in reversed(workspace.get("blocks", [])):
                layout = validate_block_layout(block)
                title = block.get("title") or self._block_label(block.get("type"))
                markers = []
                if block.get("locked"):
                    markers.append(tr("workspace_locked_badge"))
                if block.get("visible") is False:
                    markers.append(tr("workspace_hidden_badge"))
                if block.get("group_id"):
                    markers.append(tr("workspace_grouped_badge"))
                marker_text = f" [{' / '.join(markers)}]" if markers else ""
                item = QListWidgetItem(
                    f"{title}{marker_text}  ({layout['col_span']}x{layout['row_span']} at {layout['col']},{layout['row']})"
                )
                item.setData(Qt.UserRole, block.get("id"))
                self.layers_list.addItem(item)
        self._refreshing_layers = False
        self._sync_layer_selection()

    def _sync_layer_selection(self):
        if not hasattr(self, "layers_list") or self._refreshing_layers:
            return
        selected_ids = set(self.workspace_layout_editor.selected_block_ids)
        self._refreshing_layers = True
        self.layers_list.clearSelection()
        for row in range(self.layers_list.count()):
            item = self.layers_list.item(row)
            selected = item.data(Qt.UserRole) in selected_ids
            item.setSelected(selected)
            if item.data(Qt.UserRole) == self.workspace_layout_editor.selected_block_id:
                self.layers_list.setCurrentItem(item)
        self._refreshing_layers = False

    def _layer_selection_changed(self, current, previous):
        _ = previous
        if self._refreshing_layers or current is None:
            return
        selected_ids = [
            item.data(Qt.UserRole)
            for item in self.layers_list.selectedItems()
            if item.data(Qt.UserRole)
        ]
        if not selected_ids:
            selected_ids = [current.data(Qt.UserRole)]
        self.workspace_layout_editor.selected_block_ids = selected_ids
        self.workspace_layout_editor.selected_block_id = selected_ids[-1]
        self.workspace_layout_editor.render()
        self._populate_block_options()

    def _refresh_selection_metrics(self):
        if not hasattr(self, "selection_metrics_label"):
            return
        summary = self.workspace_layout_editor.selection_summary()
        self.selection_metrics_label.setText(
            summary.get("text") or tr("workspace_no_selection")
        )
        hint = getattr(
            self.workspace_layout_editor,
            "interaction_hint",
            tr("workspace_ready"),
        )
        if hint == tr("workspace_ready"):
            hint = tr("workspace_shortcut_hint")
        self.shortcut_hint_label.setText(hint)

    def _workspace_layout_changed(self):
        self._refresh_layers_list()
        self._populate_block_options()

    def _new_workspace(self):
        workspace = self.workspace_service.save_workspace(new_workspace(tr("workspace_default_name")))
        self._load_workspaces()
        self._select_workspace(workspace.get("id"))

    def _duplicate_workspace(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        duplicate = self.workspace_service.duplicate_workspace(workspace["id"])
        self._load_workspaces()
        if duplicate:
            self._select_workspace(duplicate.get("id"))

    def _delete_workspace(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        confirm = show_message(
            self,
            tr("workspace_delete_confirm_title"),
            tr(
                "workspace_delete_confirm_message",
                name=workspace.get("name") or tr("workspace_title"),
            ),
            kind="question",
            buttons="yes_no",
        )
        if confirm not in {1, 16384}:
            return
        self.workspace_service.delete_workspace(workspace["id"])
        self._load_workspaces()

    def _select_workspace(self, workspace_id):
        for row in range(self.workspaces_list.count()):
            item = self.workspaces_list.item(row)
            if item.data(Qt.UserRole) == workspace_id:
                self.workspaces_list.setCurrentRow(row)
                return

    def _update_workspace_name(self, value):
        workspace = self._current_workspace()
        if workspace is not None:
            workspace["name"] = value
            item = self.workspaces_list.currentItem()
            if item:
                item.setText(value or tr("workspace_title"))

    def _update_workspace_size(self):
        workspace = self._current_workspace()
        if workspace is not None:
            workspace["dialog_size"] = self.workspace_size_combo.currentData()

    def _add_workspace_block(self):
        block_type = self.block_add_combo.currentData()
        block = self.workspace_layout_editor.add_block_at(block_type, row=0, col=0)
        if block:
            self._populate_block_options()

    def _add_palette_block(self, block_type):
        block = self.workspace_layout_editor.add_block_at(block_type, row=0, col=0)
        if block:
            self._populate_block_options()

    def _remove_workspace_block(self):
        selected_count = len(
            getattr(self.workspace_layout_editor, "selected_block_ids", [])
        )
        if selected_count:
            confirm = show_message(
                self,
                tr("workspace_remove_block_confirm_title"),
                tr("workspace_remove_block_confirm_message", count=selected_count),
                kind="question",
                buttons="yes_no",
            )
            if confirm not in {1, 16384}:
                return
        self.workspace_layout_editor.delete_selected()
        self._populate_block_options()

    def _duplicate_selected_block(self):
        block = self.workspace_layout_editor.duplicate_block()
        if block:
            self._populate_block_options()

    def _toggle_selected_locked(self):
        self.workspace_layout_editor.toggle_selected_locked()
        self._populate_block_options()

    def _toggle_selected_visible(self):
        self.workspace_layout_editor.toggle_selected_visible()
        self._populate_block_options()

    def _group_selected_blocks(self):
        self.workspace_layout_editor.group_selected()
        self._populate_block_options()

    def _ungroup_selected_blocks(self):
        self.workspace_layout_editor.ungroup_selected()
        self._populate_block_options()

    def _move_selected_layer(self, direction, to_edge=False):
        self.workspace_layout_editor.arrange_selected_layers(
            direction=direction,
            to_edge=to_edge,
        )
        self._populate_block_options()

    def _copy_selected_block(self):
        self.workspace_layout_editor.copy_selected()

    def _paste_block(self):
        block = self.workspace_layout_editor.paste_copied()
        if block:
            self._populate_block_options()

    def _clear_canvas(self):
        workspace = self._current_workspace()
        block_count = len(workspace.get("blocks", [])) if workspace else 0
        if block_count:
            confirm = show_message(
                self,
                tr("workspace_clear_canvas_confirm_title"),
                tr("workspace_clear_canvas_confirm_message", count=block_count),
                kind="question",
                buttons="yes_no",
            )
            if confirm not in {1, 16384}:
                return
        self.workspace_layout_editor.clear_blocks()
        self._populate_block_options()

    def _align_selected(self, edge):
        self.workspace_layout_editor.align_selected(edge)
        self._populate_block_options()

    def _distribute_selected(self, axis):
        self.workspace_layout_editor.distribute_selected(axis)
        self._populate_block_options()

    def _update_block_title(self, value):
        block = self._current_block()
        if block is not None:
            block["title"] = value
            self.workspace_layout_editor.render()
            self._refresh_layers_list()

    def _update_block_col_span(self, value):
        if self._current_block() is not None:
            self.workspace_layout_editor.update_selected_layout(col_span=value)

    def _update_block_row_span(self, value):
        if self._current_block() is not None:
            self.workspace_layout_editor.update_selected_layout(row_span=value)

    def _update_block_document_type(self):
        block = self._current_block()
        if block is not None and block.get("type") == "document_viewer":
            block["document_type"] = self.block_document_combo.currentData() or ""

    def _update_block_web_url(self, value):
        block = self._current_block()
        if block is not None and block.get("type") == "web_viewer":
            block["web_url"] = value
            self.workspace_layout_editor.render()

    def _edit_block_properties(self, block_id):
        if not block_id:
            return
        workspace = self._current_workspace()
        block = self._current_block()
        if not workspace or not block:
            return
        dialog = WorkspaceBlockPropertiesDialog(block, self)
        if dialog.exec() != QDialog.Accepted:
            return
        updated = dialog.updated_block()
        for index, existing in enumerate(workspace.get("blocks", [])):
            if existing.get("id") == block_id:
                workspace["blocks"][index] = updated
                break
        self.workspace_layout_editor.set_workspace(workspace)
        self.workspace_layout_editor.set_selected_block(block_id)
        self._refresh_layers_list()
        self._populate_block_options()

    def _undo(self):
        self.workspace_layout_editor.undo()
        self._populate_block_options()

    def _redo(self):
        self.workspace_layout_editor.redo()
        self._populate_block_options()

    def _zoom_in(self):
        self.workspace_layout_editor.zoom_in()
        self.zoom_reset_btn.setText(f"{round(self.workspace_layout_editor.zoom * 100)}%")

    def _zoom_out(self):
        self.workspace_layout_editor.zoom_out()
        self.zoom_reset_btn.setText(f"{round(self.workspace_layout_editor.zoom * 100)}%")

    def _zoom_reset(self):
        self.workspace_layout_editor.reset_zoom()
        self.zoom_reset_btn.setText("100%")

    def _save_current_workspace(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        saved = self.workspace_service.save_workspace(workspace)
        self._load_workspaces()
        self._select_workspace(saved.get("id"))
        if self.main_window and hasattr(self.main_window, "refresh_workspace_actions"):
            self.main_window.refresh_workspace_actions()
        show_message(self, tr("workspaces_title"), tr("workspace_saved"))
