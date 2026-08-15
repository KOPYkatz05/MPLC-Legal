"""Non-widget state and durable save rules for an upload session."""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from services.document_image_export_service import DocumentImageExportService
from services.document_service import (
    DocumentService,
    DocumentUploadOutcomeUnknownError,
)
from services.upload_pipeline import (
    UploadPipelineResult,
    finalize_ocr_ingestion,
    finalize_saved_ocr_follow_up,
    ocr_runtime_mode,
    prepare_ocr_ingestion,
)
from utils.constants import DOCUMENTS, requires_fbi_document
from utils.document_files import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    sha256_file,
    validate_document_file,
)
from utils.logger import logger

from .models import UploadQueueItem, UploadSaveResult


SUPPORTED_EXTENSIONS = SUPPORTED_DOCUMENT_EXTENSIONS


def _hook(name, fallback):
    """Honor temporary compatibility patches on the legacy facade."""

    facade = sys.modules.get("ui.dialogs.upload_session_dialog")
    return getattr(facade, name, fallback) if facade is not None else fallback


class _UploadIdentityDocumentService:
    def __init__(self, delegate, *, content_sha256, file_size):
        self._delegate = delegate
        self._content_sha256 = content_sha256
        self._file_size = file_size

    def upload_document(self, *args, **kwargs):
        kwargs.setdefault("content_sha256", self._content_sha256)
        kwargs.setdefault("file_size", self._file_size)
        return self._delegate.upload_document(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._delegate, name)


