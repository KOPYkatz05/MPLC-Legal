from copy import deepcopy
from types import SimpleNamespace

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QWidget,
)

from services.settings_service import SettingsService
from services.workspace_service import new_block, new_workspace
from ui.dialogs import missionary_workspace_dialog as workspace_dialog_module
from ui.dialogs.missionary_workspace_dialog import (
    MissionaryWorkspaceDialog,
    WorkspaceBlockFactory,
)
from services.missionary_detail_layout_service import MissionaryDetailLayoutService
from ui.pages.missionary_detail_page import (
    MissionaryDetailLayoutDialog,
    MissionaryDetailPage,
)
from ui.pages.missionary_workspace_page import MissionaryWorkspacePage
from ui.pages.workspaces_page import WorkspacesPage, WorkspaceBlockPropertiesDialog
from ui.widgets.workspace_layout_editor import (
    WorkspaceLayoutEditor,
    WorkspaceLayoutTile,
    WorkspacePaletteButton,
)
from utils.i18n import get_i18n


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

    def get_workspace(self, workspace_id):
        for item in self.items:
            if item.get("id") == workspace_id:
                return deepcopy(item)
        return None

    def duplicate_workspace(self, workspace_id):
        return None

    def delete_workspace(self, workspace_id):
        self.items = [
            item
            for item in self.items
            if item.get("id") != workspace_id
        ]
        return True


def _widget_texts(widget):
    return [
        child.text()
        for child in widget.findChildren(QLabel)
        if child.text()
    ]


class FakeWorkspaceDialog:
    def __init__(self):
        self.preview_mode = False
        self.opened_urls = []
        self.actions = []
        self.context = SimpleNamespace(
            missionary=SimpleNamespace(
                full_name="Test Missionary",
                current_stage="INTERPOL",
                phone="555-0100",
                email="test@example.org",
                emergency_contact="Office",
                folder_path="C:/Missionary",
                interpol_appointment_date="2026-07-01",
            ),
            documents=[
                SimpleNamespace(document_type="PASSPORT", uploaded_at=2),
                SimpleNamespace(document_type="FBI", uploaded_at=1),
            ],
            workflows=[
                SimpleNamespace(stage_name="INTERPOL", status="IN PROGRESS"),
            ],
            tasks=[
                {"id": 1, "title": "Call office"},
            ],
            residency_rows=[],
            missing_groups=[("INTERPOL", ["FBI"], True)],
        )

    @staticmethod
    def normalized_web_url(value):
        return value

    def open_web_url(self, url):
        self.opened_urls.append(url)

    def upload_document(self):
        self.actions.append("upload_document")

    def add_task(self):
        self.actions.append("add_task")

    def open_folder_path(self):
        self.actions.append("open_folder")

    def update_current_workflow(self):
        self.actions.append("update_workflow")


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class FakeWebEngineView(QWidget):
    created = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loadStarted = FakeSignal()
        self.loadFinished = FakeSignal()
        self.loaded_url = None
        FakeWebEngineView.created.append(self)

    def setUrl(self, url):
        self.loaded_url = url
        self.loadStarted.emit()
        self.loadFinished.emit(True)


def test_workspace_layout_editor_updates_source_layout(qapp):
    _ = qapp
    workspace = new_workspace("Grid")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("personal_info")
    editor.set_selected_block(block["id"])

    editor.update_selected_layout(col_span=12, row_span=3)

    assert workspace["blocks"][0]["layout"]["col_span"] == 12
    assert workspace["blocks"][0]["layout"]["row_span"] == 3


def test_missionary_detail_layout_dialog_uses_workspace_editor(qapp):
    _ = qapp
    dialog = MissionaryDetailLayoutDialog(
        MissionaryDetailLayoutService.default_layout()
    )

    editor = dialog.findChild(WorkspaceLayoutEditor, "MissionaryDetailLayoutEditor")
    assert editor is not None
    assert editor.workspace["blocks"]


def test_missionary_detail_layout_edit_mode_shows_status_banner(qapp):
    _ = qapp
    page = MissionaryDetailPage(
        SimpleNamespace(workspace_service=MemoryWorkspaceService())
    )
    layout = MissionaryDetailLayoutService.default_layout()
    page.detail_layout_service = SimpleNamespace(get_layout=lambda: layout)
    page.show()
    qapp.processEvents()

    try:
        assert page.layout_edit_banner.isVisible() is False

        page._edit_layout()

        assert page.layout_edit_banner.isVisible() is True
        assert page.layout_edit_banner_title.text() == "Editing layout"
        assert "Drag or resize" in page.layout_edit_banner_hint.text()
        assert page.edit_layout_button.isVisible() is False
        assert page.save_layout_button.isVisible() is True
        assert page.actions_button.isVisible() is False
        assert page.delete_button.isVisible() is False

        page._cancel_layout_edit()

        assert page.layout_edit_banner.isVisible() is False
        assert page.edit_layout_button.isVisible() is True
        assert page.actions_button.isVisible() is True
    finally:
        page.close()


def test_missionary_detail_layout_dialog_reset_restores_default(qapp):
    _ = qapp
    layout = MissionaryDetailLayoutService.default_layout()
    layout["blocks"] = [layout["blocks"][0]]
    dialog = MissionaryDetailLayoutDialog(layout)

    dialog._reset_to_default()
    section_types = {
        block["type"]
        for block in dialog.updated_layout()["blocks"]
    }

    assert {
        "overview",
        "workflow",
        "open_tasks",
        "documents",
        "missing_documents",
        "details_summary",
        "details_identity",
        "details_credentials",
        "details_legal_timeline",
        "details_residency",
    }.issubset(section_types)


def test_missionary_detail_layout_dialog_switches_between_tab_canvases(qapp):
    _ = qapp
    dialog = MissionaryDetailLayoutDialog(
        MissionaryDetailLayoutService.default_layout()
    )
    editor = dialog.findChild(WorkspaceLayoutEditor, "MissionaryDetailLayoutEditor")

    overview_types = {
        block["type"]
        for block in editor.workspace["blocks"]
    }
    dialog.tab_combo.setCurrentIndex(dialog.tab_combo.findData("details"))
    details_types = {
        block["type"]
        for block in editor.workspace["blocks"]
    }

    assert "overview" in overview_types
    assert "details_summary" not in overview_types
    assert "details_summary" in details_types
    assert "overview" not in details_types


def test_missionary_detail_layout_dialog_keeps_fixed_sections(qapp):
    _ = qapp
    dialog = MissionaryDetailLayoutDialog(
        MissionaryDetailLayoutService.default_layout()
    )
    editor = dialog.findChild(WorkspaceLayoutEditor, "MissionaryDetailLayoutEditor")
    first_id = editor.workspace["blocks"][0]["id"]

    editor.set_selected_block(first_id)
    editor.delete_selected()
    editor.duplicate_block(first_id)

    section_types = [block["type"] for block in editor.workspace["blocks"]]
    assert len(section_types) == len(set(section_types))
    assert first_id in {block["id"] for block in editor.workspace["blocks"]}


