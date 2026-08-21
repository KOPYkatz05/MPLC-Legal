"""Plain state objects for an upload session."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from utils.constants import DOCUMENTS


@dataclass
class UploadQueueItem:
    """One selected file and all state needed to retry it safely."""

    file_path: str
    document_type: str | None = None
    workflow_stage: str = "GENERAL"
    export_settings: dict = field(default_factory=dict)
    ocr_result: object = None
    confirmed_data: dict = field(default_factory=dict)
    ocr_reviewed: bool = False
    duplicate_action: str = "keep"
    status: str = "pending"
    error_text: str = ""
    notes: str = ""
    updated_fields: list = field(default_factory=list)
    saved_document_id: int | None = None
    prefilled_data: dict = field(default_factory=dict)
    upload_id: str = field(default_factory=lambda: str(uuid4()))
    warnings: list = field(default_factory=list)
    supersedes_document_id: int | None = None
    replacement_target_resolved: bool = False
    content_sha256: str | None = None
    file_size: int | None = None
    derived_from_upload_id: str | None = None
    derived_kind: str | None = None
    derived_photo_approved: bool = False

    @property
    def file_name(self):
        return Path(self.file_path).name

    @property
    def has_ocr_fields(self):
        return bool(
            DOCUMENTS.get(self.document_type, {}).get("ocr_fields", [])
        )

    @property
    def file_size_text(self):
        try:
            size = Path(self.file_path).stat().st_size
        except OSError:
            size = self.file_size
            if size is None:
                return "Unknown size"

        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"


@dataclass
class UploadSaveResult:
    """Outcome returned by one save or reconciliation attempt."""

    item: UploadQueueItem | None = None
    status: str = "failed"
    document: object = None
    error_text: str = ""
    warnings: list = field(default_factory=list)

    @property
    def succeeded(self):
        return self.status in {"saved", "skipped"}
