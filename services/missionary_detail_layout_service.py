import json
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from services.workspace_layout import normalize_workspace_layout, validate_block_layout
from utils.logger import logger


DETAIL_LAYOUT_SCHEMA_VERSION = 1
DETAIL_LAYOUT_FILE_NAME = "missionary_detail_layout.json"

DEFAULT_DETAIL_LAYOUT = {
    "id": "missionary_detail_default",
    "name": "Missionary Detail",
    "blocks": [
        {
            "id": "overview",
            "tab": "overview",
            "type": "overview",
            "title": "Overview",
            "layout": {"row": 0, "col": 0, "row_span": 2, "col_span": 6},
        },
        {
            "id": "workflow",
            "tab": "overview",
            "type": "workflow",
            "title": "Workflow",
            "layout": {"row": 0, "col": 6, "row_span": 2, "col_span": 6},
        },
        {
            "id": "open_tasks",
            "tab": "overview",
            "type": "open_tasks",
            "title": "Open Tasks",
            "layout": {"row": 2, "col": 0, "row_span": 2, "col_span": 6},
        },
        {
            "id": "documents",
            "tab": "overview",
            "type": "documents",
            "title": "Documents",
            "layout": {"row": 2, "col": 6, "row_span": 3, "col_span": 6},
        },
        {
            "id": "missing_documents",
            "tab": "overview",
            "type": "missing_documents",
            "title": "Missing Documents",
            "layout": {"row": 5, "col": 0, "row_span": 2, "col_span": 12},
        },
        {
            "id": "details_summary",
            "tab": "details",
            "type": "details_summary",
            "title": "At a Glance",
            "layout": {"row": 0, "col": 0, "row_span": 1, "col_span": 12},
        },
        {
            "id": "details_identity",
            "tab": "details",
            "type": "details_identity",
            "title": "Identity",
            "layout": {"row": 1, "col": 0, "row_span": 2, "col_span": 6},
        },
        {
            "id": "details_legal_timeline",
            "tab": "details",
            "type": "details_legal_timeline",
            "title": "Legal Timeline",
            "layout": {"row": 1, "col": 6, "row_span": 2, "col_span": 6},
        },
        {
            "id": "details_credentials",
            "tab": "details",
            "type": "details_credentials",
            "title": "Credentials",
            "layout": {"row": 3, "col": 0, "row_span": 1, "col_span": 6},
        },
        {
            "id": "details_residency",
            "tab": "details",
            "type": "details_residency",
            "title": "Residency Timeline",
            "layout": {"row": 3, "col": 6, "row_span": 2, "col_span": 6},
        },
    ],
}


def _default_config_dir():
    path = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if path:
        return Path(path)
    return Path.home() / ".mission-legal-tracker"


class MissionaryDetailLayoutService:
    def __init__(self, file_path=None):
        self.file_path = Path(file_path) if file_path else (
            _default_config_dir() / DETAIL_LAYOUT_FILE_NAME
        )

    def get_layout(self):
        if not self.file_path.exists():
            return self.default_layout()
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read missionary detail layout JSON")
            return self.default_layout()
        if not isinstance(data, dict):
            return self.default_layout()
        return self._normalize_layout(data.get("layout", data))

    def save_layout(self, layout):
        saved = self._normalize_layout(layout)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": DETAIL_LAYOUT_SCHEMA_VERSION,
            "layout": saved,
        }
        self.file_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return saved

    @classmethod
    def default_layout(cls):
        return cls._normalize_layout(deepcopy(DEFAULT_DETAIL_LAYOUT))

    @staticmethod
    def _normalize_layout(layout):
        normalized = deepcopy(layout or DEFAULT_DETAIL_LAYOUT)
        normalized["id"] = "missionary_detail"
        normalized["name"] = "Missionary Detail"
        blocks = [
            MissionaryDetailLayoutService._normalize_block(block)
            for block in normalized.get("blocks", [])
            if isinstance(block, dict)
        ]
        if not blocks:
            blocks = deepcopy(DEFAULT_DETAIL_LAYOUT["blocks"])
        blocks = MissionaryDetailLayoutService._with_required_blocks(blocks)
        normalized["blocks"] = MissionaryDetailLayoutService._normalize_tabs(blocks)
        return normalized

    @staticmethod
    def _with_required_blocks(blocks):
        existing = {
            block.get("type") or block.get("id")
            for block in blocks
        }
        for default_block in DEFAULT_DETAIL_LAYOUT["blocks"]:
            section_key = default_block.get("type") or default_block.get("id")
            if section_key not in existing:
                blocks.append(deepcopy(default_block))
                existing.add(section_key)
        return blocks

    @staticmethod
    def _normalize_block(block):
        normalized = dict(block or {})
        normalized["id"] = str(normalized.get("id") or normalized.get("type") or "block")
        normalized["type"] = str(normalized.get("type") or normalized["id"])
        normalized["tab"] = MissionaryDetailLayoutService._section_tab(normalized)
        normalized["title"] = str(normalized.get("title") or normalized["type"].replace("_", " ").title())
        normalized["layout"] = validate_block_layout(normalized)
        return normalized

    @staticmethod
    def _section_tab(block):
        tab = str(block.get("tab") or "").strip()
        if tab in {"overview", "details"}:
            return tab
        section_type = block.get("type") or block.get("id")
        if str(section_type).startswith("details_"):
            return "details"
        return "overview"

    @staticmethod
    def _normalize_tabs(blocks):
        normalized_blocks = []
        for tab in ("overview", "details"):
            tab_blocks = [
                block
                for block in blocks
                if block.get("tab") == tab
            ]
            packed = normalize_workspace_layout({"blocks": tab_blocks}).get("blocks", [])
            for block in packed:
                block["tab"] = tab
            normalized_blocks.extend(packed)
        return normalized_blocks