def test_workspace_layout_editor_allows_structure_changes_by_default(qapp):
    _ = qapp
    workspace = new_workspace("Flexible")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents")

    duplicate = editor.duplicate_block(block["id"])
    editor.delete_block(block["id"])

    assert duplicate is not None
    assert block["id"] not in {item["id"] for item in workspace["blocks"]}


def test_missionary_detail_overview_uses_saved_layout(qapp):
    _ = qapp
    canvas = QWidget()
    overview = QLabel("Overview")
    documents = QLabel("Documents")

    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    page.overview_layout_canvas = canvas
    page._overview_sections = {
        "overview": overview,
        "documents": documents,
    }
    page.detail_layout_service = SimpleNamespace(
        get_layout=lambda: {
            "blocks": [
                {
                    "id": "documents",
                    "type": "documents",
                    "layout": {
                        "row": 0,
                        "col": 0,
                        "row_span": 1,
                        "col_span": 12,
                    },
                },
                {
                    "id": "overview",
                    "type": "overview",
                    "layout": {
                        "row": 1,
                        "col": 0,
                        "row_span": 1,
                        "col_span": 6,
                    },
                },
            ]
        }
    )

    MissionaryDetailPage._apply_overview_layout(page)

    assert documents.parentWidget() is canvas
    assert overview.parentWidget() is canvas
    assert documents.geometry().y() < overview.geometry().y()


def test_missionary_detail_details_tab_uses_saved_layout(qapp):
    _ = qapp
    canvas = QWidget()
    summary = QLabel("Summary")
    credentials = QLabel("Credentials")

    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    page.details_layout_canvas = canvas
    page._details_sections = {
        "details_summary": summary,
        "details_credentials": credentials,
    }
    page.detail_layout_service = SimpleNamespace(
        get_layout=lambda: {
            "blocks": [
                {
                    "id": "details_credentials",
                    "type": "details_credentials",
                    "tab": "details",
                    "layout": {
                        "row": 0,
                        "col": 0,
                        "row_span": 1,
                        "col_span": 12,
                    },
                },
                {
                    "id": "details_summary",
                    "type": "details_summary",
                    "tab": "details",
                    "layout": {
                        "row": 1,
                        "col": 0,
                        "row_span": 1,
                        "col_span": 6,
                    },
                },
            ]
        }
    )

    MissionaryDetailPage._apply_details_layout(page)

    assert credentials.parentWidget() is canvas
    assert summary.parentWidget() is canvas
    assert credentials.geometry().y() < summary.geometry().y()


def test_missionary_detail_layout_edit_uses_free_card_geometry(qapp):
    _ = qapp
    layout = MissionaryDetailLayoutService.default_layout()
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    page._layout_editing = True
    page._layout_edit_payload = layout
    page._layout_preview_payload = None
    page._layout_drag_state = None
    page.detail_layout_service = SimpleNamespace(get_layout=lambda: layout)

    overview_canvas = QWidget()
    overview = QLabel("Overview")
    documents = QLabel("Documents")
    page.overview_layout_canvas = overview_canvas
    page._overview_sections = {
        "overview": overview,
        "documents": documents,
    }

    details_canvas = QWidget()
    page.details_layout_canvas = details_canvas
    page._details_sections = {}

    MissionaryDetailPage._apply_overview_layout(page)

    original_overview_x = overview.geometry().x()
    original_overview_y = overview.geometry().y()

    page._layout_drag_state = {
        "base_payload": deepcopy(layout),
    }
    assert MissionaryDetailPage._preview_free_layout(
        page,
        "overview",
        documents.geometry(),
    )

    overview_block = MissionaryDetailPage._layout_block_for_section(
        page,
        "overview",
    )
    preview_overview_block = MissionaryDetailPage._layout_block_for_section(
        page,
        "overview",
        page._layout_preview_payload,
    )
    documents_block = MissionaryDetailPage._layout_block_for_section(
        page,
        "documents",
        page._layout_preview_payload,
    )
    assert overview_block["free_layout"]["x"] == original_overview_x
    assert overview_block["free_layout"]["y"] == original_overview_y
    assert preview_overview_block["free_layout"]["x"] == documents.geometry().x()
    assert (
        preview_overview_block["free_layout"]["width"]
        == documents.geometry().width()
    )
    assert (
        documents_block["free_layout"]["y"]
        >= overview.geometry().bottom() + 1
    )


def test_missionary_detail_layout_preview_commits_or_rebounds(qapp):
    _ = qapp
    layout = MissionaryDetailLayoutService.default_layout()
    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    page._layout_editing = True
    page._layout_edit_payload = layout
    page._layout_preview_payload = None
    page._layout_drag_state = None
    page.detail_layout_service = SimpleNamespace(get_layout=lambda: layout)

    overview_canvas = QWidget()
    overview = QLabel("Overview")
    documents = QLabel("Documents")
    page.overview_layout_canvas = overview_canvas
    page._overview_sections = {
        "overview": overview,
        "documents": documents,
    }
    page.details_layout_canvas = QWidget()
    page._details_sections = {}

    MissionaryDetailPage._apply_overview_layout(page)
    original_rect = overview.geometry()
    target_rect = documents.geometry()
    page._layout_drag_state = {
        "base_payload": deepcopy(layout),
    }

    assert MissionaryDetailPage._preview_free_layout(
        page,
        "overview",
        target_rect,
    )
    MissionaryDetailPage._rebound_layout_preview(page)

    assert page._layout_preview_payload is None
    assert overview.geometry() == original_rect
    assert (
        MissionaryDetailPage._layout_block_for_section(
            page,
            "overview",
        )["free_layout"]["x"]
        == original_rect.x()
    )

    page._layout_drag_state = {
        "base_payload": deepcopy(layout),
    }
    assert MissionaryDetailPage._preview_free_layout(
        page,
        "overview",
        target_rect,
    )
    MissionaryDetailPage._commit_layout_preview(page)

    assert page._layout_preview_payload is None
    assert (
        MissionaryDetailPage._layout_block_for_section(
            page,
            "overview",
        )["free_layout"]["x"]
        == target_rect.x()
    )


def test_workspace_layout_editor_modern_actions(qapp):
    _ = qapp
    workspace = new_workspace("Actions")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("personal_info")
    second = editor.duplicate_block(first["id"])

    assert len(workspace["blocks"]) == 2
    assert second["id"] != first["id"]
    assert editor.selected_block_id == second["id"]

    editor.move_block_layer(second["id"], -1)
    assert workspace["blocks"][0]["id"] == second["id"]

    editor.delete_block(second["id"])
    assert len(workspace["blocks"]) == 1
    assert workspace["blocks"][0]["id"] == first["id"]


def test_workspace_layout_editor_swaps_block_layouts(qapp):
    _ = qapp
    workspace = new_workspace("Swap")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=3, col=6)
    first_layout = deepcopy(editor._block(first["id"])["layout"])
    second_layout = deepcopy(editor._block(second["id"])["layout"])

    assert editor.swap_block_layouts(first["id"], second["id"])

    assert editor._block(first["id"])["layout"] == second_layout
    assert editor._block(second["id"])["layout"] == first_layout
    assert editor.selected_block_id == first["id"]

    editor.undo()
    assert workspace["blocks"][0]["layout"] == first_layout
    assert workspace["blocks"][1]["layout"] == second_layout


