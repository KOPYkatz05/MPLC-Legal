import json

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
