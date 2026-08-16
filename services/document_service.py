import json
import hashlib
import os
import shutil
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pathlib import Path
from database.runtime import get_client_data_dir

from database.db import SessionLocal
from services.api_client import (
    ApiUnavailableError,
    ApiUploadConflictError,
    ApiUploadOutcomeUnknownError,
    MissionLegalApiClient,
)
from services.remote_service import RemoteServiceMixin
from services.document_storage_service import (
    AMBIGUOUS,
    CLOUD_UNAVAILABLE,
    MISSING,
    UNREADABLE,
    DocumentStorageError,
    portable_relative_path,
    resolve_missionary_write_folder,
    pin_onedrive_file,
    resolve_document_path,
    verify_readable,
)

from database.models.document import (
    Document,
)

from utils.constants import DOCUMENTS, WORKFLOW_STAGES
from utils.document_files import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    sha256_file,
    validate_document_file,
)
from utils.logger import logger

from services.workflow_validator import (
    WorkflowValidator,
)


class DocumentFileUnavailableError(FileNotFoundError):
    """The document record exists but its file is unavailable on the server."""

    def __init__(self, document_id, reason=MISSING):
        super().__init__(f"Document file {document_id} is unavailable on the server.")
        self.document_id = document_id
        self.reason = reason


class DocumentUploadConflictError(ValueError):
    """An upload ID was reused for a different document payload."""


class DocumentUploadOutcomeUnknownError(RuntimeError):
    """The upload may be committed, but its durable outcome is not confirmed."""

    def __init__(self, message, *, upload_id):
        super().__init__(message)
        self.upload_id = str(upload_id)


class DocumentReplacementError(ValueError):
    """An explicit replacement target is missing, stale, or ambiguous."""


def _fsync_file(path):
    """Push a staged document's bytes to stable local storage."""

    # Windows' CRT rejects fsync on a read-only descriptor (EBADF), even when
    # the underlying file is readable. The staged/destination copies are ours
    # and writable, so use rb+ solely to obtain a flushable handle.
    with Path(path).open("rb+") as handle:
        os.fsync(handle.fileno())


def _fsync_parent_directory(path):
    """Persist the installed filename where the platform supports it."""

    directory = Path(path).parent
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = None
    try:
        descriptor = os.open(str(directory), flags)
        os.fsync(descriptor)
    except OSError:
        if os.name != "nt":
            raise
        # Windows reliably flushes the file handle above, but Python does not
        # expose a portable directory handle. The rename remains atomic; this
        # is a best-effort metadata barrier on that platform.
        logger.debug(
            "Directory flush is unavailable for upload destination %s",
            directory,
            exc_info=True,
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)


POST_PROCESSING_NOT_REQUIRED = "NOT_REQUIRED"
POST_PROCESSING_PENDING = "PENDING"
POST_PROCESSING_PROCESSING = "PROCESSING"
POST_PROCESSING_COMPLETE = "COMPLETE"
POST_PROCESSING_RETRY_REQUIRED = "RETRY_REQUIRED"
POST_PROCESSING_CANCELLED = "CANCELLED"
_POST_PROCESSING_RETRY_STATES = frozenset({
    POST_PROCESSING_PENDING,
    POST_PROCESSING_RETRY_REQUIRED,
})