def test_workspace_layout_editor_clipboard_and_alignment(qapp):
    _ = qapp
    workspace = new_workspace("Clipboard")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=3, col=3)
    editor.set_selected_block(block["id"])

    assert editor.copy_selected()
    pasted = editor.paste_copied()
    assert pasted is not None
    assert len(workspace["blocks"]) == 2

    editor.align_selected("right")
    assert workspace["blocks"][1]["layout"]["col"] == 6

    editor.align_selected("fit_width")
    assert workspace["blocks"][1]["layout"]["col"] == 0
    assert workspace["blocks"][1]["layout"]["col_span"] == 12

    editor.nudge_selected(row_delta=2, col_delta=1)
    assert workspace["blocks"][1]["layout"]["row"] >= 2


def test_workspace_layout_editor_multi_select_alignment_and_distribution(qapp):
    _ = qapp
    workspace = new_workspace("Multi")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=4)
    third = editor.add_block_at("workflow", row=4, col=8)

    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)
    editor.select_block(third["id"], additive=True)

    assert editor.selected_block_ids == [first["id"], second["id"], third["id"]]

    editor.align_selected("left")
    assert all(block["layout"]["col"] == 0 for block in workspace["blocks"])
    assert editor.selection_summary()["count"] == 3

    workspace["blocks"][0]["layout"]["col"] = 0
    workspace["blocks"][1]["layout"]["col"] = 3
    workspace["blocks"][2]["layout"]["col"] = 6
    editor.distribute_selected("horizontal")

    cols = [block["layout"]["col"] for block in workspace["blocks"]]
    assert cols == sorted(cols)


def test_workspace_layout_editor_arranges_multi_selected_layers(qapp):
    _ = qapp
    workspace = new_workspace("Layer Arrange")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents")
    second = editor.add_block_at("notes")
    third = editor.add_block_at("workflow")
    fourth = editor.add_block_at("open_tasks")

    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)

    editor.arrange_selected_layers(direction=1)
    assert [block["id"] for block in workspace["blocks"]] == [
        third["id"],
        first["id"],
        second["id"],
        fourth["id"],
    ]

    editor.arrange_selected_layers(direction=1, to_edge=True)
    assert [block["id"] for block in workspace["blocks"]][-2:] == [
        first["id"],
        second["id"],
    ]

    editor.arrange_selected_layers(direction=-1, to_edge=True)
    assert [block["id"] for block in workspace["blocks"]][:2] == [
        first["id"],
        second["id"],
    ]


def test_workspace_layout_editor_multi_select_copy_paste_delete_nudge(qapp):
    _ = qapp
    workspace = new_workspace("Group Ops")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=1, col=3)
    third = editor.add_block_at("workflow", row=4, col=6)

    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)
    assert editor.copy_selected()

    pasted = editor.paste_copied()
    assert pasted is not None
    assert len(workspace["blocks"]) == 5
    assert len(editor.selected_block_ids) == 2

    selected_before = {
        block["id"]: dict(block["layout"])
        for block in workspace["blocks"]
        if block["id"] in editor.selected_block_ids
    }
    editor.nudge_selected(row_delta=1, col_delta=1)
    for block in workspace["blocks"]:
        if block["id"] in selected_before:
            assert block["layout"]["row"] == selected_before[block["id"]]["row"] + 1
            assert block["layout"]["col"] == selected_before[block["id"]]["col"] + 1

    editor.delete_selected()
    assert len(workspace["blocks"]) == 3
    assert {block["id"] for block in workspace["blocks"]} == {
        first["id"],
        second["id"],
        third["id"],
    }


def test_workspace_layout_editor_multi_selected_tile_drag_state(qapp):
    _ = qapp
    workspace = new_workspace("Group Drag")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=3)
    third = editor.add_block_at("workflow", row=5, col=6)
    editor._block(third["id"])["locked"] = True
    locked_start = dict(editor._block(third["id"])["layout"])

    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)
    editor.select_block(third["id"], additive=True)

    editor.select_block_for_drag(second["id"], additive=False)
    assert editor.selected_block_ids == [first["id"], second["id"], third["id"]]
    assert editor.selected_block_id == second["id"]

    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)
    editor.select_block(third["id"], additive=True)
    start_layouts = {
        block["id"]: dict(block["layout"])
        for block in editor._selected_blocks()
        if not block.get("locked")
    }
    editor.preview_selected_move(
        start_layouts,
        row_delta=1,
        col_delta=2,
        anchor_id=second["id"],
    )

    layouts = {block["id"]: block["layout"] for block in workspace["blocks"]}
    assert layouts[first["id"]]["row"] == 1
    assert layouts[first["id"]]["col"] == 2
    assert layouts[second["id"]]["row"] == 3
    assert layouts[second["id"]]["col"] == 5
    assert layouts[third["id"]] == locked_start
    assert editor.interaction_hint.startswith("Move 2 blocks:")


def test_workspace_layout_editor_preview_keeps_active_tile_alive(qapp):
    _ = qapp
    workspace = new_workspace("Stable Preview")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)
    editor.set_selected_block(block["id"])

    tiles = editor.surface.findChildren(
        WorkspaceLayoutTile,
        options=Qt.FindDirectChildrenOnly,
    )
    active_tile = next(tile for tile in tiles if tile.block["id"] == block["id"])

    editor.preview_layout(block["id"], row=2, col=3, row_span=3, col_span=6)

    refreshed_tiles = editor.surface.findChildren(
        WorkspaceLayoutTile,
        options=Qt.FindDirectChildrenOnly,
    )
    expected_rect = editor.layout_to_rect(editor._block(block["id"])["layout"])
    assert active_tile in refreshed_tiles
    assert active_tile.geometry() == expected_rect


def test_workspace_layout_editor_cancel_rebounds_preview(qapp):
    _ = qapp
    workspace = new_workspace("Cancel Preview")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)
    original_layout = deepcopy(block["layout"])

    editor.begin_interaction()
    editor.preview_layout(block["id"], row=3, col=4)
    assert workspace["blocks"][0]["layout"]["row"] == 3
    assert workspace["blocks"][0]["layout"]["col"] == 4

    assert editor.cancel_interaction()
    assert workspace["blocks"][0]["layout"] == original_layout
    assert editor._interaction_snapshot is None


def test_workspace_layout_editor_group_preview_keeps_tiles_alive(qapp):
    _ = qapp
    workspace = new_workspace("Stable Group Preview")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=4)
    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)

    original_tiles = {
        tile.block["id"]: tile
        for tile in editor.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        )
    }
    start_layouts = {
        block["id"]: dict(block["layout"])
        for block in editor._selected_blocks()
    }

    editor.preview_selected_move(start_layouts, row_delta=1, col_delta=1, anchor_id=second["id"])

    refreshed_tiles = {
        tile.block["id"]: tile
        for tile in editor.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        )
    }
    assert refreshed_tiles[first["id"]] is original_tiles[first["id"]]
    assert refreshed_tiles[second["id"]] is original_tiles[second["id"]]


