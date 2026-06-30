import json
from pathlib import Path

from services.workspace_layout import normalize_workspace_layout
from services.missionary_detail_layout_service import MissionaryDetailLayoutService
from services.workspace_service import WorkspaceService, new_block, new_workspace


def test_missing_workspace_file_returns_empty_list(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")

    assert service.list_workspaces() == []


def test_workspace_save_load_round_trip(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")
    workspace = new_workspace("Interpol Prep")
    workspace["blocks"].append(new_block("personal_info"))

    saved = service.save_workspace(workspace)
    reloaded = WorkspaceService(tmp_path / "workspaces.json")

    assert reloaded.get_workspace(saved["id"])["name"] == "Interpol Prep"
    assert reloaded.list_workspaces()[0]["blocks"]
    assert reloaded.list_workspaces()[0]["blocks"][0]["layout"]


def test_new_workspace_starts_with_blank_canvas():
    workspace = new_workspace("Blank")

    assert workspace["blocks"] == []


def test_corrupt_workspace_json_returns_empty_list(tmp_path):
    path = tmp_path / "workspaces.json"
    path.write_text("{not json", encoding="utf-8")
    service = WorkspaceService(path)

    assert service.list_workspaces() == []


def test_duplicate_workspace_copies_blocks_with_new_ids(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")
    workspace = new_workspace("Review")
    workspace["blocks"].append(new_block("documents"))
    workspace = service.save_workspace(workspace)

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


def test_missionary_detail_layout_file_saves_ui_layout_without_database():
    test_dir = Path("test_upload_tmp") / "missionary_detail_layout_service"
    path = test_dir / "layout.json"
    temp_path = path.with_suffix(".tmp")
    try:
        service = MissionaryDetailLayoutService(path)
        layout = service.get_layout()
        layout["blocks"][0]["layout"] = {
            "row": 4,
            "col": 0,
            "row_span": 2,
            "col_span": 12,
        }

        saved = service.save_layout(layout)
        reloaded = MissionaryDetailLayoutService(path).get_layout()
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert payload["version"] == 1
        assert saved["blocks"][0]["layout"] == {
            "row": 4,
            "col": 0,
            "row_span": 2,
            "col_span": 12,
        }
        assert reloaded["blocks"][0]["layout"] == saved["blocks"][0]["layout"]
    finally:
        for target in (path, temp_path):
            try:
                target.unlink(missing_ok=True)
            except PermissionError:
                pass
        try:
            if test_dir.exists():
                test_dir.rmdir()
        except (OSError, PermissionError):
            pass


def test_missionary_detail_layout_restores_required_sections():
    layout = {
        "blocks": [
            {
                "id": "overview",
                "type": "overview",
                "layout": {
                    "row": 3,
                    "col": 0,
                    "row_span": 1,
                    "col_span": 12,
                },
            }
        ]
    }

    normalized = MissionaryDetailLayoutService._normalize_layout(layout)
    section_types = {block["type"] for block in normalized["blocks"]}

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


def test_workspace_layout_fields_survive_save_load_and_duplicate(tmp_path):
    service = WorkspaceService(tmp_path / "workspaces.json")
    workspace = new_workspace("Grid")
    workspace["blocks"].append(new_block("documents"))
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
    workspace["blocks"].append(new_block("documents"))
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


def test_missionary_detail_layout_normalizes_tabs_independently():
    normalized = MissionaryDetailLayoutService._normalize_layout(
        {
            "blocks": [
                {
                    "id": "overview",
                    "type": "overview",
                    "tab": "overview",
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
                        "row": 0,
                        "col": 0,
                        "row_span": 1,
                        "col_span": 12,
                    },
                },
            ]
        }
    )

    overview = next(
        block for block in normalized["blocks"] if block["type"] == "overview"
    )
    details = next(
        block
        for block in normalized["blocks"]
        if block["type"] == "details_summary"
    )

    assert overview["layout"]["row"] == 0
    assert details["layout"]["row"] == 0


def test_web_viewer_block_defaults_to_full_tall_layout():
    block = new_block("web_viewer")

    assert block["web_url"] == "https://"
    assert block["width"] == "full"
    assert block["height"] == "tall"
    assert block["layout"]["col_span"] == 12
    assert block["layout"]["row_span"] == 3
