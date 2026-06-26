from copy import deepcopy
from types import SimpleNamespace

from services.settings_service import SettingsService
from services.workspace_service import new_workspace
from ui.pages.workspaces_page import WorkspacesPage
from ui.widgets.workspace_layout_editor import WorkspaceLayoutEditor


class MemoryWorkspaceService:
    def __init__(self):
        self.items = []

    def list_workspaces(self):
        return deepcopy(self.items)

    def save_workspace(self, workspace):
        saved = deepcopy(workspace)
        self.items = [
            item
            for item in self.items
            if item.get("id") != saved.get("id")
        ]
        self.items.append(saved)
        return deepcopy(saved)

    def duplicate_workspace(self, workspace_id):
        return None

    def delete_workspace(self, workspace_id):
        self.items = [
            item
            for item in self.items
            if item.get("id") != workspace_id
        ]
        return True


def test_workspace_layout_editor_updates_source_layout(qapp):
    _ = qapp
    workspace = new_workspace("Grid")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    editor.set_selected_block(workspace["blocks"][0]["id"])

    editor.update_selected_layout(col_span=12, row_span=3)

    assert workspace["blocks"][0]["layout"]["col_span"] == 12
    assert workspace["blocks"][0]["layout"]["row_span"] == 3


def test_workspaces_page_renders_editor_and_preview(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    page.block_col_span_spin.setValue(12)

    assert page.workspace_layout_editor.workspace is not None
    assert page._current_block()["layout"]["col_span"] == 12
    assert page.workspace_preview_grid.count() > 0