def test_workspace_layout_tile_mouse_drag_and_resize(qapp):
    workspace = new_workspace("Pointer Gestures")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.resize(1040, 720)
    editor.show()
    qapp.processEvents()
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)
    editor.set_selected_block(block["id"])
    qapp.processEvents()

    tile = next(
        child
        for child in editor.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        )
        if child.block["id"] == block["id"]
    )
    start = tile.rect().center()
    drag_delta = QPoint(int(editor.cell_width() * 2), editor.row_height)
    QTest.mousePress(tile, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(tile, start + drag_delta)
    QTest.mouseRelease(tile, Qt.LeftButton, Qt.NoModifier, start + drag_delta)

    moved_layout = editor._block(block["id"])["layout"]
    assert moved_layout["row"] >= 1
    assert moved_layout["col"] >= 2

    qapp.processEvents()
    tile = next(
        child
        for child in editor.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        )
        if child.block["id"] == block["id"]
    )
    start_size = dict(editor._block(block["id"])["layout"])
    resize_start = tile.rect().bottomRight() - QPoint(3, 3)
    resize_delta = QPoint(int(editor.cell_width()), editor.row_height)
    QTest.mousePress(tile, Qt.LeftButton, Qt.NoModifier, resize_start)
    QTest.mouseMove(tile, resize_start + resize_delta)
    QTest.mouseRelease(tile, Qt.LeftButton, Qt.NoModifier, resize_start + resize_delta)

    resized_layout = editor._block(block["id"])["layout"]
    assert resized_layout["col_span"] > start_size["col_span"]
    assert resized_layout["row_span"] > start_size["row_span"]


def test_workspace_layout_tile_first_click_drag_does_not_destroy_tile(qapp):
    workspace = new_workspace("First Click Drag")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.resize(1040, 720)
    editor.show()
    qapp.processEvents()
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)
    editor.select_block(None)
    qapp.processEvents()

    tile = next(
        child
        for child in editor.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        )
        if child.block["id"] == block["id"]
    )
    start = tile.rect().center()
    drag_delta = QPoint(int(editor.cell_width() * 2), editor.row_height)

    QTest.mousePress(tile, Qt.LeftButton, Qt.NoModifier, start)
    assert tile.parent() is editor.surface
    assert editor.selected_block_id == block["id"]

    QTest.mouseMove(tile, start + drag_delta)
    QTest.mouseRelease(tile, Qt.LeftButton, Qt.NoModifier, start + drag_delta)

    moved_layout = editor._block(block["id"])["layout"]
    assert moved_layout["row"] >= 1
    assert moved_layout["col"] >= 2


def test_workspace_layout_tile_text_area_is_draggable(qapp):
    workspace = new_workspace("Text Drag")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.resize(1040, 720)
    editor.show()
    qapp.processEvents()
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)
    editor.set_selected_block(block["id"])
    qapp.processEvents()

    tile = next(
        child
        for child in editor.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        )
        if child.block["id"] == block["id"]
    )
    preview_label = next(
        label
        for label in tile.findChildren(QLabel)
        if label.text()
    )
    title_global = preview_label.mapToGlobal(preview_label.rect().center())
    hit_widget = QApplication.widgetAt(title_global)

    assert hit_widget is tile

    start = tile.mapFromGlobal(title_global)
    drag_delta = QPoint(int(editor.cell_width() * 2), editor.row_height)
    QTest.mousePress(tile, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(tile, start + drag_delta)
    QTest.mouseRelease(tile, Qt.LeftButton, Qt.NoModifier, start + drag_delta)

    moved_layout = editor._block(block["id"])["layout"]
    assert moved_layout["row"] >= 1
    assert moved_layout["col"] >= 2


def test_workspace_layout_tile_has_no_inline_action_buttons(qapp):
    workspace = new_workspace("No Inline Buttons")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.resize(1040, 720)
    editor.show()
    qapp.processEvents()
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)

    for _ in range(3):
        editor.set_selected_block(block["id"])
        editor.render()
        qapp.processEvents()

    inline_buttons = [
        button
        for tile in editor.surface.findChildren(
            WorkspaceLayoutTile,
            options=Qt.FindDirectChildrenOnly,
        )
        for button in tile.findChildren(QPushButton)
        if button.objectName() == "WorkspaceTileEditButton"
    ]
    assert inline_buttons == []


def test_workspace_layout_tile_context_menu_has_requested_actions(qapp):
    _ = qapp
    workspace = new_workspace("Context Menu")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=0)
    tile = WorkspaceLayoutTile(first, "Documents", editor)

    menu = tile._build_context_menu()
    action_texts = [
        action.text()
        for action in menu.actions()
        if action.text()
    ]
    assert action_texts == [
        "Select",
        "Delete",
        "Edit Properties",
        "Swap",
    ]

    swap_menu = menu.actions()[-1].menu()
    swap_list = swap_menu.findChild(QListWidget, "WorkspaceSwapBlockList")
    assert swap_list is not None
    assert swap_list.height() <= 220
    assert swap_list.count() == 1
    assert swap_list.item(0).data(Qt.UserRole) == second["id"]


def test_workspace_layout_tile_renders_live_block_preview(qapp):
    _ = qapp
    workspace = new_workspace("Live Preview")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("personal_info", row=0, col=0)
    tile = WorkspaceLayoutTile(block, "Personal Information", editor)

    texts = _widget_texts(tile)

    assert "Sample Missionary" in texts
    assert "Full Name" in texts
    assert not any(
        row.objectName() in {
            "WorkspaceTilePreviewStrong",
            "WorkspaceTilePreviewLine",
        }
        for row in tile.findChildren(QLabel)
    )


def test_workspace_palette_label_area_is_draggable_target(qapp):
    button = WorkspacePaletteButton("documents", "Documents")
    button.resize(220, 64)
    button.show()
    qapp.processEvents()

    label = button.findChild(QLabel, "StrongText")
    hit_widget = QApplication.widgetAt(label.mapToGlobal(label.rect().center()))

    assert hit_widget is button


def test_workspace_layout_editor_render_keeps_marquee_rubber_band(qapp):
    workspace = new_workspace("Marquee Stable")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.resize(1040, 720)
    editor.show()
    qapp.processEvents()
    editor.set_workspace(workspace)
    editor.add_block_at("documents", row=0, col=0)
    rubber_band = editor.surface._rubber_band

    editor.render()
    qapp.processEvents()

    assert rubber_band.parent() is editor.surface
    assert rubber_band.isVisible() is False

    start = QPoint(12, 12)
    end = QPoint(96, 96)
    QTest.mousePress(editor.surface, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(editor.surface, end)
    QTest.mouseRelease(editor.surface, Qt.LeftButton, Qt.NoModifier, end)

    assert rubber_band.isVisible() is False


def test_workspace_layout_editor_group_and_ungroup(qapp):
    _ = qapp
    workspace = new_workspace("Grouping")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=3)
    third = editor.add_block_at("workflow", row=5, col=6)

    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)
    group_id = editor.group_selected()

    assert group_id
    assert editor._block(first["id"])["group_id"] == group_id
    assert editor._block(second["id"])["group_id"] == group_id
    assert not editor._block(third["id"]).get("group_id")

    editor.select_block(first["id"])
    assert editor.selected_block_ids == [first["id"], second["id"]]

    editor.ungroup_selected()
    assert not editor._block(first["id"]).get("group_id")
    assert not editor._block(second["id"]).get("group_id")


