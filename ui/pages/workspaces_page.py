from PySide6.QtWidgets import QVBoxLayout

from ui.foundation import PageHeader, divider
from ui.pages.settings_page import SettingsPage
from utils.language_helper import ui_text as tr


class WorkspacesPage(SettingsPage):
    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        self.header = PageHeader(
            tr("workspaces_title"),
            tr("workspaces_hint"),
        )
        outer.addWidget(self.header)
        outer.addWidget(divider())
        outer.addWidget(self._build_workspaces_tab(), stretch=1)

    def load_data(self):
        if hasattr(self, "workspaces_list"):
            self._load_workspaces()

    def retranslate_ui(self):
        self.workspaces_list_title.setText(tr("workspaces_title"))
        self.workspace_editor_title.setText(tr("workspace_editor_title"))
        self.workspace_new_btn.setText(tr("workspace_new"))
        self.workspace_duplicate_btn.setText(tr("workspace_duplicate"))
        self.workspace_delete_btn.setText(tr("workspace_delete"))
        self.workspace_blocks_label.setText(tr("workspace_blocks"))
        self.block_add_btn.setText(tr("workspace_add_block"))
        self.block_up_btn.setText(tr("workspace_move_up"))
        self.block_down_btn.setText(tr("workspace_move_down"))
        self.block_remove_btn.setText(tr("workspace_remove_block"))
        self.field_add_btn.setText(tr("workspace_add_field"))
        self.field_up_btn.setText(tr("workspace_move_up"))
        self.field_down_btn.setText(tr("workspace_move_down"))
        self.field_remove_btn.setText(tr("workspace_remove_field"))
        self.workspace_preview_title.setText(tr("workspace_preview_title"))
        self.workspace_save_btn.setText(tr("workspace_save"))
