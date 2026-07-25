from copy import deepcopy
import time

from PySide6.QtCore import QEventLoop, QPoint, Qt
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidgetAction,
    QWidget,
)

from services.settings_service import SettingsService
from services.workspace_block_registry import (
    BLOCK_CATEGORIES,
    BLOCK_LABELS,
    DEFAULT_DENSITIES,
    block_definition,
    block_presentation,
)
from services.workspace_layout import WORKSPACE_GRID_COLUMNS, validate_block_layout
from services.workspace_service import WorkspaceService, new_workspace
from ui.foundation import (
    create_button,
    create_combo_box,
    create_line_edit,
    create_list_widget,
    show_message,
)
from ui.foundation.background_loader import LatestRequestLoader
from ui.dialogs.missionary_workspace_dialog import MissionaryWorkspaceDialog
from ui.widgets.workspace_layout_editor import (
    GraphicsWorkspaceLayoutEditor,
    WorkspaceLayoutEditor,
    WorkspacePaletteButton,
)
from ui.widgets.editable_canvas import EditableCanvasEditorKit
from utils.constants import DOCUMENTS
from utils.i18n import field_label
from utils.language_helper import ui_text as tr
from utils.logger import logger


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


class WorkspaceFieldPill(QFrame):
    def __init__(self, field_key, label, remove_callback, parent=None):
        super().__init__(parent)
        self.field_key = field_key
        self.setObjectName("WorkspaceFieldPill")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(28)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(24, 24, 27, 0))
        self.setGraphicsEffect(self._shadow)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(6)
        self.setLayout(layout)

        self.text_label = QLabel(label)
        self.text_label.setObjectName("WorkspaceFieldPillText")
        self.text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.text_label)

        remove_btn = QPushButton("x")
        remove_btn.setObjectName("WorkspaceFieldPillRemove")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setFixedSize(18, 18)
        remove_btn.clicked.connect(lambda checked=False: remove_callback(field_key))
        layout.addWidget(remove_btn)

    def enterEvent(self, event):
        self._shadow.setBlurRadius(18)
        self._shadow.setOffset(0, 2)
        self._shadow.setColor(QColor(24, 24, 27, 32))
        font = self.text_label.font()
        font.setBold(True)
        self.text_label.setFont(font)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(24, 24, 27, 0))
        font = self.text_label.font()
        font.setBold(False)
        self.text_label.setFont(font)
        super().leaveEvent(event)