def test_workspace_layout_editor_group_copy_paste_remaps_group(qapp):
    _ = qapp
    workspace = new_workspace("Group Copy")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=4)
    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)
    original_group = editor.group_selected()

    assert editor.copy_selected()
    pasted = editor.paste_copied()
    assert pasted is not None

    pasted_blocks = [
        block
        for block in workspace["blocks"]
        if block["id"] in editor.selected_block_ids
    ]
    pasted_group_ids = {block.get("group_id") for block in pasted_blocks}

    assert len(pasted_blocks) == 2
    assert len(pasted_group_ids) == 1
    assert original_group not in pasted_group_ids
    assert editor._block(first["id"])["group_id"] == original_group
    assert editor._block(second["id"])["group_id"] == original_group


def test_workspace_layout_editor_group_duplicate_remaps_group(qapp):
    _ = qapp
    workspace = new_workspace("Group Duplicate")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=4)
    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)
    original_group = editor.group_selected()

    duplicate = editor.duplicate_block()
    assert duplicate is not None

    duplicated_blocks = [
        block
        for block in workspace["blocks"]
        if block["id"] in editor.selected_block_ids
    ]
    duplicated_group_ids = {block.get("group_id") for block in duplicated_blocks}

    assert len(duplicated_blocks) == 2
    assert len(duplicated_group_ids) == 1
    assert original_group not in duplicated_group_ids


def test_workspace_layout_editor_select_all_and_marquee(qapp):
    _ = qapp
    workspace = new_workspace("Marquee")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=5)
    third = editor.add_block_at("workflow", row=6, col=0)

    editor.select_all()
    assert editor.selected_block_ids == [first["id"], second["id"], third["id"]]
    assert editor.selected_block_id == third["id"]

    first_rect = editor.layout_to_rect(first["layout"]).adjusted(-2, -2, 2, 2)
    editor.select_blocks_in_rect(first_rect)
    assert editor.selected_block_ids == [first["id"]]

    second_rect = editor.layout_to_rect(second["layout"]).adjusted(-2, -2, 2, 2)
    editor.select_blocks_in_rect(second_rect, additive=True)
    assert editor.selected_block_ids == [first["id"], second["id"]]

    empty_rect = QRect(0, 0, 1, 1)
    editor.select_blocks_in_rect(empty_rect)
    assert editor.selected_block_ids == []


def test_workspace_layout_editor_keyboard_shortcuts(qapp):
    _ = qapp
    workspace = new_workspace("Keys")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)
    editor.set_selected_block(block["id"])

    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    assert workspace["blocks"][0]["layout"]["col"] == 1

    editor.keyPressEvent(
        QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier)
    )
    assert workspace["blocks"][0]["layout"]["col"] == 0

    editor.keyPressEvent(
        QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.ControlModifier)
    )
    assert workspace["blocks"][0]["layout"]["col"] == 1

    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert editor.selected_block_id is None


def test_workspace_layout_editor_layer_keyboard_shortcuts(qapp):
    _ = qapp
    workspace = new_workspace("Layer Keys")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=2, col=4)
    editor.set_selected_block(first["id"])
    editor.select_block(second["id"], additive=True)

    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.ControlModifier))
    assert editor._block(first["id"]).get("group_id")
    assert editor._block(first["id"]).get("group_id") == editor._block(second["id"]).get("group_id")

    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.ControlModifier | Qt.ShiftModifier))
    assert not editor._block(first["id"]).get("group_id")
    assert not editor._block(second["id"]).get("group_id")

    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_L, Qt.ControlModifier))
    assert editor._block(first["id"])["locked"] is True
    assert editor._block(second["id"])["locked"] is True

    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_H, Qt.ControlModifier))
    assert editor._block(first["id"])["visible"] is False
    assert editor._block(second["id"])["visible"] is False


def test_workspace_layout_editor_placement_guide(qapp):
    _ = qapp
    workspace = new_workspace("Guide")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)

    editor.preview_new_block("web_viewer", row=2, col=3)

    assert editor.placement_guide_layout["row"] == 2
    assert editor.placement_guide_layout["col"] == 0
    assert editor.placement_guide_layout["col_span"] == 12
    assert editor.placement_guide_layout["row_span"] == 3

    editor.set_placement_guide(
        {"row": 4, "col": 11, "row_span": 2, "col_span": 6}
    )
    assert editor.placement_guide_layout["col"] == 6

    editor.clear_placement_guide()
    assert editor.placement_guide_layout is None


def test_workspace_layout_editor_smart_placement_avoids_overlap(qapp):
    _ = qapp
    workspace = new_workspace("Smart Placement")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)

    editor.preview_new_block("notes", row=0, col=0)

    assert editor.placement_guide_status == "adjusted"
    assert editor.placement_guide_layout["row"] == 0
    assert editor.placement_guide_layout["col"] == 6

    second = editor.add_block_at("notes", row=0, col=0)
    assert second["layout"]["col"] == 6

    editor.set_selected_block(second["id"])
    editor.update_selected_layout(row=0, col=0)

    layouts = {block["id"]: block["layout"] for block in workspace["blocks"]}
    assert layouts[first["id"]]["col"] == 0
    assert layouts[second["id"]]["col"] == 6


def test_workspace_layout_editor_alignment_guides_and_hint(qapp):
    _ = qapp
    workspace = new_workspace("Guides")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)
    second = editor.add_block_at("notes", row=4, col=6)

    editor.set_placement_guide(
        {"row": 4, "col": 0, "row_span": 2, "col_span": 6},
        block_id=first["id"],
    )

    assert 4 in editor.alignment_guides["horizontal"]
    assert 6 in editor.alignment_guides["vertical"]
    assert editor.interaction_hint.startswith("Move block:")

    editor.clear_placement_guide()
    assert editor.alignment_guides == {"vertical": [], "horizontal": []}
    assert editor.interaction_hint == "Ready"
    assert second["id"] in [block["id"] for block in workspace["blocks"]]


def test_workspace_layout_editor_snaps_near_alignment(qapp):
    _ = qapp
    workspace = new_workspace("Snap")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    first = editor.add_block_at("documents", row=0, col=0)

    snapped, changed = editor.snap_layout_to_alignment(
        {"row": 5, "col": 5, "row_span": 2, "col_span": 6}
    )
    assert changed
    assert snapped["col"] == 6

    editor.set_placement_guide(
        {"row": 5, "col": 5, "row_span": 2, "col_span": 6}
    )
    assert editor.placement_guide_status == "snapped"
    assert editor.placement_guide_layout["col"] == 6
    assert editor.interaction_hint.startswith("Snapped:")

    second = editor.add_block_at("notes", row=5, col=5)
    assert second["layout"]["col"] == 6
    assert first["layout"]["col"] == 0


