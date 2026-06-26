import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QStandardPaths

from services.workspace_layout import (
    normalize_workspace_layout,
    validate_block_layout,
)
from utils.logger import logger


WORKSPACE_SCHEMA_VERSION = 1
WORKSPACES_FILE_NAME = "workspaces.json"

DEFAULT_BLOCKS = [
    {
        "id": "personal-info",
        "type": "personal_info",
        "title": "Personal Information",
        "width": "half",
        "height": "normal",
        "fields": [
            "full_name",
            "nationality",
            "passport_number",
            "carnet_number",
            "date_of_birth",
            "folder_path",
        ],
    },
    {
        "id": "documents",
        "type": "documents",
        "title": "Documents",
        "width": "half",
        "height": "normal",
    },
]


def _default_config_dir():
    path = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if path:
        return Path(path)
    return Path.home() / ".mission-legal-tracker"


def new_workspace(name="New Workspace"):
    return normalize_workspace_layout({
        "id": uuid4().hex,
        "name": name,
        "dialog_size": "large",
        "blocks": deepcopy(DEFAULT_BLOCKS),
    })


def new_block(block_type):
    labels = {
        "personal_info": "Personal Information",
        "documents": "Documents",
        "document_viewer": "Document Viewer",
        "web_viewer": "Web Viewer",
        "missing_documents": "Missing Documents",
        "workflow": "Workflow",
        "open_tasks": "Open Tasks",
        "notes": "Notes",
        "residency_timeline": "Residency Timeline",
    }
    block = {
        "id": uuid4().hex,
        "type": block_type,
        "title": labels.get(block_type, block_type),
        "width": "half",
        "height": "normal",
    }
    if block_type == "personal_info":
        block["fields"] = [
            "full_name",
            "nationality",
            "passport_number",
            "carnet_number",
        ]
    if block_type == "document_viewer":
        block["document_type"] = ""
        block["height"] = "tall"
        block["width"] = "full"
    if block_type == "web_viewer":
        block["web_url"] = "https://"
        block["height"] = "tall"
        block["width"] = "full"
    block["layout"] = validate_block_layout(block)
    return block


class WorkspaceService:
    def __init__(self, file_path=None):
        self.file_path = Path(file_path) if file_path else (
            _default_config_dir() / WORKSPACES_FILE_NAME
        )

    def list_workspaces(self):
        return list(self._read_payload().get("workspaces", []))

    def get_workspace(self, workspace_id):
        for workspace in self.list_workspaces():
            if workspace.get("id") == workspace_id:
                return workspace
        return None

    def save_workspace(self, workspace):
        payload = self._read_payload()
        workspaces = payload.setdefault("workspaces", [])
        saved = self._normalize_workspace(workspace)
        replaced = False
        for index, existing in enumerate(workspaces):
            if existing.get("id") == saved["id"]:
                workspaces[index] = saved
                replaced = True
                break
        if not replaced:
            workspaces.append(saved)
        self._write_payload(payload)
        return saved

    def delete_workspace(self, workspace_id):
        payload = self._read_payload()
        workspaces = payload.setdefault("workspaces", [])
        next_workspaces = [
            workspace
            for workspace in workspaces
            if workspace.get("id") != workspace_id
        ]
        deleted = len(next_workspaces) != len(workspaces)
        if deleted:
            payload["workspaces"] = next_workspaces
            self._write_payload(payload)
        return deleted

    def duplicate_workspace(self, workspace_id):
        workspace = self.get_workspace(workspace_id)
        if not workspace:
            return None
        duplicate = deepcopy(workspace)
        duplicate["id"] = uuid4().hex
        duplicate["name"] = f"{workspace.get('name', 'Workspace')} Copy"
        for block in duplicate.get("blocks", []):
            block["id"] = uuid4().hex
        return self.save_workspace(duplicate)

    def _read_payload(self):
        if not self.file_path.exists():
            return {"version": WORKSPACE_SCHEMA_VERSION, "workspaces": []}
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read workspaces JSON")
            return {"version": WORKSPACE_SCHEMA_VERSION, "workspaces": []}
        if not isinstance(data, dict):
            return {"version": WORKSPACE_SCHEMA_VERSION, "workspaces": []}
        workspaces = data.get("workspaces", [])
        if not isinstance(workspaces, list):
            workspaces = []
        return {
            "version": WORKSPACE_SCHEMA_VERSION,
            "workspaces": [
                self._normalize_workspace(workspace)
                for workspace in workspaces
                if isinstance(workspace, dict)
            ],
        }

    def _write_payload(self, payload):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": WORKSPACE_SCHEMA_VERSION,
            "workspaces": payload.get("workspaces", []),
        }
        temp_path = self.file_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temp_path, self.file_path)

    @staticmethod
    def _normalize_workspace(workspace):
        normalized = dict(workspace or {})
        normalized["id"] = str(normalized.get("id") or uuid4().hex)
        normalized["name"] = str(normalized.get("name") or "Workspace")
        normalized["dialog_size"] = (
            normalized.get("dialog_size")
            if normalized.get("dialog_size") in {"medium", "large", "wide"}
            else "large"
        )
        blocks = normalized.get("blocks", [])
        normalized["blocks"] = [
            WorkspaceService._normalize_block(block)
            for block in blocks
            if isinstance(block, dict)
        ]
        return normalize_workspace_layout(normalized)

    @staticmethod
    def _normalize_block(block):
        normalized = dict(block or {})
        normalized["id"] = str(normalized.get("id") or uuid4().hex)
        normalized["type"] = str(normalized.get("type") or "personal_info")
        normalized["title"] = str(
            normalized.get("title") or normalized["type"].replace("_", " ").title()
        )
        normalized["width"] = (
            normalized.get("width")
            if normalized.get("width") in {"full", "half"}
            else "half"
        )
        normalized["height"] = (
            normalized.get("height")
            if normalized.get("height") in {"compact", "normal", "tall"}
            else "normal"
        )
        normalized["layout"] = validate_block_layout(normalized)
        return normalized