class UploadSessionController:
    def __init__(
        self,
        missionary,
        document_service=None,
        image_export_service=None,
    ):
        self.missionary = missionary
        self.document_service = document_service or DocumentService()
        self.image_export_service = (
            image_export_service or DocumentImageExportService()
        )
        self.items = []
        self.selected_index = -1
        self.saved_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.updated_fields = []

    def add_files(self, file_paths):
        added = []
        known = {str(Path(item.file_path)) for item in self.items}
        for file_path in file_paths:
            path = Path(file_path)
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            normalized = str(path)
            if normalized in known:
                continue
            item = UploadQueueItem(
                file_path=normalized,
                workflow_stage="GENERAL",
                export_settings=self.default_export_settings(path),
            )
            self.items.append(item)
            known.add(normalized)
            added.append(item)

        if self.selected_index < 0 and self.items:
            self.selected_index = 0

        if added:
            logger.info(
                "UPLOAD_FILES_ADDED count=%s files=%s total=%s",
                len(added),
                [item.file_name for item in added],
                len(self.items),
            )

        return added

    def add_rejected_files(self, rejected_paths):
        """Keep rejected selections visible so they cannot disappear silently."""

        added = []
        known = {str(Path(item.file_path)) for item in self.items}
        for file_path, reason in rejected_paths:
            normalized = str(Path(file_path))
            if normalized in known:
                continue
            item = UploadQueueItem(
                file_path=normalized,
                status="rejected",
                error_text=reason,
            )
            self.items.append(item)
            known.add(normalized)
            added.append(item)

        if self.selected_index < 0 and self.items:
            self.selected_index = 0
        if added:
            logger.warning(
                "UPLOAD_FILES_REJECTED count=%s files=%s",
                len(added),
                [
                    {"file": item.file_name, "reason": item.error_text}
                    for item in added
                ],
            )
        return added

    def remove_item(self, index):
        if index < 0 or index >= len(self.items):
            return
        del self.items[index]
        if not self.items:
            self.selected_index = -1
        elif self.selected_index >= len(self.items):
            self.selected_index = len(self.items) - 1

    def select(self, index):
        if 0 <= index < len(self.items):
            self.selected_index = index

    def selected_item(self):
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None

    def set_document_type(self, index, document_type):
        if index < 0 or index >= len(self.items):
            return
        if document_type == "FBI" and not requires_fbi_document(self.missionary):
            document_type = "OTHER"
        item = self.items[index]
        if document_type is None:
            normalized_type = None
        elif document_type in DOCUMENTS:
            normalized_type = document_type
        else:
            normalized_type = "OTHER"
        if normalized_type is None:
            workflow_stage = "GENERAL"
        else:
            workflow_stage = self.derive_stage(normalized_type)
        if item.document_type == normalized_type:
            return
        if document_type not in DOCUMENTS and document_type is not None:
            document_type = "OTHER"
        logger.info(
            "Queue item %s type change: %s -> %s",
            index,
            item.document_type,
            normalized_type,
        )
        item.document_type = normalized_type
        item.workflow_stage = workflow_stage
        item.ocr_result = None
        item.prefilled_data = self.missionary_defaults_for_document(
            normalized_type
        )
        item.confirmed_data = dict(item.prefilled_data)
        item.ocr_reviewed = False
        item.error_text = ""
        item.supersedes_document_id = None
        item.replacement_target_resolved = False
        if item.status not in {"saved", "skipped"}:
            item.status = "pending"
        logger.info(
            "UPLOAD_DOCUMENT_TYPE_SET index=%s file=%s type=%s stage=%s prefilled_fields=%s",
            index,
            item.file_name,
            item.document_type,
            item.workflow_stage,
            sorted(item.prefilled_data.keys()),
        )

    @staticmethod
    def derive_stage(document_type):
        return DOCUMENTS.get(document_type, {}).get("stage") or "GENERAL"

    @staticmethod
    def default_export_settings(path):
        if Path(path).suffix.lower() == ".pdf":
            return {
                "page": 0,
                "pages": "all",
            }
        return {
            "page": 0,
        }

    def has_duplicate(self, item):
        return self.document_service.document_type_exists(
            self.missionary.id,
            item.document_type,
        )

    def _recount_results(self):
        self.saved_count = sum(
            item.status == "saved" for item in self.items
        )
        self.failed_count = sum(
            item.status in {"failed", "unknown", "rejected"}
            for item in self.items
        )
        self.skipped_count = sum(
            item.status == "skipped" for item in self.items
        )

    def _resolve_replacement_document_id(self, item):
        if item.duplicate_action != "replace":
            item.supersedes_document_id = None
            item.replacement_target_resolved = False
            return None
        if item.replacement_target_resolved:
            return item.supersedes_document_id

        resolver = getattr(
            self.document_service,
            "get_active_document_by_type",
            None,
        )
        if not callable(resolver):
            raise RuntimeError(
                "This client cannot safely replace an existing document. "
                "Choose Keep both or update the client and server."
            )

        existing = resolver(self.missionary.id, item.document_type)
        if existing is None:
            item.supersedes_document_id = None
            item.replacement_target_resolved = True
            return None

        document_id = getattr(existing, "id", None)
        if document_id is None:
            raise RuntimeError(
                "The existing document could not be identified safely. "
                "Choose Keep both and try again."
            )
        item.supersedes_document_id = int(document_id)
        item.replacement_target_resolved = True
        return item.supersedes_document_id

    @staticmethod
    def _capture_content_identity(item):
        """Cache immutable bytes metadata before the first network attempt."""

        path = Path(item.file_path)
        actual_size = path.stat().st_size
        actual_sha256 = _hook("sha256_file", sha256_file)(path)
        if item.file_size is not None and int(item.file_size) != actual_size:
            raise ValueError(
                "The selected file changed after its first upload attempt. "
                "Remove it and add the intended scan again."
            )
        if (
            item.content_sha256 is not None
            and str(item.content_sha256).lower() != actual_sha256
        ):
            raise ValueError(
                "The selected file changed after its first upload attempt. "
                "Remove it and add the intended scan again."
            )
        item.file_size = actual_size
        item.content_sha256 = actual_sha256

    @staticmethod
    def _durable_follow_up_metadata(document):
        status = getattr(document, "post_processing_status", None)
        warnings = []
        updated_fields = []
        if status in {"PENDING", "PROCESSING", "RETRY_REQUIRED"}:
            warnings.append(
                "The document was saved, but its missionary updates still "
                "need to be retried. The saved file remains available."
            )
        elif status == "COMPLETE":
            encoded_fields = getattr(
                document,
                "post_processing_updated_fields",
                None,
            )
            try:
                decoded_fields = (
                    json.loads(encoded_fields)
                    if isinstance(encoded_fields, str)
                    else encoded_fields
                )
            except (TypeError, ValueError):
                decoded_fields = None
            if isinstance(decoded_fields, list):
                updated_fields = [str(field) for field in decoded_fields]
        return updated_fields, warnings

    def _record_saved_item(
        self,
        item,
        document,
        *,
        updated_fields=None,
        warnings=None,
    ):
        item.updated_fields = list(updated_fields or [])
        item.warnings = list(warnings or [])
        item.saved_document_id = getattr(document, "id", None)
        item.status = "saved"
        item.error_text = (
            "Saved with a follow-up warning: " + " ".join(item.warnings)
            if item.warnings
            else ""
        )
        self.updated_fields.extend(item.updated_fields)
        self._recount_results()
        logger.info(
            "Saved upload item missionary=%s file=%s type=%s stage=%s document_id=%s",
            self.missionary.id,
            item.file_name,
            item.document_type,
            item.workflow_stage,
            getattr(document, "id", None),
        )
        return UploadSaveResult(
            item=item,
            status="saved",
            document=document,
            warnings=list(item.warnings),
        )

    def missionary_defaults_for_document(self, document_type):
        defaults = {}
        for field in DOCUMENTS.get(
            document_type, {}
        ).get("ocr_fields", []):
            value = self._serialize_missionary_field(field)
            if not self._blank_confirmed_value(value):
                defaults[field] = value
        return defaults

    def _serialize_missionary_field(self, field):
        value = getattr(self.missionary, field, None)
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value).strip()

    @staticmethod
    def _blank_confirmed_value(value):
        if value is None:
            return True
        return str(value).strip() == ""

    def merge_ocr_data_into_confirmed(self, item):
        if item.ocr_result is None:
            return

        parsed_data = getattr(item.ocr_result, "parsed_data", None) or {}
        if not parsed_data:
            logger.info(
                "UPLOAD_OCR_MERGE_SKIPPED file=%s type=%s parsed_fields=[]",
                item.file_name,
                item.document_type,
            )
            return

        confirmed = dict(item.confirmed_data or {})
        filled_blank = []
        replaced_prefill = []
        preserved = []
        for field, value in parsed_data.items():
            confirmed_value = confirmed.get(field)
            if self._blank_confirmed_value(confirmed_value):
                confirmed[field] = value
                filled_blank.append(field)
            elif self._ocr_should_replace_prefill(
                item,
                field,
                confirmed_value,
            ):
                confirmed[field] = value
                replaced_prefill.append(field)
            else:
                preserved.append(field)
        item.confirmed_data = confirmed
        logger.info(
            "UPLOAD_OCR_MERGE_DONE file=%s type=%s parsed_fields=%s filled_blank=%s replaced_prefill=%s preserved=%s",
            item.file_name,
            item.document_type,
            sorted(parsed_data.keys()),
            sorted(filled_blank),
            sorted(replaced_prefill),
            sorted(preserved),
        )

    def _ocr_should_replace_prefill(self, item, field, confirmed_value):
        if item.document_type not in {
            "PASSPORT",
            "DNI",
            "CARNE_DE_EXTRANJERIA",
        }:
            return False

        prefilled_value = (item.prefilled_data or {}).get(field)
        if self._blank_confirmed_value(prefilled_value):
            return False

        return str(confirmed_value).strip() == str(prefilled_value).strip()

    @classmethod
    def _confirmed_updates_for_save(cls, item):
        """Exclude unchanged display prefills from authoritative updates."""

        updates = {}
        prefills = item.prefilled_data or {}
        for field, value in (item.confirmed_data or {}).items():
            if cls._blank_confirmed_value(value):
                continue
            prefilled_value = prefills.get(field)
            if (
                not cls._blank_confirmed_value(prefilled_value)
                and str(value).strip() == str(prefilled_value).strip()
            ):
                continue
            updates[field] = value
        return updates

    def run_ocr(self, item, parent=None):
        ocr_fields = DOCUMENTS.get(item.document_type, {}).get(
            "ocr_fields", []
        )
        logger.info(
            "UPLOAD_OCR_REQUEST file=%s type=%s fields=%s status=%s",
            item.file_name,
            item.document_type,
            list(ocr_fields),
            item.status,
        )
        logger.info(
            "UPLOAD_OCR_RUNTIME file=%s type=%s mode=%s",
            item.file_name,
            item.document_type,
            ocr_runtime_mode(),
        )
        if not ocr_fields:
            item.ocr_result = None
            item.confirmed_data = {}
            item.ocr_reviewed = False
            item.status = "pending"
            logger.info(
                "UPLOAD_OCR_SKIPPED_NO_FIELDS file=%s type=%s",
                item.file_name,
                item.document_type,
            )
            return None

        item.status = "ocr"
        item.error_text = ""
        logger.info(
            "UPLOAD_OCR_PIPELINE_BEGIN file=%s type=%s export_settings=%s",
            item.file_name,
            item.document_type,
            item.export_settings,
        )
        item.ocr_result = _hook("prepare_ocr_ingestion", prepare_ocr_ingestion)(
            source_file=item.file_path,
            document_type=item.document_type,
            export_settings=item.export_settings,
            parent=parent,
            ocr_fields=ocr_fields,
            image_export_service=self.image_export_service,
        )
        logger.info(
            "UPLOAD_OCR_PIPELINE_DONE file=%s type=%s ocr_status=%s errors=%s parsed_fields=%s images=%s",
            item.file_name,
            item.document_type,
            getattr(item.ocr_result, "ocr_status", None),
            getattr(item.ocr_result, "errors", None),
            sorted((getattr(item.ocr_result, "parsed_data", None) or {}).keys()),
            [str(path) for path in getattr(item.ocr_result, "ocr_image_paths", [])],
        )
        self.merge_ocr_data_into_confirmed(item)
        item.ocr_reviewed = False

        self._apply_post_ocr_state(item)
        logger.info(
            "UPLOAD_OCR_STATE_APPLIED file=%s type=%s status=%s error=%s",
            item.file_name,
            item.document_type,
            item.status,
            item.error_text,
        )
        return item.ocr_result

    def _apply_post_ocr_state(self, item):
        if item.ocr_result is None:
            item.status = "pending"
            return

        status = item.ocr_result.ocr_status
        if status == "success":
            item.status = "ready"
            item.error_text = ""
        elif status == "partial":
            item.status = "review"
            item.error_text = "OCR found some fields. Please review."
        elif status == "failed":
            item.status = "review"
            error_message = item.ocr_result.errors[:1]
            item.error_text = (
                error_message[0]
                if error_message
                else "OCR could not read this document."
            )
        else:
            item.status = "pending"
            item.error_text = ""

    def save_item(self, item, parent=None, run_ocr=False):
        try:
            was_unknown = item.status == "unknown"
            was_saved_warning = item.status == "saved" and bool(item.warnings)
            if item.duplicate_action == "skip":
                item.status = "skipped"
                item.error_text = ""
                logger.info(
                    "Skipping upload for missionary=%s file=%s type=%s",
                    self.missionary.id,
                    item.file_name,
                    item.document_type,
                )
                self._recount_results()
                return UploadSaveResult(item=item, status="skipped")

            document_type = item.document_type
            if document_type not in DOCUMENTS:
                raise ValueError("document_type is required")
            if document_type == "FBI" and not requires_fbi_document(self.missionary):
                raise ValueError(
                    "FBI documents are only available for USA or Canada missionaries"
                )

            workflow_stage = item.workflow_stage or self.derive_stage(
                document_type
            )
            if not workflow_stage:
                workflow_stage = "GENERAL"
            item.workflow_stage = workflow_stage

            if was_saved_warning:
                return self._retry_saved_item_follow_up(
                    item,
                    document_type=document_type,
                    workflow_stage=workflow_stage,
                )

            supersedes_document_id = self._resolve_replacement_document_id(
                item
            )

            if (
                was_unknown
                and item.content_sha256
                and item.file_size is not None
            ):
                reconciler = getattr(
                    self.document_service,
                    "reconcile_upload",
                    None,
                )
                if callable(reconciler):
                    document = reconciler(
                        item.upload_id,
                        missionary_id=self.missionary.id,
                        document_type=document_type,
                        workflow_stage=workflow_stage,
                        content_sha256=item.content_sha256,
                        file_size=item.file_size,
                        supersedes_document_id=supersedes_document_id,
                    )
                    if document is not None:
                        updated_fields, warnings = (
                            self._durable_follow_up_metadata(document)
                        )
                        return self._record_saved_item(
                            item,
                            document,
                            updated_fields=updated_fields,
                            warnings=warnings,
                        )

            validation_error = _hook("validate_document_file", validate_document_file)(item.file_path)
            if validation_error:
                raise ValueError(validation_error)
            self._capture_content_identity(item)

            logger.info(
                "Saving upload item missionary=%s file=%s type=%s stage=%s ocr=%s",
                self.missionary.id,
                item.file_name,
                document_type,
                workflow_stage,
                item.has_ocr_fields,
            )

            document = None
            if item.has_ocr_fields:
                if item.ocr_result is None:
                    ocr_fields = DOCUMENTS.get(
                        item.document_type, {}
                    ).get("ocr_fields", [])
                    item.ocr_result = UploadPipelineResult(
                        ocr_status="skipped",
                        document_type=item.document_type,
                        ocr_fields=list(ocr_fields),
                        export_settings=item.export_settings,
                    )
                confirmed_updates = self._confirmed_updates_for_save(item)
                save_result = _hook("finalize_ocr_ingestion", finalize_ocr_ingestion)(
                    missionary=self.missionary,
                    source_file=item.file_path,
                    document_type=document_type,
                    workflow_stage=workflow_stage,
                    pipeline_result=item.ocr_result,
                    confirmed_data=confirmed_updates,
                    notes=item.notes,
                    document_service=_UploadIdentityDocumentService(
                        self.document_service,
                        content_sha256=item.content_sha256,
                        file_size=item.file_size,
                    ),
                    upload_id=item.upload_id,
                    supersedes_document_id=supersedes_document_id,
                )
                item.updated_fields = list(
                    save_result.updated_fields or []
                )
                item.warnings = list(
                    getattr(save_result, "warnings", None) or []
                )
                document = save_result.document
            else:
                document = self.document_service.upload_document(
                    missionary=self.missionary,
                    source_file=item.file_path,
                    document_type=document_type,
                    workflow_stage=workflow_stage,
                    notes=item.notes,
                    upload_id=item.upload_id,
                    content_sha256=item.content_sha256,
                    file_size=item.file_size,
                    supersedes_document_id=supersedes_document_id,
                )
                item.updated_fields = []
                item.warnings = []

            return self._record_saved_item(
                item,
                document,
                updated_fields=item.updated_fields,
                warnings=item.warnings,
            )
        except DocumentUploadOutcomeUnknownError as exc:
            logger.exception("Upload session outcome is not yet confirmed")
            item.status = "unknown"
            item.error_text = (
                f"{exc} Retry this file to reconcile upload {item.upload_id}; "
                "the same upload will not be duplicated."
            )
            self._recount_results()
            return UploadSaveResult(
                item=item,
                status="unknown",
                error_text=item.error_text,
            )
        except Exception as exc:
            logger.exception("Upload session save failed")
            item.status = "failed"
            item.error_text = str(exc)
            self._recount_results()
            return UploadSaveResult(
                item=item,
                status="failed",
                error_text=str(exc),
            )

    def _retry_saved_item_follow_up(
        self,
        item,
        *,
        document_type,
        workflow_stage,
    ):
        """Retry ancillary work by document ID without reopening saved bytes."""

        document_id = item.saved_document_id
        retry = getattr(
            self.document_service,
            "retry_document_post_processing",
            None,
        )
        if document_id is None or not callable(retry):
            item.status = "saved"
            item.warnings = [
                "The document is saved, but this follow-up cannot be retried "
                "until the client and server are updated."
            ]
            item.error_text = "Saved with a follow-up warning: " + " ".join(
                item.warnings
            )
            self._recount_results()
            return UploadSaveResult(
                item=item,
                status="saved",
                warnings=list(item.warnings),
            )

        try:
            document = retry(document_id)
            result = _hook("finalize_saved_ocr_follow_up", finalize_saved_ocr_follow_up)(
                missionary=self.missionary,
                document=document,
                document_type=document_type,
                workflow_stage=workflow_stage,
                confirmed_data=item.confirmed_data,
            )
        except Exception:
            logger.exception(
                "Saved document %s follow-up retry could not be verified",
                document_id,
            )
            item.status = "saved"
            item.warnings = [
                "The document is saved, but its follow-up could not be "
                "verified. Check the server connection and retry."
            ]
            item.error_text = "Saved with a follow-up warning: " + " ".join(
                item.warnings
            )
            self._recount_results()
            return UploadSaveResult(
                item=item,
                status="saved",
                warnings=list(item.warnings),
            )

        return self._record_saved_item(
            item,
            document,
            updated_fields=result.updated_fields,
            warnings=result.warnings,
        )

    def has_saved_items(self):
        return any(
            item.status in {"saved", "unknown"}
            for item in self.items
        )