def test_workspace_layout_tile_resize_handles_and_resize_hint(qapp):
    _ = qapp
    workspace = new_workspace("Handles")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents")
    tile = WorkspaceLayoutTile(block, "Documents", editor)
    tile.resize(240, 160)

    assert tile.resize_handle(tile.rect().topLeft()) == "nw"
    assert tile.resize_handle(tile.rect().topRight()) == "ne"
    assert tile.resize_handle(tile.rect().bottomLeft()) == "sw"
    assert tile.resize_handle(tile.rect().bottomRight()) == "se"
    assert tile.resize_handle(tile.rect().center()) is None

    editor.set_placement_guide(
        {"row": 0, "col": 0, "row_span": 3, "col_span": 7},
        block_id=block["id"],
        verb="Resize block",
    )

    assert editor.interaction_hint.startswith("Resize block:")
    assert editor.placement_guide_layout["col_span"] == 7
    assert editor.placement_guide_layout["row_span"] == 3


def test_workspace_layout_editor_lock_and_visibility_controls(qapp):
    _ = qapp
    workspace = new_workspace("Locking")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("documents", row=0, col=0)
    editor.set_selected_block(block["id"])

    editor.toggle_selected_locked()
    assert workspace["blocks"][0]["locked"] is True

    editor.update_selected_layout(col=6, row=4)
    assert workspace["blocks"][0]["layout"]["col"] == 0
    assert workspace["blocks"][0]["layout"]["row"] == 0
    assert editor.interaction_hint == "Locked block"

    editor.delete_selected()
    assert len(workspace["blocks"]) == 1

    editor.toggle_selected_locked()
    assert workspace["blocks"][0]["locked"] is False

    editor.toggle_selected_visible()
    assert workspace["blocks"][0]["visible"] is False

    editor.toggle_selected_visible()
    assert workspace["blocks"][0]["visible"] is True


def test_workspaces_page_layer_lock_visibility_controls(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    block = page.workspace_layout_editor.add_block_at("documents")
    page.workspace_layout_editor.set_selected_block(block["id"])
    page._populate_block_options()

    page._toggle_selected_locked()
    assert page.lock_block_btn.text() == "Unlock"
    assert not page.remove_block_btn.isEnabled()
    assert any(
        "Locked" in page.layers_list.item(row).text()
        for row in range(page.layers_list.count())
    )

    page._toggle_selected_locked()
    page._toggle_selected_visible()
    assert page.visibility_block_btn.text() == "Show"
    assert any(
        "Hidden" in page.layers_list.item(row).text()
        for row in range(page.layers_list.count())
    )


def test_workspaces_page_chrome_uses_active_language(qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SimpleNamespace(),
        workspace_service=service,
    )

    try:
        i18n.set_language("es")
        page = WorkspacesPage(main_window)

        labels = {
            label.text()
            for label in page.findChildren(QLabel)
            if label.text()
        }
        buttons = {
            button.text()
            for button in page.findChildren(QPushButton)
            if button.text()
        }

        assert "Constructor de espacios" in labels
        assert "Bloques" in labels
        assert "Inspector" in labels
        assert "Capas" in labels
        assert "Deshacer" in buttons
        assert "Rehacer" in buttons
        assert "Copiar" in buttons
        assert "Limpiar" in buttons
        assert page.workspace_name_input.placeholderText() == "Nombre del espacio"
        assert page.palette_search.placeholderText() == "Buscar bloques"
    finally:
        i18n.set_language(original_language)
        if "page" in locals():
            page.close()


def test_workspaces_page_group_controls(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    first = page.workspace_layout_editor.add_block_at("documents")
    second = page.workspace_layout_editor.add_block_at("notes")
    page.workspace_layout_editor.set_selected_block(first["id"])
    page.workspace_layout_editor.select_block(second["id"], additive=True)
    page._populate_block_options()

    assert page.group_block_btn.isEnabled()
    assert not page.ungroup_block_btn.isEnabled()

    page._group_selected_blocks()
    assert page.ungroup_block_btn.isEnabled()
    assert any(
        "Grouped" in page.layers_list.item(row).text()
        for row in range(page.layers_list.count())
    )

    page._ungroup_selected_blocks()
    assert not any(
        "Grouped" in page.layers_list.item(row).text()
        for row in range(page.layers_list.count())
    )


def test_workspaces_page_selection_metrics_label(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    first = page.workspace_layout_editor.add_block_at("documents")
    second = page.workspace_layout_editor.add_block_at("notes", row=2, col=4)
    page.workspace_layout_editor.set_selected_block(first["id"])
    page.workspace_layout_editor.select_block(second["id"], additive=True)
    page._populate_block_options()

    assert "2 selected" in page.selection_metrics_label.text()
    assert page.selected_block_label.text() == "2 blocks selected"

    page.workspace_layout_editor.set_placement_guide(
        {"row": 6, "col": 0, "row_span": 2, "col_span": 6},
        block_id=first["id"],
    )
    assert page.shortcut_hint_label.text().startswith("Move block:")


def test_workspace_layout_editor_clear_and_deselect(qapp):
    _ = qapp
    workspace = new_workspace("Clear")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("notes")

    editor.select_block(None)
    assert editor.selected_block_id is None

    editor.set_selected_block(block["id"])
    editor.clear_blocks()
    assert workspace["blocks"] == []
    assert editor.selected_block_id is None


def test_workspaces_page_confirms_destructive_workspace_actions(monkeypatch, qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)
    prompts = []

    def fake_message(parent, title, content, **kwargs):
        prompts.append((title, content, kwargs))
        return 0

    monkeypatch.setattr(
        "ui.pages.workspaces_page.show_message",
        fake_message,
    )

    try:
        page._new_workspace()
        workspace_id = page._current_workspace()["id"]
        block = page.workspace_layout_editor.add_block_at("notes")
        page.workspace_layout_editor.set_selected_block(block["id"])

        page._remove_workspace_block()
        assert len(page._current_workspace()["blocks"]) == 1
        assert prompts[-1][0] == "Remove Block?"

        page._clear_canvas()
        assert len(page._current_workspace()["blocks"]) == 1
        assert prompts[-1][0] == "Clear Canvas?"

        page._delete_workspace()
        assert service.get_workspace(workspace_id) is not None
        assert prompts[-1][0] == "Delete Workspace?"
    finally:
        page.close()


def test_workspaces_page_confirmed_destructive_actions_apply(monkeypatch, qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    monkeypatch.setattr(
        "ui.pages.workspaces_page.show_message",
        lambda *args, **kwargs: 1,
    )

    try:
        page._new_workspace()
        workspace_id = page._current_workspace()["id"]
        first = page.workspace_layout_editor.add_block_at("notes")
        page.workspace_layout_editor.add_block_at("documents")
        page.workspace_layout_editor.set_selected_block(first["id"])

        page._remove_workspace_block()
        assert len(page._current_workspace()["blocks"]) == 1

        page._clear_canvas()
        assert page._current_workspace()["blocks"] == []

        page._delete_workspace()
        assert service.get_workspace(workspace_id) is None
    finally:
        page.close()


def test_workspace_layout_editor_zoom_controls(qapp):
    _ = qapp
    workspace = new_workspace("Zoom")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)

    editor.zoom_in()
    assert editor.zoom > 1
    assert editor.row_height > editor.base_row_height

    editor.reset_zoom()
    assert editor.zoom == 1.0


def test_workspaces_page_grid_controls_update_editor(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page.grid_toggle.setChecked(False)
    assert page.workspace_layout_editor.grid_visible is False

    page.grid_size_spin.setValue(128)
    assert page.workspace_layout_editor.base_row_height == 128

    page.canvas_scroll.resize(800, 600)
    page._zoom_fit()
    assert page.workspace_layout_editor.zoom != 1.0
    assert page.zoom_reset_btn.text().endswith("%")


def test_workspaces_page_uses_canvas_without_visible_inspector(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    splitters = page.findChildren(QSplitter)

    assert page.inspector_panel.isVisible() is False
    assert all(
        splitter.indexOf(page.inspector_panel) == -1
        for splitter in splitters
    )
    assert page.canvas_scroll is not None


def test_workspaces_page_renders_editor_and_preview(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    page._add_workspace_block()
    page.block_col_span_spin.setValue(12)

    assert page.workspace_layout_editor.workspace is not None
    assert page._current_block()["layout"]["col_span"] == 12
    assert page.workspace_preview_grid.count() > 0


def test_workspaces_page_configures_web_viewer_url(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    index = page.block_add_combo.findData("web_viewer")
    page.block_add_combo.setCurrentIndex(index)
    page._add_workspace_block()
    page.block_web_url_input.setText("https://example.org")

    block = page._current_block()
    assert block["type"] == "web_viewer"
    assert block["web_url"] == "https://example.org"
    assert page.workspace_preview_grid.count() > 0


def test_workspaces_page_toolbar_copy_paste_and_align(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    page._add_workspace_block()
    page._copy_selected_block()
    page._paste_block()
    page._align_selected("fit_width")

    workspace = page._current_workspace()
    assert len(workspace["blocks"]) == 2
    assert page._current_block()["layout"]["col_span"] == 12


def test_workspaces_page_keyboard_shortcuts(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    first = page.workspace_layout_editor.add_block_at("documents")
    second = page.workspace_layout_editor.add_block_at("notes")
    page.workspace_layout_editor.set_selected_block(first["id"])
    page.workspace_layout_editor.select_block(second["id"], additive=True)

    page.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.ControlModifier))
    assert page.workspace_layout_editor._block(first["id"]).get("group_id")

    page.keyPressEvent(
        QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.ControlModifier | Qt.ShiftModifier)
    )
    assert not page.workspace_layout_editor._block(first["id"]).get("group_id")

    page.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_L, Qt.ControlModifier))
    assert page.workspace_layout_editor._block(first["id"])["locked"] is True

    page.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier))
    assert not page.workspace_layout_editor._block(first["id"]).get("locked")

    page.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.ControlModifier))
    assert page.workspace_layout_editor._block(first["id"])["locked"] is True