class WorkspaceBlockPropertiesDialog(QMenu):
    def __init__(self, block, parent=None):
        super().__init__(parent)
        self._result = QDialog.Rejected
        self.block = deepcopy(block or {})
        self.selected_fields = [
            field_key
            for field_key in self.block.get("fields", [])
            if field_key in FIELD_KEYS
        ]
        self.setWindowTitle(tr("workspace_properties_title"))
        self.setObjectName("WorkspaceTileContextMenu")

        content = QWidget()
        content.setObjectName("WorkspacePropertiesPopup")
        content.setFixedWidth(404)

        surface = QFrame()
        surface.setObjectName("WorkspacePropertiesSurface")
        surface.setAttribute(Qt.WA_StyledBackground, True)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        content.setLayout(root)
        root.addWidget(surface)

        wrapper_action = QWidgetAction(self)
        wrapper_action.setDefaultWidget(content)
        self.addAction(wrapper_action)

        surface_layout = QVBoxLayout()
        surface_layout.setContentsMargins(6, 6, 6, 6)
        surface_layout.setSpacing(8)
        surface.setLayout(surface_layout)

        header = QFrame()
        header.setObjectName("WorkspacePropertiesHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 2)
        header_layout.setSpacing(3)
        header.setLayout(header_layout)

        title = QLabel(tr("workspace_properties_title"))
        title.setObjectName("WorkspacePropertiesTitle")
        header_layout.addWidget(title)
        helper = QLabel(tr("workspace_properties_hint"))
        helper.setObjectName("WorkspacePropertiesSubtitle")
        helper.setWordWrap(True)
        header_layout.addWidget(helper)
        surface_layout.addWidget(header)

        body = QFrame()
        body.setObjectName("WorkspacePropertiesBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        body.setLayout(body_layout)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        body_layout.addLayout(form)

        self.title_input = create_line_edit(
            tr("workspace_block_title"),
            "WorkspaceBlockTitleDialogInput",
        )
        self.title_input.setText(self.block.get("title", ""))
        form.addRow(tr("workspace_properties_title_field"), self.title_input)

        definition = block_definition(self.block.get("type"))
        presentation = block_presentation(self.block)
        self.variant_combo = create_combo_box()
        for variant in definition.get("allowed_variants", []):
            self.variant_combo.addItem(
                tr(f"workspace_variant_{variant}"),
                variant,
            )
        variant_idx = self.variant_combo.findData(presentation["variant"])
        self.variant_combo.setCurrentIndex(max(variant_idx, 0))
        form.addRow(tr("workspace_properties_variant"), self.variant_combo)

        self.density_combo = create_combo_box()
        for density in DEFAULT_DENSITIES:
            self.density_combo.addItem(
                tr(f"workspace_density_{density}"),
                density,
            )
        density_idx = self.density_combo.findData(presentation["density"])
        self.density_combo.setCurrentIndex(max(density_idx, 0))
        form.addRow(tr("workspace_properties_density"), self.density_combo)

        self.content_limit_spin = QSpinBox()
        self.content_limit_spin.setRange(1, 12)
        self.content_limit_spin.setValue(presentation["content_limit"])
        form.addRow(tr("workspace_properties_content_limit"), self.content_limit_spin)

        self.fields_panel = QFrame()
        self.fields_panel.setObjectName("WorkspacePropertiesFieldsPanel")
        self.fields_panel.setAttribute(Qt.WA_StyledBackground, True)
        fields_layout = QVBoxLayout()
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(8)
        self.fields_panel.setLayout(fields_layout)

        self.selected_fields_frame = QFrame()
        self.selected_fields_frame.setObjectName("WorkspacePropertiesSelectedFields")
        self.selected_fields_frame.setAttribute(Qt.WA_StyledBackground, True)
        self.selected_fields_layout = QGridLayout()
        self.selected_fields_layout.setContentsMargins(8, 7, 8, 7)
        self.selected_fields_layout.setHorizontalSpacing(7)
        self.selected_fields_layout.setVerticalSpacing(7)
        self.selected_fields_frame.setLayout(self.selected_fields_layout)
        fields_layout.addWidget(self.selected_fields_frame)

        self.field_options_list = create_list_widget("WorkspaceFieldOptionList")
        self.field_options_list.setFixedHeight(188)
        self.field_options_list.itemClicked.connect(self._add_field_from_item)
        fields_layout.addWidget(self.field_options_list)
        form.addRow(tr("workspace_block_fields"), self.fields_panel)
        self._refresh_field_picker()

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

        self.links_input = create_list_widget("WorkspacePropertiesLinksList")
        links = (self.block.get("settings") or {}).get("links", [])
        self.links_input.setFixedHeight(112)
        for link in links:
            if isinstance(link, dict):
                label = link.get("label", "") or link.get("url", "")
                url = link.get("url", "") or label
                item = QListWidgetItem(f"{label}  -  {url}")
                item.setData(Qt.UserRole, {"label": label, "url": url})
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.links_input.addItem(item)
        form.addRow(tr("workspace_properties_links"), self.links_input)

        self.actions_input = create_list_widget("WorkspacePropertiesActionsList")
        actions = (self.block.get("settings") or {}).get("actions", [])
        self.actions_input.setFixedHeight(112)
        for action in actions:
            item = QListWidgetItem(str(action).replace("_", " ").title())
            item.setData(Qt.UserRole, action)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.actions_input.addItem(item)
        form.addRow(tr("workspace_properties_actions"), self.actions_input)

        block_type = self.block.get("type")
        for widget, visible in (
            (self.fields_panel, block_type == "personal_info"),
            (self.document_combo, block_type == "document_viewer"),
            (self.web_url_input, block_type == "web_viewer"),
            (self.links_input, block_type == "link_list"),
            (self.actions_input, block_type == "quick_actions"),
        ):
            try:
                form.setRowVisible(widget, visible)
            except AttributeError:
                widget.setVisible(visible)

        footer = QFrame()
        footer.setObjectName("WorkspacePropertiesFooter")
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(8)
        footer.setLayout(footer_layout)
        cancel_btn = QPushButton(tr("missionary_detail_cancel"))
        cancel_btn.setObjectName("WorkspacePropertiesCancelButton")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedHeight(34)
        apply_btn = QPushButton(tr("workspace_apply"))
        apply_btn.setObjectName("WorkspacePropertiesApplyButton")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.accept)
        footer_layout.addStretch()
        footer_layout.addWidget(cancel_btn)
        footer_layout.addWidget(apply_btn)
        body_layout.addWidget(footer)
        surface_layout.addWidget(body, stretch=1)

    def exec(self):
        self._result = QDialog.Rejected
        self.adjustSize()
        position = QCursor.pos()
        if self.parentWidget() is not None:
            anchor = QCursor.pos()
            screen = self.parentWidget().screen()
            if screen is not None:
                available = screen.availableGeometry()
                x = min(anchor.x(), available.right() - self.width() - 12)
                y = min(anchor.y(), available.bottom() - self.height() - 12)
                position = QPoint(max(available.left() + 12, x), max(available.top() + 12, y))
        loop = QEventLoop(self)
        self.aboutToHide.connect(loop.quit)
        self.popup(position)
        loop.exec()
        return self._result

    def accept(self):
        self._result = QDialog.Accepted
        self.close()

    def reject(self):
        self._result = QDialog.Rejected
        self.close()

    def _refresh_field_picker(self):
        while self.selected_fields_layout.count():
            item = self.selected_fields_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if self.selected_fields:
            for index, field_key in enumerate(self.selected_fields):
                pill = WorkspaceFieldPill(
                    field_key,
                    field_label(field_key),
                    self._remove_field,
                    self.selected_fields_frame,
                )
                self.selected_fields_layout.addWidget(pill, index // 2, index % 2)
        else:
            empty = QLabel(tr("workspace_properties_no_fields"))
            empty.setObjectName("WorkspacePropertiesNoFields")
            self.selected_fields_layout.addWidget(empty, 0, 0, 1, 2)
        self.selected_fields_layout.setColumnStretch(0, 1)
        self.selected_fields_layout.setColumnStretch(1, 1)

        self.field_options_list.blockSignals(True)
        self.field_options_list.clear()
        for field_key in FIELD_KEYS:
            item = QListWidgetItem(field_label(field_key))
            item.setData(Qt.UserRole, field_key)
            if field_key in self.selected_fields:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.field_options_list.addItem(item)
        self.field_options_list.blockSignals(False)

    def _add_field_from_item(self, item):
        field_key = item.data(Qt.UserRole)
        if field_key and field_key not in self.selected_fields:
            self.selected_fields.append(field_key)
            self._refresh_field_picker()

    def _remove_field(self, field_key):
        self.selected_fields = [
            existing
            for existing in self.selected_fields
            if existing != field_key
        ]
        self._refresh_field_picker()

    def updated_block(self):
        block = deepcopy(self.block)
        block["title"] = self.title_input.text().strip() or block.get("title", "")
        block["variant"] = self.variant_combo.currentData() or block.get("variant", "summary")
        block["density"] = self.density_combo.currentData() or block.get("density", "comfortable")
        block["content_limit"] = self.content_limit_spin.value()
        block["overflow"] = "view_all"
        block["layout"] = validate_block_layout(block)
        if block.get("type") == "personal_info":
            block["fields"] = list(self.selected_fields)
        if block.get("type") == "document_viewer":
            block["document_type"] = self.document_combo.currentData() or ""
        if block.get("type") == "web_viewer":
            block["web_url"] = self.web_url_input.text().strip()
        if block.get("type") == "link_list":
            links = []
            for row in range(self.links_input.count()):
                item = self.links_input.item(row)
                label, _, url = item.text().partition(" - ")
                label = label.strip()
                url = url.strip()
                if label or url:
                    links.append({"label": label or url, "url": url or label})
            block.setdefault("settings", {})["links"] = links
        if block.get("type") == "quick_actions":
            block.setdefault("settings", {})["actions"] = [
                self.actions_input.item(row).text().strip().lower().replace(" ", "_")
                for row in range(self.actions_input.count())
                if self.actions_input.item(row).text().strip()
            ]
        return block


class WorkspacesPage(QWidget):
    CACHE_TTL_SECONDS = 300.0

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
        self._workspace_dirty = False
        self._applying_workspace_snapshot = False
        self._last_refresh_at = 0.0
        self._refresh_loader = LatestRequestLoader(parent=self)
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

        self.editor_kit = EditableCanvasEditorKit(parent=self)

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
        self.workspaces_list.setMinimumHeight(120)

        self.block_library_panel = self.editor_kit.create_block_library(
            BLOCK_CATEGORIES,
            self._block_label,
            self._make_palette_button,
            tr("workspace_blocks"),
            tr("workspace_blocks_hint"),
            tr("workspace_search_blocks"),
            tr("workspace_no_blocks_match"),
        )
        self.block_library_panel.blockAddRequested.connect(self._add_palette_block)
        self.palette_label = self.block_library_panel.title_label
        self.palette_hint_label = self.block_library_panel.hint_label
        self.palette_search = self.block_library_panel.search
        self.palette_body = self.block_library_panel.body
        self.palette_body_layout = self.block_library_panel.body_layout
        self.block_library_panel.setMinimumHeight(220)

        self.left_panel_splitter = QSplitter(Qt.Vertical)
        self.left_panel_splitter.setObjectName("WorkspaceLeftPanelSplitter")
        self.left_panel_splitter.setChildrenCollapsible(False)
        self.left_panel_splitter.addWidget(self.workspaces_list)
        self.left_panel_splitter.addWidget(self.block_library_panel)
        self.left_panel_splitter.setSizes([220, 480])
        left_layout.addWidget(self.left_panel_splitter, stretch=1)
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
        self.canvas_controls = self.editor_kit.create_controls(
            show_grid=True,
            grid_min=56,
            grid_max=180,
            grid_step=8,
            grid_value=96,
            grid_suffix=tr("workspace_grid_px"),
        )
        self.zoom_out_btn = self.canvas_controls.zoom_out_btn
        self.zoom_reset_btn = self.canvas_controls.zoom_reset_btn
        self.zoom_in_btn = self.canvas_controls.zoom_in_btn
        self.zoom_fit_btn = self.canvas_controls.zoom_fit_btn
        self.grid_toggle = self.canvas_controls.grid_toggle
        self.grid_size_spin = self.canvas_controls.grid_size_spin
        self.preview_mode_btn = create_button(
            tr("workspace_preview_as_opened"),
            "secondary",
        )
        self.preview_mode_btn.setCheckable(True)
        self.open_preview_btn = create_button(
            tr("workspace_open_preview"),
            "secondary",
        )
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
        self.canvas_controls.zoomOutRequested.connect(self._zoom_out)
        self.canvas_controls.zoomResetRequested.connect(self._zoom_reset)
        self.canvas_controls.zoomInRequested.connect(self._zoom_in)
        self.canvas_controls.zoomFitRequested.connect(self._zoom_fit)
        self.canvas_controls.gridVisibleChanged.connect(self._toggle_workspace_grid)
        self.canvas_controls.gridSizeChanged.connect(self._update_workspace_grid_size)
        self.preview_mode_btn.toggled.connect(self._toggle_workspace_preview_mode)
        self.open_preview_btn.clicked.connect(self._open_workspace_preview)
        self.copy_btn.clicked.connect(self._copy_selected_block)
        self.paste_btn.clicked.connect(self._paste_block)
        self.clear_canvas_btn.clicked.connect(self._clear_canvas)
        self.add_selected_btn.clicked.connect(self._add_workspace_block)
        for button in (
            self.undo_btn,
            self.redo_btn,
            self.copy_btn,
            self.paste_btn,
            self.clear_canvas_btn,
            self.add_selected_btn,
            self.preview_mode_btn,
            self.open_preview_btn,
        ):
            button.setFixedHeight(30)
        toolbar.addWidget(self.undo_btn)
        toolbar.addWidget(self.redo_btn)
        toolbar.addWidget(self.canvas_controls)
        toolbar.addWidget(self.preview_mode_btn)
        toolbar.addWidget(self.open_preview_btn)
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

        canvas_scroll = self.editor_kit.create_scroll_area()
        canvas_scroll.setObjectName("WorkspaceCanvasScroll")
        self.canvas_scroll = canvas_scroll
        canvas_scroll.zoomRequested.connect(self._zoom_canvas_by)
        canvas_shell = QWidget()
        canvas_shell_layout = QVBoxLayout()
        canvas_shell_layout.setContentsMargins(0, 0, 0, 0)
        canvas_shell.setLayout(canvas_shell_layout)
        self.workspace_layout_editor = GraphicsWorkspaceLayoutEditor(self._block_label)
        self.workspace_layout_editor.blockSelected.connect(self._select_block_from_layout)
        self.workspace_layout_editor.editRequested.connect(self._edit_block_properties)
        self.workspace_layout_editor.layoutChanged.connect(self._workspace_layout_changed)
        self.workspace_layout_editor.interactionChanged.connect(self._refresh_selection_metrics)
        canvas_shell_layout.addWidget(self.workspace_layout_editor)
        canvas_scroll.setWidget(canvas_shell)
        center_layout.addWidget(canvas_scroll, stretch=1)
        splitter.addWidget(center)

        inspector = QFrame(self)
        inspector.setObjectName("WorkspaceInspector")
        inspector.setAttribute(Qt.WA_StyledBackground, True)
        inspector.setVisible(False)
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
        self.inspector_panel = inspector
        splitter.setSizes([280, 1200])

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

        self._refresh_palette()
        self._populate_block_options()

    def _block_label(self, block_type):
        return tr(BLOCK_LABELS.get(block_type, "workspace_block_unsupported"))

    def _make_palette_button(self, block_type):
        return WorkspacePaletteButton(block_type, self._block_label(block_type))

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
        if hasattr(self, "block_library_panel"):
            self.block_library_panel.refresh()
            return
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
            label.setObjectName("WorkspacePaletteCategory")
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

    def request_refresh(self, force=False):
        now = time.monotonic()
        cache_is_fresh = (
            bool(self._workspaces)
            and now - self._last_refresh_at < self.CACHE_TTL_SECONDS
        )
        if not force and (cache_is_fresh or self._workspace_dirty):
            return False

        service = self.workspace_service
        default_name = tr("workspace_default_name")

        def fetch_workspaces():
            workspaces = list(service.list_workspaces() or [])
            if not workspaces:
                workspace = service.save_workspace(
                    new_workspace(default_name)
                )
                workspaces = [workspace]
            return workspaces

        self._refresh_loader.request(
            fetch_workspaces,
            on_success=self._apply_workspace_snapshot,
            on_error=self._workspace_refresh_failed,
        )
        return True

    def load_data(self):
        """Compatibility entry point for callers that need a forced refresh."""
        return self.request_refresh(force=True)

    def retranslate_ui(self):
        self.workspace_page_title.setText(tr("workspace_builder_title"))
        self.workspace_page_subtitle.setText(tr("workspace_builder_subtitle"))
        self.workspace_name_input.setPlaceholderText(tr("workspace_name_placeholder"))
        self.workspace_save_btn.setText(tr("workspace_save"))
        self.workspace_new_btn.setText(tr("workspace_new"))
        self.workspace_duplicate_btn.setText(tr("workspace_duplicate"))
        self.workspace_delete_btn.setText(tr("workspace_delete"))
        self.block_library_panel.set_texts(
            tr("workspace_blocks"),
            tr("workspace_blocks_hint"),
            tr("workspace_search_blocks"),
            tr("workspace_no_blocks_match"),
        )
        self.undo_btn.setText(tr("workspace_undo"))
        self.redo_btn.setText(tr("workspace_redo"))
        self.canvas_controls.retranslate_ui()
        self.preview_mode_btn.setText(
            tr("workspace_back_to_edit")
            if self.preview_mode_btn.isChecked()
            else tr("workspace_preview_as_opened")
        )
        self.open_preview_btn.setText(tr("workspace_open_preview"))
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
        """Synchronously reconcile after a local workspace mutation."""
        self._refresh_loader.cancel()
        workspaces = list(self.workspace_service.list_workspaces() or [])
        if not workspaces:
            workspace = self.workspace_service.save_workspace(
                new_workspace(tr("workspace_default_name"))
            )
            workspaces = [workspace]
        self._apply_workspace_snapshot(workspaces)

    def _apply_workspace_snapshot(self, workspaces):
        selected_id = self._selected_workspace_id
        self._applying_workspace_snapshot = True
        try:
            self._workspaces = list(workspaces or [])
            self.workspaces_list.blockSignals(True)
            self.workspaces_list.clear()
            for workspace in self._workspaces:
                item = QListWidgetItem(
                    workspace.get("name", tr("workspace_title"))
                )
                item.setData(Qt.UserRole, workspace.get("id"))
                self.workspaces_list.addItem(item)
            self.workspaces_list.blockSignals(False)
            if self._workspaces:
                selected_row = 0
                for row, workspace in enumerate(self._workspaces):
                    if workspace.get("id") == selected_id:
                        selected_row = row
                        break
                self.workspaces_list.setCurrentRow(selected_row)
            else:
                self._selected_workspace_id = None
                self._populate_block_options()
            self._workspace_dirty = False
            self._last_refresh_at = time.monotonic()
        finally:
            self._applying_workspace_snapshot = False

    @staticmethod
    def _workspace_refresh_failed(error):
        logger.error(
            "Failed to load workspaces",
            exc_info=(type(error), error, error.__traceback__),
        )

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
        self._mark_workspace_dirty()
        self._refresh_layers_list()
        self._populate_block_options()

    def _mark_workspace_dirty(self):
        if self._applying_workspace_snapshot:
            return
        self._workspace_dirty = True
        if self._refresh_loader.busy:
            self._refresh_loader.cancel()

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
            self._mark_workspace_dirty()
            workspace["name"] = value
            item = self.workspaces_list.currentItem()
            if item:
                item.setText(value or tr("workspace_title"))

    def _update_workspace_size(self):
        workspace = self._current_workspace()
        if workspace is not None:
            self._mark_workspace_dirty()
            dialog_size = self.workspace_size_combo.currentData()
            workspace["dialog_size"] = dialog_size
            if getattr(self.workspace_layout_editor, "workspace", None) is not None:
                self.workspace_layout_editor.workspace["dialog_size"] = dialog_size
            self.workspace_layout_editor.render()
            self._refresh_zoom_label()

    def _toggle_workspace_preview_mode(self, checked):
        if hasattr(self.workspace_layout_editor, "set_preview_as_opened"):
            self.workspace_layout_editor.set_preview_as_opened(checked)
        self.preview_mode_btn.setText(
            tr("workspace_back_to_edit")
            if checked
            else tr("workspace_preview_as_opened")
        )

    def _open_workspace_preview(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        preview_host = getattr(self.workspace_layout_editor, "_preview_host", None)
        missionary = getattr(getattr(preview_host, "context", None), "missionary", None)
        opener = getattr(self.main_window, "open_missionary_workspace", None)
        if callable(opener) and missionary is not None:
            if opener(missionary, workspace):
                return
        dialog = MissionaryWorkspaceDialog(
            missionary,
            deepcopy(workspace),
            parent=self,
            context=getattr(preview_host, "context", None),
        )
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        self._workspace_preview_dialog = dialog
        dialog.show()

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
            self._mark_workspace_dirty()
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
            self._mark_workspace_dirty()
            block["document_type"] = self.block_document_combo.currentData() or ""

    def _update_block_web_url(self, value):
        block = self._current_block()
        if block is not None and block.get("type") == "web_viewer":
            self._mark_workspace_dirty()
            block["web_url"] = value
            self.workspace_layout_editor.render()

    def _edit_block_properties(self, block_id):
        if not block_id:
            return
        workspace = self._current_workspace()
        block = next(
            (
                item
                for item in (workspace or {}).get("blocks", [])
                if item.get("id") == block_id
            ),
            None,
        )
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
        self._set_workspace_zoom(self.workspace_layout_editor.zoom + 0.1)

    def _zoom_out(self):
        self._set_workspace_zoom(self.workspace_layout_editor.zoom - 0.1)

    def _zoom_reset(self):
        self._set_workspace_zoom(1.0)

    def _zoom_fit(self):
        self.workspace_layout_editor.fit_width_zoom(
            self.canvas_scroll.viewport().width()
        )
        self._refresh_zoom_label()

    def _set_workspace_zoom(self, value):
        self.workspace_layout_editor.set_zoom(value)
        self._refresh_zoom_label()

    def _refresh_zoom_label(self):
        self.canvas_controls.set_zoom_percent(self.workspace_layout_editor.zoom)

    def _zoom_canvas_by(self, factor, anchor_view_pos):
        old_zoom = max(self.workspace_layout_editor.zoom, 0.01)
        anchor_content_pos = self.workspace_layout_editor.mapFrom(
            self.canvas_scroll.viewport(),
            anchor_view_pos,
        )
        self._set_workspace_zoom(old_zoom * factor)
        scale_ratio = self.workspace_layout_editor.zoom / old_zoom
        target_x = int(anchor_content_pos.x() * scale_ratio) - anchor_view_pos.x()
        target_y = int(anchor_content_pos.y() * scale_ratio) - anchor_view_pos.y()
        self.canvas_scroll.horizontalScrollBar().setValue(target_x)
        self.canvas_scroll.verticalScrollBar().setValue(target_y)

    def _toggle_workspace_grid(self, checked):
        self.workspace_layout_editor.set_grid_visible(checked)

    def _update_workspace_grid_size(self, value):
        self.workspace_layout_editor.set_grid_size(value)

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