class DocumentService(RemoteServiceMixin):
    REMOTE_SERVICE = "documents"
    REMOTE_METHODS = frozenset({
        "document_type_exists",
        "get_active_document_by_type",
        "delete_document_by_type",
        "delete_document_by_id",
        "update_document_notes",
    })
    def __init__(self):
        self.api_client = MissionLegalApiClient.from_environment()
        if self.api_client is not None:
            self.onedrive_service = None
            return
        self.workflow_validator = (
            WorkflowValidator()
        )

    def upload_document(
        self,
        missionary,
        source_file,
        document_type,
        workflow_stage,
        ocr_raw_data=None,
        ocr_confirmed_data=None,
        notes=None,
        upload_id=None,
        content_sha256=None,
        file_size=None,
        supersedes_document_id=None,
    ):
        source_path = Path(source_file)
        document_type, workflow_stage = self._validate_upload_classification(
            document_type,
            workflow_stage,
        )
        upload_id = self._canonical_upload_id(upload_id or uuid4())
        actual_size, actual_sha256 = self._validate_upload_source(
            source_path,
            expected_size=file_size,
            expected_sha256=content_sha256,
        )
        supersedes_document_id = self._normalize_replacement_id(
            supersedes_document_id
        )
        raw_json = self._serialize_json_field(ocr_raw_data)
        confirmed_json = self._serialize_json_field(ocr_confirmed_data)
        normalized_notes = notes or None

        if self.api_client is not None:
            data = {
                "missionary_id": str(missionary.id),
                "document_type": document_type,
                "workflow_stage": workflow_stage,
                "ocr_raw_data": raw_json or "",
                "ocr_confirmed_data": confirmed_json or "",
                "notes": normalized_notes or "",
                "upload_id": upload_id,
                "content_sha256": actual_sha256,
                "file_size": str(actual_size),
            }
            if supersedes_document_id is not None:
                data["supersedes_document_id"] = str(supersedes_document_id)
            try:
                payload = self.api_client.upload(
                    "/v1/documents/upload",
                    file_path=source_path,
                    data=data,
                )
            except ApiUploadOutcomeUnknownError as error:
                raise DocumentUploadOutcomeUnknownError(
                    str(error),
                    upload_id=upload_id,
                ) from error
            from services.api_client import RemoteRecord

            return RemoteRecord(payload)

        session = SessionLocal()
        session.expire_on_commit = False
        temporary_path = None
        destination_path = None
        installed_by_this_attempt = False
        commit_started = False
        committed = False

        try:
            existing = self._get_document_by_upload_id_in_session(
                session,
                upload_id,
            )
            if existing is not None:
                self._assert_upload_matches(
                    existing,
                    missionary_id=missionary.id,
                    document_type=document_type,
                    workflow_stage=workflow_stage,
                    content_sha256=actual_sha256,
                    file_size=actual_size,
                    supersedes_document_id=supersedes_document_id,
                    ocr_raw_data=raw_json,
                    ocr_confirmed_data=confirmed_json,
                    notes=normalized_notes,
                )
                self._verify_committed_upload_file(existing)
                # Release the read transaction before the durable follow-up
                # uses its own transactions. A repeated upload ID is also the
                # recovery trigger for work left PENDING by a crash.
                session.close()
                return self._run_post_processing_best_effort(existing)

            destination_folder = (
                resolve_missionary_write_folder(missionary)
                / workflow_stage
            )

            destination_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination_path, new_file_name = (
                self._build_destination_path(
                    destination_folder,
                    document_type,
                    source_path.suffix.lower(),
                )
            )

            logger.info(
                f"Uploading document "
                f"{new_file_name} "
                f"for missionary "
                f"{missionary.full_name}"
            )

            temporary_path = destination_path.with_name(
                f".{destination_path.name}.{uuid4().hex}.uploading"
            )
            # The staged copy is app-owned. Do not inherit a read-only bit
            # from email, network, scanner, or removable-media sources because
            # the durability flush below needs a writable Windows handle.
            shutil.copyfile(source_path, temporary_path)
            if temporary_path.stat().st_size != actual_size:
                raise OSError("Uploaded document copy has an unexpected size")
            if sha256_file(temporary_path) != actual_sha256:
                raise OSError("Uploaded document copy failed checksum verification")
            if verify_readable(temporary_path):
                raise OSError("Uploaded document copy is unreadable")
            _fsync_file(temporary_path)
            os.replace(temporary_path, destination_path)
            installed_by_this_attempt = True
            _fsync_file(destination_path)
            _fsync_parent_directory(destination_path)
            pin_onedrive_file(destination_path)

            document = Document(
                missionary_id=missionary.id,
                document_type=document_type,
                workflow_stage=workflow_stage,
                status="ACTIVE",
                file_name=new_file_name,
                file_path=str(destination_path),
                storage_relative_path=(
                    str(relative_destination) if (
                        relative_destination := portable_relative_path(destination_path)
                    ) is not None else None
                ),
                notes=notes or None,
                ocr_raw_data=raw_json,
                ocr_confirmed_data=confirmed_json,
                upload_id=upload_id,
                content_sha256=actual_sha256,
                file_size=actual_size,
                supersedes_document_id=supersedes_document_id,
                post_processing_status=(
                    POST_PROCESSING_PENDING
                    if self._requires_post_processing(
                        document_type,
                        confirmed_json,
                    )
                    else POST_PROCESSING_NOT_REQUIRED
                ),
                post_processing_error=None,
                post_processing_updated_fields=None,
            )

            if supersedes_document_id is not None:
                # Win the race against stale post-processing before replacing
                # the row. If a retry currently owns SQLite's write lock this
                # waits for it to finish; otherwise the unfinished old upload
                # is cancelled before any later retry can claim it.
                (
                    session.query(Document)
                    .filter(
                        Document.id == supersedes_document_id,
                        Document.missionary_id == missionary.id,
                        Document.document_type == document_type,
                        Document.status == "ACTIVE",
                        Document.post_processing_status.in_({
                            POST_PROCESSING_PENDING,
                            POST_PROCESSING_PROCESSING,
                            POST_PROCESSING_RETRY_REQUIRED,
                        }),
                    )
                    .update(
                        {
                            Document.post_processing_status: (
                                POST_PROCESSING_CANCELLED
                            ),
                            Document.post_processing_error: (
                                "Superseded before post-processing completed."
                            ),
                            Document.post_processing_updated_fields: None,
                        },
                        synchronize_session=False,
                    )
                )
                replaced = (
                    session.query(Document)
                    .filter(
                        Document.id == supersedes_document_id,
                        Document.missionary_id == missionary.id,
                        Document.document_type == document_type,
                        Document.status == "ACTIVE",
                    )
                    .update(
                        {
                            Document.status: "SUPERSEDED",
                            Document.invalidated_at: datetime.now(timezone.utc),
                            Document.invalidated_reason: (
                                f"Replaced by upload {upload_id}"
                            ),
                        },
                        synchronize_session=False,
                    )
                )
                if replaced != 1:
                    raise DocumentReplacementError(
                        "The document selected for replacement is no longer "
                        "the active matching document. Refresh and choose again."
                    )

            session.add(document)
            session.flush()
            commit_started = True
            session.commit()
            committed = True

        except Exception as error:
            try:
                session.rollback()
            except Exception:
                logger.exception("Could not roll back failed upload %s", upload_id)

            reconciled = None
            reconciliation_conflict = None
            try:
                # Another request with the same upload ID may have committed
                # after this transaction's initial lookup. Reconcile every
                # failure before reporting it, including stale replacement
                # targets caused by two in-flight retries.
                reconciled = self.get_document_by_upload_id(upload_id)
                if reconciled is not None:
                    self._assert_upload_matches(
                        reconciled,
                        missionary_id=missionary.id,
                        document_type=document_type,
                        workflow_stage=workflow_stage,
                        content_sha256=actual_sha256,
                        file_size=actual_size,
                        supersedes_document_id=supersedes_document_id,
                        ocr_raw_data=raw_json,
                        ocr_confirmed_data=confirmed_json,
                        notes=normalized_notes,
                    )
            except DocumentUploadConflictError as conflict:
                reconciliation_conflict = conflict
            except Exception:
                logger.exception(
                    "Could not reconcile failed upload %s",
                    upload_id,
                )

            if reconciliation_conflict is not None:
                if installed_by_this_attempt and not commit_started:
                    self._remove_failed_upload_path(destination_path)
                raise reconciliation_conflict from error

            if reconciled is not None:
                self._verify_committed_upload_file(reconciled)
                if (
                    installed_by_this_attempt
                    and destination_path is not None
                    and Path(reconciled.file_path) != destination_path
                ):
                    self._remove_failed_upload_path(destination_path)
                return self._run_post_processing_best_effort(reconciled)

            if installed_by_this_attempt and not commit_started:
                self._remove_failed_upload_path(destination_path)

            if commit_started:
                raise DocumentUploadOutcomeUnknownError(
                    "The database did not confirm whether upload "
                    f"{upload_id} committed. Keep the same upload ID and "
                    "reconcile before retrying.",
                    upload_id=upload_id,
                ) from error

            logger.exception(
                f"Failed to upload "
                f"document for "
                f"{missionary.full_name}"
            )

            raise

        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning(
                        "Could not remove upload staging file %s",
                        temporary_path,
                    )
            try:
                session.close()
            except Exception:
                logger.warning(
                    "Could not close the upload database session for %s",
                    upload_id,
                    exc_info=True,
                )

        if not committed:
            raise DocumentUploadOutcomeUnknownError(
                "The upload did not reach a confirmed committed state.",
                upload_id=upload_id,
            )

        try:
            logger.info(
                "Successfully uploaded %s for missionary %s (upload_id=%s)",
                new_file_name,
                missionary.full_name,
                upload_id,
            )
            self.workflow_validator.validate_workflows(missionary.id)
        except Exception:
            logger.exception(
                "Document %s was committed, but workflow recalculation failed",
                document.id,
            )

        return self._run_post_processing_best_effort(document)

    def reconcile_upload(
        self,
        upload_id,
        *,
        missionary_id,
        document_type,
        workflow_stage,
        content_sha256,
        file_size,
        supersedes_document_id=None,
    ):
        """Return a matching committed upload without reading source bytes.

        ``None`` means an authoritative lookup confirmed absence. An
        unavailable lookup raises ``DocumentUploadOutcomeUnknownError`` so a
        caller cannot mistake a network/database failure for permission to
        create a second upload.
        """

        upload_id = self._canonical_upload_id(upload_id)
        document_type, workflow_stage = self._validate_upload_classification(
            document_type,
            workflow_stage,
        )
        try:
            missionary_id = int(missionary_id)
        except (TypeError, ValueError) as error:
            raise ValueError("missionary_id must be an integer") from error
        if missionary_id <= 0:
            raise ValueError("missionary_id must be positive")

        content_sha256 = str(content_sha256 or "").strip().lower()
        if len(content_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in content_sha256
        ):
            raise ValueError("content_sha256 must be a SHA-256 hex digest")
        try:
            file_size = int(file_size)
        except (TypeError, ValueError) as error:
            raise ValueError("file_size must be an integer") from error
        if file_size <= 0:
            raise ValueError("file_size must be positive")
        supersedes_document_id = self._normalize_replacement_id(
            supersedes_document_id
        )

        expected = {
            "upload_id": upload_id,
            "missionary_id": missionary_id,
            "document_type": document_type,
            "workflow_stage": workflow_stage,
            "content_sha256": content_sha256,
            "file_size": file_size,
            "supersedes_document_id": supersedes_document_id,
        }
        if self.api_client is not None:
            try:
                result = self.api_client.lookup_upload(
                    upload_id,
                    expected=expected,
                )
            except ApiUploadConflictError as error:
                raise DocumentUploadConflictError(str(error)) from error
            if result.committed:
                from services.api_client import RemoteRecord

                return RemoteRecord(result.payload)
            if result.not_found:
                return None
            raise DocumentUploadOutcomeUnknownError(
                f"Upload {upload_id} still cannot be verified: "
                f"{result.detail or 'the server is unavailable'}.",
                upload_id=upload_id,
            )

        session = SessionLocal()
        try:
            document = self._get_document_by_upload_id_in_session(
                session,
                upload_id,
            )
            if document is None:
                return None
            self._assert_upload_core_matches(document, **expected)
            self._verify_committed_upload_file(document)
        except DocumentUploadConflictError:
            raise
        except DocumentStorageError:
            raise
        except Exception as error:
            raise DocumentUploadOutcomeUnknownError(
                f"Upload {upload_id} still cannot be verified because the "
                "document database is unavailable.",
                upload_id=upload_id,
            ) from error
        finally:
            session.close()
        return self._run_post_processing_best_effort(document)

    @staticmethod
    def _requires_post_processing(document_type, confirmed_json):
        return bool(confirmed_json) or document_type in {
            "CARNE_DE_EXTRANJERIA",
            "APROBACION_DE_PRORROGA",
        }

    def _run_post_processing_best_effort(self, document):
        """Finish durable follow-up without making a saved file look failed.

        The document transaction stores PENDING before this runs. Any crash or
        failure therefore leaves an authoritative retry marker. Reposting the
        same upload ID reaches this method again without copying another file.
        """

        status = getattr(
            document,
            "post_processing_status",
            POST_PROCESSING_NOT_REQUIRED,
        )
        if status not in _POST_PROCESSING_RETRY_STATES:
            return document
        try:
            return self.retry_document_post_processing(document.id)
        except Exception:
            logger.exception(
                "Document %s was saved, but post-processing needs a retry",
                document.id,
            )
            try:
                refreshed = self.get_document_by_id(document.id)
            except Exception:
                logger.exception(
                    "Could not reload post-processing state for document %s",
                    document.id,
                )
                refreshed = None
            return refreshed or document

    def retry_document_post_processing(self, document_id):
        """Idempotently finish the follow-up work for one committed upload."""

        if self.api_client is not None:
            payload = self.api_client.post(
                f"/v1/documents/{int(document_id)}/retry-post-processing"
            )
            from services.api_client import RemoteRecord

            return RemoteRecord(payload)

        session = SessionLocal()
        session.expire_on_commit = False
        try:
            document = session.get(Document, int(document_id))
            if document is None:
                raise LookupError(f"Document {document_id} was not found.")
            if document.status != "ACTIVE":
                if document.post_processing_status in _POST_PROCESSING_RETRY_STATES:
                    session.close()
                    return self._cancel_inactive_post_processing(document_id)
                return document
            if document.post_processing_status not in _POST_PROCESSING_RETRY_STATES:
                return document
            # Never derive missionary or residency data from a missing,
            # unreadable, truncated, or checksum-mismatched committed file.
            self._verify_committed_upload_file(document)
            confirmed_data = self._deserialize_confirmed_data(
                document.ocr_confirmed_data
            )
            missionary_id = document.missionary_id
            document_type = document.document_type
            session.expunge(document)
        finally:
            session.close()

        try:
            from services.upload_pipeline import (
                PostProcessingClaimUnavailableError,
                apply_missionary_updates,
            )

            apply_missionary_updates(
                missionary_id,
                document_type,
                int(document_id),
                confirmed_data,
                session_factory=SessionLocal,
                track_post_processing=True,
            )
        except PostProcessingClaimUnavailableError:
            # A concurrent retry completed it, or a replacement cancelled it.
            # In both cases the newly loaded row is authoritative.
            return self.get_document_by_id(document_id)
        except Exception as error:
            try:
                return_value = self._record_post_processing_failure(
                    document_id,
                    self._post_processing_error_message(error),
                )
                # Keep the local object useful to callers even though the
                # original failure is re-raised for logging and warning paths.
                document.post_processing_status = (
                    return_value.post_processing_status
                )
                document.post_processing_error = (
                    return_value.post_processing_error
                )
                document.post_processing_updated_fields = (
                    return_value.post_processing_updated_fields
                )
            except Exception:
                # PENDING was committed with the document, so even a failure to
                # record the richer error remains safely retryable.
                logger.exception(
                    "Could not record failed post-processing for document %s",
                    document_id,
                )
            raise

        # The missionary changes and COMPLETE marker commit atomically in
        # apply_missionary_updates. Reload the durable outcome for the caller.
        return self.get_document_by_id(document_id)

    @staticmethod
    def _deserialize_confirmed_data(value):
        if not value:
            return {}
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError) as error:
            raise ValueError("Confirmed OCR data is not valid JSON.") from error
        if not isinstance(data, dict):
            raise ValueError("Confirmed OCR data must be a JSON object.")
        return data

    @staticmethod
    def _post_processing_error_message(error):
        message = str(error).strip() or "Post-processing failed."
        return f"{type(error).__name__}: {message}"[:1000]

    @staticmethod
    def _record_post_processing_failure(document_id, error):
        session = SessionLocal()
        session.expire_on_commit = False
        try:
            document_id = int(document_id)
            (
                session.query(Document)
                .filter(
                    Document.id == document_id,
                    Document.status == "ACTIVE",
                    Document.post_processing_status.in_(
                        _POST_PROCESSING_RETRY_STATES
                    ),
                )
                .update(
                    {
                        Document.post_processing_status: (
                            POST_PROCESSING_RETRY_REQUIRED
                        ),
                        Document.post_processing_error: error,
                        Document.post_processing_updated_fields: None,
                    },
                    synchronize_session=False,
                )
            )
            # A replacement may have committed immediately after the failed
            # transaction rolled back. Never turn its CANCELLED old row back
            # into a retryable update.
            (
                session.query(Document)
                .filter(
                    Document.id == document_id,
                    Document.status != "ACTIVE",
                    Document.post_processing_status.in_({
                        POST_PROCESSING_PENDING,
                        POST_PROCESSING_PROCESSING,
                        POST_PROCESSING_RETRY_REQUIRED,
                    }),
                )
                .update(
                    {
                        Document.post_processing_status: (
                            POST_PROCESSING_CANCELLED
                        ),
                        Document.post_processing_error: (
                            "Superseded before post-processing completed."
                        ),
                        Document.post_processing_updated_fields: None,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            document = session.get(Document, document_id)
            if document is None:
                raise LookupError(f"Document {document_id} was not found.")
            return document
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _cancel_inactive_post_processing(document_id):
        session = SessionLocal()
        session.expire_on_commit = False
        try:
            document_id = int(document_id)
            (
                session.query(Document)
                .filter(
                    Document.id == document_id,
                    Document.status != "ACTIVE",
                    Document.post_processing_status.in_(
                        _POST_PROCESSING_RETRY_STATES
                    ),
                )
                .update(
                    {
                        Document.post_processing_status: (
                            POST_PROCESSING_CANCELLED
                        ),
                        Document.post_processing_error: (
                            "Superseded before post-processing completed."
                        ),
                        Document.post_processing_updated_fields: None,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            document = session.get(Document, document_id)
            if document is None:
                raise LookupError(f"Document {document_id} was not found.")
            return document
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _canonical_upload_id(value):
        try:
            return str(UUID(str(value).strip()))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("upload_id must be a valid UUID") from error

    @staticmethod
    def _normalize_replacement_id(value):
        if value in (None, ""):
            return None
        try:
            value = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "supersedes_document_id must be a document ID"
            ) from error
        if value <= 0:
            raise ValueError("supersedes_document_id must be positive")
        return value

    @staticmethod
    def _validate_upload_classification(document_type, workflow_stage):
        document_type = str(document_type or "").strip()
        if document_type not in DOCUMENTS:
            raise ValueError("document_type is not an allowed document type")

        workflow_stage = str(workflow_stage or "GENERAL").strip().upper()
        allowed_stages = {"GENERAL", "DNI", *WORKFLOW_STAGES}
        if workflow_stage not in allowed_stages:
            raise ValueError("workflow_stage is not an allowed workflow stage")
        return document_type, workflow_stage

    @staticmethod
    def _validate_upload_source(
        source_path,
        *,
        expected_size=None,
        expected_sha256=None,
    ):
        source_path = Path(source_path)
        extension = source_path.suffix.lower()
        if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
            raise ValueError(
                f"Unsupported document file type: {extension or 'no extension'}"
            )
        validation_error = validate_document_file(source_path)
        if validation_error:
            raise ValueError(validation_error)

        actual_size = source_path.stat().st_size
        actual_sha256 = sha256_file(source_path)
        if expected_size not in (None, ""):
            try:
                expected_size = int(expected_size)
            except (TypeError, ValueError) as error:
                raise ValueError("file_size must be an integer") from error
            if expected_size != actual_size:
                raise DocumentUploadConflictError(
                    "file_size does not match the selected document"
                )
        if expected_sha256 not in (None, ""):
            expected_sha256 = str(expected_sha256).strip().lower()
            if expected_sha256 != actual_sha256:
                raise DocumentUploadConflictError(
                    "content_sha256 does not match the selected document"
                )
        return actual_size, actual_sha256

    @staticmethod
    def _get_document_by_upload_id_in_session(session, upload_id):
        return (
            session.query(Document)
            .filter(Document.upload_id == upload_id)
            .one_or_none()
        )

    @staticmethod
    def _assert_upload_matches(
        document,
        *,
        missionary_id,
        document_type,
        workflow_stage,
        content_sha256,
        file_size,
        supersedes_document_id,
        ocr_raw_data,
        ocr_confirmed_data,
        notes,
    ):
        comparisons = {
            "missionary": (int(document.missionary_id), int(missionary_id)),
            "document type": (str(document.document_type), str(document_type)),
            "workflow stage": (
                str(document.workflow_stage or "GENERAL"),
                str(workflow_stage or "GENERAL"),
            ),
            "checksum": (
                str(document.content_sha256 or "").lower(),
                str(content_sha256 or "").lower(),
            ),
            "file size": (int(document.file_size or 0), int(file_size or 0)),
            "replacement target": (
                document.supersedes_document_id,
                supersedes_document_id,
            ),
            "OCR source data": (document.ocr_raw_data or None, ocr_raw_data or None),
            "confirmed OCR data": (
                document.ocr_confirmed_data or None,
                ocr_confirmed_data or None,
            ),
            "notes": (document.notes or None, notes or None),
        }
        for label, (actual, expected) in comparisons.items():
            if actual != expected:
                raise DocumentUploadConflictError(
                    f"upload_id {document.upload_id} is already committed with "
                    f"a different {label}"
                )

    @staticmethod
    def _assert_upload_core_matches(
        document,
        *,
        upload_id,
        missionary_id,
        document_type,
        workflow_stage,
        content_sha256,
        file_size,
        supersedes_document_id,
    ):
        comparisons = {
            "upload ID": (str(document.upload_id), str(upload_id)),
            "missionary": (int(document.missionary_id), int(missionary_id)),
            "document type": (str(document.document_type), str(document_type)),
            "workflow stage": (
                str(document.workflow_stage or "GENERAL"),
                str(workflow_stage or "GENERAL"),
            ),
            "checksum": (
                str(document.content_sha256 or "").lower(),
                str(content_sha256 or "").lower(),
            ),
            "file size": (int(document.file_size or 0), int(file_size or 0)),
            "replacement target": (
                document.supersedes_document_id,
                supersedes_document_id,
            ),
        }
        for label, (actual, expected) in comparisons.items():
            if actual != expected:
                raise DocumentUploadConflictError(
                    f"upload_id {document.upload_id} is already committed with "
                    f"a different {label}"
                )

    @staticmethod
    def _remove_failed_upload_path(path):
        if path is None:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove failed document upload destination")

    @staticmethod
    def _verify_committed_upload_file(document):
        try:
            resolved_path = Path(getattr(document, "file_path", "") or "")
            if verify_readable(resolved_path):
                resolved_path = resolve_document_path(
                    document.id,
                    session_factory=SessionLocal,
                )
            actual_size = Path(resolved_path).stat().st_size
            expected_size = getattr(document, "file_size", None)
            if expected_size is not None and actual_size != int(expected_size):
                raise DocumentStorageError(UNREADABLE, document.id)
            expected_sha256 = getattr(document, "content_sha256", None)
            if (
                expected_sha256
                and sha256_file(resolved_path) != str(expected_sha256).lower()
            ):
                raise DocumentStorageError(UNREADABLE, document.id)
            document.file_path = str(resolved_path)
            return resolved_path
        except DocumentStorageError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise DocumentStorageError(UNREADABLE, document.id) from error

    @staticmethod
    def _serialize_json_field(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, default=str)

    @staticmethod
    def _build_destination_path(
        destination_folder,
        document_type,
        file_extension,
    ):
        destination_folder = Path(destination_folder)
        new_file_name = f"{document_type}_{uuid4().hex}{file_extension}"
        destination_path = destination_folder / new_file_name
        return destination_path, new_file_name

    def get_documents(self, missionary_id):
        if self.api_client is not None:
            started_at = time.monotonic()
            payload = self.api_client.get(
                "/v1/rpc/documents/get_documents",
                params={"missionary_id": missionary_id},
            )
            from services.api_client import RemoteRecord

            documents = [RemoteRecord(item) for item in payload["items"]]
            logger.info(
                "Loaded %s document metadata record(s) for missionary %s in %.2fs",
                len(documents),
                missionary_id,
                time.monotonic() - started_at,
            )
            return documents
        session = SessionLocal()

        try:
            logger.info(
                f"Loading documents "
                f"for missionary ID "
                f"{missionary_id}"
            )

            documents = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id
                )
                .all()
            )

            logger.info(
                f"Loaded "
                f"{len(documents)} "
                f"documents for missionary "
                f"ID {missionary_id}"
            )

            return documents

        except Exception:
            logger.exception(
                "Failed to load documents"
            )
            raise

        finally:
            session.close()

    def ensure_local_copy(self, document):
        """Download one remote document only when its local file is needed."""
        source_path = Path(getattr(document, "file_path", "") or "")
        if self.api_client is None:
            try:
                return resolve_document_path(document.id)
            except DocumentStorageError as error:
                raise DocumentFileUnavailableError(document.id, error.code) from error

        cache_root = get_client_data_dir() / "DocumentCache" / str(document.missionary_id)
        suffix = source_path.suffix or ".bin"
        destination = cache_root / f"{document.id}{suffix}"
        started_at = time.monotonic()
        try:
            self.api_client.download(
                f"/v1/documents/{document.id}/content",
                destination,
            )
        except ApiUnavailableError as error:
            reason = getattr(error, "code", None)
            if reason in {MISSING, CLOUD_UNAVAILABLE, UNREADABLE, AMBIGUOUS}:
                raise DocumentFileUnavailableError(document.id, reason) from error
            if getattr(error, "status_code", None) == 404 or "404" in str(error):
                raise DocumentFileUnavailableError(document.id, MISSING) from error
            raise
        logger.info(
            "Downloaded document %s to client cache in %.2fs",
            document.id,
            time.monotonic() - started_at,
        )
        document.file_path = str(destination)
        return destination

    def ensure_local_thumbnail(self, document):
        """Download one lightweight thumbnail without downloading the document."""
        source_path = Path(getattr(document, "file_path", "") or "")
        version = f"{getattr(document, 'file_name', '')}|{getattr(document, 'uploaded_at', '')}"
        version_key = hashlib.sha256(version.encode("utf-8")).hexdigest()[:16]
        cache_root = get_client_data_dir() / "DocumentCache" / str(document.missionary_id) / "thumbnails"
        destination = cache_root / f"{document.id}-{version_key}.jpg"
        if self.api_client is None:
            raise DocumentFileUnavailableError(document.id)
        try:
            self.api_client.download(
                f"/v1/documents/{document.id}/thumbnail",
                destination,
            )
        except ApiUnavailableError as error:
            reason = getattr(error, "code", None)
            if reason in {MISSING, CLOUD_UNAVAILABLE, UNREADABLE, AMBIGUOUS}:
                raise DocumentFileUnavailableError(document.id, reason) from error
            if getattr(error, "status_code", None) == 404 or "404" in str(error):
                raise DocumentFileUnavailableError(document.id, MISSING) from error
            raise
        return destination

    def _materialize(self, document):
        """Compatibility wrapper for callers that still need an eager copy."""
        self.ensure_local_copy(document)
        return document

    def document_type_exists(
        self,
        missionary_id,
        document_type,
    ):
        session = SessionLocal()
        try:
            return (
                session.query(Document.id)
                .filter_by(
                    missionary_id=missionary_id,
                    document_type=document_type,
                    status="ACTIVE",
                )
                .first()
                is not None
            )
        except Exception:
            logger.exception("Failed to check document type")
            raise
        finally:
            session.close()

    def get_active_document_by_type(
        self,
        missionary_id,
        document_type,
    ):
        session = SessionLocal()

        try:
            matches = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id,
                    document_type=document_type,
                    status="ACTIVE",
                )
                .order_by(Document.id.asc())
                .limit(2)
                .all()
            )

            if len(matches) > 1:
                raise DocumentReplacementError(
                    "More than one active document has this type; refresh and "
                    "choose the exact document instead of replacing by type."
                )
            return matches[0] if matches else None

        except Exception:
            logger.exception(
                "Failed to load active document by type"
            )
            raise

        finally:
            session.close()

    def delete_document_by_type(
        self,
        missionary_id,
        document_type,
    ):
        session = SessionLocal()

        try:
            matches = (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id,
                    document_type=document_type,
                    status="ACTIVE",
                )
                .order_by(Document.id.asc())
                .limit(2)
                .all()
            )

            if len(matches) > 1:
                raise DocumentReplacementError(
                    "More than one active document has this type; delete the "
                    "exact document by ID instead."
                )
            if not matches:
                return False

            self._delete_document_record(
                session,
                matches[0],
                log_label=(
                    f"{document_type} "
                    f"for missionary {missionary_id}"
                ),
            )
            return True

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to delete document by type"
            )
            raise

        finally:
            session.close()

    def delete_document_by_id(self, document_id):
        session = SessionLocal()

        try:
            existing = (
                session.query(Document)
                .filter_by(id=document_id)
                .first()
            )

            if not existing:
                return False

            self._delete_document_record(
                session,
                existing,
                log_label=(
                    f"document ID {document_id}"
                ),
            )

            return True

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to delete document by ID"
            )

            return False

        finally:
            session.close()

    def update_document_notes(
        self,
        document_id,
        notes,
    ):
        session = SessionLocal()

        try:
            doc = (
                session.query(Document)
                .filter_by(id=document_id)
                .first()
            )

            if not doc:
                return

            doc.notes = notes

            session.commit()

            logger.info(
                f"Updated notes for document "
                f"{document_id}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to update document notes"
            )

        finally:
            session.close()

    def get_document_by_id(
        self,
        document_id,
    ):
        if self.api_client is not None:
            payload = self.api_client.get(f"/v1/documents/{document_id}")
            from services.api_client import RemoteRecord

            return RemoteRecord(payload)
        session = SessionLocal()

        try:
            return (
                session.query(Document)
                .filter_by(id=document_id)
                .first()
            )

        except Exception:
            logger.exception("Failed to load document %s", document_id)
            raise

        finally:
            session.close()

    def get_document_by_upload_id(self, upload_id):
        """Authoritatively return a committed upload, or ``None`` when absent.

        Unlike broad document-list helpers, database failures are deliberately
        propagated so a caller never mistakes an unavailable database for a
        safe-to-retry missing upload.
        """

        upload_id = self._canonical_upload_id(upload_id)
        if self.api_client is not None:
            payload = self.api_client.get(
                f"/v1/document-uploads/{upload_id}"
            )
            from services.api_client import RemoteRecord

            return RemoteRecord(payload)

        session = SessionLocal()
        try:
            return self._get_document_by_upload_id_in_session(
                session,
                upload_id,
            )
        finally:
            session.close()

    def _delete_document_record(
        self,
        session,
        document,
        log_label,
    ):
        missionary_id = document.missionary_id
        document_id = document.id
        old_path = Path(document.file_path)

        try:
            from database.models.residency_event import ResidencyEvent

            (
                session.query(ResidencyEvent)
                .filter_by(document_id=document_id)
                .update({"document_id": None})
            )
        except Exception:
            logger.warning(
                "Could not clear residency event document references "
                f"for document ID {document_id}"
            )

        session.delete(document)
        session.commit()

        try:
            old_path.unlink(missing_ok=True)
        except Exception:
            logger.warning(
                "Deleted the document record but could not remove file %s",
                old_path,
            )

        try:
            logger.info(
                f"Deleted {log_label}"
            )
            self.workflow_validator.validate_workflows(
                missionary_id
            )
        except Exception:
            logger.warning(
                "Deleted document, but workflow "
                "recalculation failed"
            )