def test_workspaces_page_layer_arrange_shortcuts(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    first = page.workspace_layout_editor.add_block_at("documents")
    second = page.workspace_layout_editor.add_block_at("notes")
    third = page.workspace_layout_editor.add_block_at("workflow")
    page.workspace_layout_editor.set_selected_block(first["id"])

    page.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_BracketRight, Qt.ControlModifier))
    assert [block["id"] for block in page._current_workspace()["blocks"]] == [
        second["id"],
        first["id"],
        third["id"],
    ]

    page.keyPressEvent(
        QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_BracketRight,
            Qt.ControlModifier | Qt.ShiftModifier,
        )
    )
    assert page._current_workspace()["blocks"][-1]["id"] == first["id"]


def test_workspaces_page_palette_click_adds_block(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    page._add_palette_block("notes")

    assert page._current_block()["type"] == "notes"
    assert len(page._current_workspace()["blocks"]) == 1


def test_workspaces_page_palette_search_filters_blocks(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    def current_palette_buttons():
        return [
            page.palette_body_layout.itemAt(row).widget()
            for row in range(page.palette_body_layout.count())
            if isinstance(page.palette_body_layout.itemAt(row).widget(), WorkspacePaletteButton)
        ]

    initial_count = current_palette_buttons()
    assert len(initial_count) > 3

    page.palette_search.setText("web")
    filtered = current_palette_buttons()

    assert filtered
    assert len(filtered) < len(initial_count)
    assert any(button.block_type == "web_viewer" for button in filtered)


def test_workspaces_page_layers_panel_selects_and_refreshes(qapp):
    _ = qapp
    service = MemoryWorkspaceService()
    main_window = SimpleNamespace(
        settings_service=SettingsService(),
        workspace_service=service,
    )
    page = WorkspacesPage(main_window)

    page._new_workspace()
    first = page.workspace_layout_editor.add_block_at("documents")
    second = page.workspace_layout_editor.add_block_at("notes")
    page._refresh_layers_list()

    assert page.layers_list.count() == 2

    for row in range(page.layers_list.count()):
        item = page.layers_list.item(row)
        if item.data(Qt.UserRole) == first["id"]:
            page.layers_list.setCurrentItem(item)
            break

    assert page.workspace_layout_editor.selected_block_id == first["id"]

    page.block_title_input.setText("Primary Documents")
    assert any(
        "Primary Documents" in page.layers_list.item(row).text()
        for row in range(page.layers_list.count())
    )


def test_workspace_layout_tile_preview_lines(qapp):
    _ = qapp
    workspace = new_workspace("Preview")
    editor = WorkspaceLayoutEditor(lambda block_type: block_type)
    editor.set_workspace(workspace)
    block = editor.add_block_at("web_viewer")
    block["web_url"] = "https://example.org"

    tile = WorkspaceLayoutTile(block, "Web Viewer", editor)
    lines = tile.preview_lines()

    assert ("https://example.org", "strong") in lines


def test_workspace_layout_editor_inner_chrome_uses_active_language(qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    try:
        i18n.set_language("es")
        palette = WorkspacePaletteButton("documents", "Documentos")
        palette_texts = _widget_texts(palette)
        assert "Haga clic para agregar o arrastre al lienzo" in palette_texts

        workspace = new_workspace("Lienzo")
        editor = WorkspaceLayoutEditor(lambda block_type: block_type)
        editor.set_workspace(workspace)
        block = editor.add_block_at("documents")
        editor.set_selected_block(block["id"])
        tile = WorkspaceLayoutTile(block, "Documentos", editor)
        menu = tile._build_context_menu()
        menu_texts = {
            action.text()
            for action in menu.actions()
            if action.text()
        }
        assert {
            "Seleccionar",
            "Eliminar",
            "Editar propiedades",
            "Intercambiar",
        }.issubset(menu_texts)

        hidden = dict(block)
        hidden["visible"] = False
        hidden_tile = WorkspaceLayoutTile(hidden, "Documentos", editor)
        assert (
            "Oculto en el espacio de trabajo",
            "strong",
        ) in hidden_tile.preview_lines()

        duplicate = editor.duplicate_block(block["id"])
        assert duplicate["title"].endswith(" copia")

        editor.selected_block_ids = []
        assert editor.selection_summary()["text"] == "Sin selección"

        editor.set_selected_block(block["id"])
        editor.toggle_selected_locked()
        editor.update_selected_layout(col=6)
        assert editor.interaction_hint == "Bloque bloqueado"
    finally:
        i18n.set_language(original_language)
        for widget_name in ("palette", "tile", "hidden_tile"):
            if widget_name in locals():
                locals()[widget_name].close()


def test_workspace_block_properties_dialog_updates_web_url(qapp):
    _ = qapp
    block = new_block("web_viewer")
    dialog = WorkspaceBlockPropertiesDialog(block)

    dialog.title_input.setText("Portal")
    dialog.web_url_input.setText("https://example.org")
    dialog.row_spin.setValue(2)
    updated = dialog.updated_block()

    assert updated["title"] == "Portal"
    assert updated["web_url"] == "https://example.org"
    assert updated["layout"]["row"] == 2


def test_workspace_block_properties_dialog_uses_active_language(qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    try:
        i18n.set_language("es")
        dialog = WorkspaceBlockPropertiesDialog(new_block("web_viewer"))

        labels = {
            label.text()
            for label in dialog.findChildren(QLabel)
            if label.text()
        }
        buttons = {
            button.text()
            for button in dialog.findChildren(QPushButton)
            if button.text()
        }

        assert dialog.windowTitle() == "Editar propiedades"
        assert "Editar propiedades" in labels
        assert "Sitio web" in labels
        assert "Aplicar" in buttons
        assert "Cancelar" in buttons
        assert dialog.title_input.placeholderText() == "Titulo del bloque"
        assert dialog.web_url_input.placeholderText() == "URL del sitio web"
    finally:
        i18n.set_language(original_language)
        if "dialog" in locals():
            dialog.close()


def test_runtime_status_summary_block_renders_metrics(qapp):
    _ = qapp
    factory = WorkspaceBlockFactory(FakeWorkspaceDialog())

    widget = factory.build({"type": "status_summary", "title": "Snapshot"})
    texts = _widget_texts(widget)

    assert "Stage" in texts
    assert "Documents" in texts
    assert "Missing groups" in texts
    assert "Open tasks" in texts
    assert "Workflow status" in texts


def test_runtime_quick_actions_are_wired(qapp):
    _ = qapp
    dialog = FakeWorkspaceDialog()
    factory = WorkspaceBlockFactory(dialog)

    widget = factory.build(
        {
            "type": "quick_actions",
            "settings": {"actions": ["add_task", "open_folder", "update_workflow"]},
        }
    )

    buttons = {
        button.text(): button
        for button in widget.findChildren(QPushButton)
    }
    buttons["Add Task"].click()
    buttons["Open Folder"].click()
    buttons["Update Workflow"].click()

    assert dialog.actions == ["add_task", "open_folder", "update_workflow"]


def test_runtime_link_list_opens_configured_url(qapp):
    _ = qapp
    dialog = FakeWorkspaceDialog()
    factory = WorkspaceBlockFactory(dialog)

    widget = factory.build(
        {
            "type": "link_list",
            "settings": {
                "links": [
                    {"label": "Migraciones", "url": "https://example.org"},
                ],
            },
        }
    )

    button = next(
        button
        for button in widget.findChildren(QPushButton)
        if button.text() == "Open"
    )
    button.click()

    assert "Migraciones" in _widget_texts(widget)
    assert dialog.opened_urls == ["https://example.org"]


def test_runtime_web_viewer_loads_after_layout_and_uses_full_screen_size(
    monkeypatch,
    qapp,
):
    monkeypatch.setattr(
        workspace_dialog_module,
        "QWebEngineView",
        FakeWebEngineView,
    )
    FakeWebEngineView.created = []

    dialog = FakeWorkspaceDialog()
    dialog.is_full_screen_workspace = True
    factory = WorkspaceBlockFactory(dialog)
    widget = factory.build(
        {
            "type": "web_viewer",
            "title": "Portal",
            "web_url": "https://example.org",
        }
    )

    qapp.processEvents()
    QTest.qWait(1)

    web_view = FakeWebEngineView.created[0]
    assert web_view.minimumHeight() == 520
    assert web_view.loaded_url.toString() == "https://example.org"
    assert "Portal" in _widget_texts(widget)


def test_missionary_detail_opens_workspace_as_full_screen_when_available():
    workspace = new_workspace("Portal View")
    service = MemoryWorkspaceService()
    service.save_workspace(workspace)
    missionary = SimpleNamespace(id=7, full_name="Test Missionary")
    opened = []

    page = MissionaryDetailPage.__new__(MissionaryDetailPage)
    page.current_missionary = missionary
    page.workspace_service = service
    page.main_window = SimpleNamespace(
        open_missionary_workspace=lambda selected, selected_workspace: opened.append(
            (selected, selected_workspace)
        )
        or True
    )

    MissionaryDetailPage._open_workspace(page, workspace["id"])

    assert opened == [(missionary, workspace)]


def test_missionary_workspace_page_renders_workspace_blocks(monkeypatch, qapp):
    _ = qapp
    workspace = new_workspace("Portal View")
    workspace["blocks"].append(
        {
            "id": "web",
            "type": "web_viewer",
            "title": "Portal",
            "web_url": "https://example.org",
            "layout": {"row": 0, "col": 0, "row_span": 2, "col_span": 12},
        }
    )
    missionary = SimpleNamespace(id=7, full_name="Test Missionary")
    context = SimpleNamespace(
        missionary=missionary,
        documents=[],
        workflows=[],
        tasks=[],
        residency_rows=[],
        missing_groups=[],
    )
    monkeypatch.setattr(
        "ui.pages.missionary_workspace_page.MissionaryWorkspaceContext.load",
        lambda selected: context,
    )
    monkeypatch.setattr(
        "ui.dialogs.missionary_workspace_dialog.QWebEngineView",
        None,
    )

    page = MissionaryWorkspacePage()
    page.load_workspace(missionary, workspace)

    assert page.title_label.text() == "Portal View"
    assert page.subtitle_label.text() == "Test Missionary"
    assert "Portal" in _widget_texts(page)


def test_missionary_workspace_page_retranslates_screen_actions(qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    page = MissionaryWorkspacePage()
    try:
        i18n.set_language("en")
        page.retranslate_ui()
        assert page.back_btn.text() == "Back"
        assert page.refresh_btn.text() == "Refresh"

        i18n.set_language("es")
        page.retranslate_ui()
        assert page.back_btn.text() == "Volver"
        assert page.refresh_btn.text() == "Actualizar"
    finally:
        i18n.set_language(original_language)


def test_missionary_workspace_dialog_uses_close_action(monkeypatch, qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    missionary = SimpleNamespace(id=7, full_name="Test Missionary")
    context = SimpleNamespace(
        missionary=missionary,
        documents=[],
        workflows=[],
        tasks=[],
        residency_rows=[],
        missing_groups=[],
    )
    monkeypatch.setattr(
        "ui.dialogs.missionary_workspace_dialog.MissionaryWorkspaceContext.load",
        lambda selected: context,
    )
    host = QWidget()
    host.resize(1000, 700)
    try:
        i18n.set_language("en")
        dialog = MissionaryWorkspaceDialog(
            missionary,
            {"name": "Portal View", "blocks": []},
            parent=host,
        )
        button_texts = {
            button.text()
            for button in dialog.findChildren(QPushButton)
        }
        assert "Close" in button_texts
        assert "Cancel" not in button_texts
    finally:
        i18n.set_language(original_language)
