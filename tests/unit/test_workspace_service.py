import json

from services.workspace_layout import normalize_workspace_layout
from services.workspace_service import WorkspaceService, new_workspace


def test_missing_workspace_file_returns_empty_list(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")

    assert service.list_workspaces() == []


def test_workspace_save_load_round_trip(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")
    workspace = new_workspace("Interpol Prep")

    saved = service.save_workspace(workspace)
    reloaded = WorkspaceService(tmp_path / "workspaces.json")

    assert reloaded.get_workspace(saved["id"])["name"] == "Interpol Prep"
    assert reloaded.list_workspaces()[0]["blocks"]
    assert reloaded.list_workspaces()[0]["blocks"][0]["layout"]


def test_corrupt_workspace_json_returns_empty_list(tmp_path):
    path = tmp_path / "workspaces.json"
    path.write_text("{not json", encoding="utf-8")
    service = WorkspaceService(path)

    assert service.list_workspaces() == []


def test_duplicate_workspace_copies_blocks_with_new_ids(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")
    workspace = service.save_workspace(new_workspace("Review"))

    duplicate = service.duplicate_workspace(workspace["id"])

    assert duplicate["id"] != workspace["id"]
    assert duplicate["name"] == "Review Copy"
    assert duplicate["blocks"][0]["id"] != workspace["blocks"][0]["id"]


def test_workspace_file_uses_versioned_payload(tmp_path):
    path = tmp_path / "workspaces.json"
    service = WorkspaceService(path)

    service.save_workspace(new_workspace("Review"))

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["workspaces"]) == 1


def test_workspace_layout_fields_survive_save_load_and_duplicate(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")
    workspace = new_workspace("Grid")
    workspace["blocks"][0]["layout"] = {
        "row": 3,
        "col": 4,
        "row_span": 2,
        "col_span": 5,
    }

    saved = service.save_workspace(workspace)
    reloaded = WorkspaceService(tmp_path / "workspaces.json").get_workspace(saved["id"])
    duplicate = service.duplicate_workspace(saved["id"])

    assert reloaded["blocks"][0]["layout"] == {
        "row": 3,
        "col": 4,
        "row_span": 2,
        "col_span": 5,
    }
    assert duplicate["blocks"][0]["layout"] == reloaded["blocks"][0]["layout"]


def test_invalid_workspace_layout_values_are_normalized(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")
    workspace = new_workspace("Invalid")
    workspace["blocks"][0]["layout"] = {
        "row": -5,
        "col": 50,
        "row_span": 99,
        "col_span": 99,
    }

    saved = service.save_workspace(workspace)
    layout = saved["blocks"][0]["layout"]

    assert layout == {
        "row": 0,
        "col": 0,
        "row_span": 8,
        "col_span": 12,
    }


def test_phase_one_blocks_are_auto_packed_without_overlap():
    workspace = {
        "id": "old",
        "name": "Old",
        "blocks": [
            {"id": "a", "type": "personal_info", "width": "half", "height": "normal"},
            {"id": "b", "type": "documents", "width": "half", "height": "normal"},
            {"id": "c", "type": "workflow", "width": "full", "height": "compact"},
        ],
    }

    normalized = normalize_workspace_layout(workspace)
    layouts = [block["layout"] for block in normalized["blocks"]]

    assert layouts[0] == {"row": 0, "col": 0, "row_span": 2, "col_span": 6}
    assert layouts[1] == {"row": 0, "col": 6, "row_span": 2, "col_span": 6}
    assert layouts[2] == {"row": 2, "col": 0, "row_span": 1, "col_span": 12}
