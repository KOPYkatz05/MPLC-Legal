"""Non-blocking UI coordination for reusable print jobs."""

from PySide6.QtCore import QObject

from services.printing_models import PrintStatus
from services.printing_service import PrintingService
from ui.foundation import show_message
from ui.foundation.background_loader import LatestRequestLoader
from utils.language_helper import ui_text as tr
from utils.logger import logger


class PrintJobController(QObject):
    def __init__(self, document_service, parent=None):
        super().__init__(parent)
        self.printing_service = PrintingService(document_service)
        self._loader = LatestRequestLoader(parent=self)
        self._pending = False

    @property
    def pending(self):
        return self._pending

    def print_packet(self, packet_key, missionary, *, parent=None):
        if self._pending:
            return False
        dialog_parent = parent or self.parent()
        self._pending = True
        self._loader.request(
            lambda: self.printing_service.prepare_packet(packet_key, missionary),
            on_success=lambda job: self._prepared(job, dialog_parent),
            on_error=lambda error: self._failed(error, dialog_parent),
        )
        return True

    def print_documents(
        self,
        documents,
        *,
        job_name="Documents",
        transforms=None,
        parent=None,
    ):
        """Print an arbitrary collection through the same shared pipeline."""
        if self._pending:
            return False
        dialog_parent = parent or self.parent()
        self._pending = True
        self._loader.request(
            lambda: self.printing_service.prepare_documents(
                documents,
                job_name=job_name,
                transforms=transforms,
            ),
            on_success=lambda job: self._prepared(job, dialog_parent),
            on_error=lambda error: self._failed(error, dialog_parent),
        )
        return True

    def _prepared(self, job, parent):
        if job.missing_documents or job.unavailable_documents:
            sections = []
            if job.missing_documents:
                sections.append(
                    tr(
                        "print_job_missing_documents",
                        documents="\n".join(
                            f"- {label}" for label in job.missing_documents
                        ),
                    )
                )
            if job.unavailable_documents:
                sections.append(
                    tr(
                        "print_job_unavailable_documents",
                        documents="\n".join(
                            f"- {label}" for label in job.unavailable_documents
                        ),
                    )
                )
            if not job.documents:
                self._pending = False
                show_message(
                    parent,
                    tr("missionary_detail_no_documents_to_print_title"),
                    "\n\n".join(sections),
                    kind="warning",
                )
                return
            response = show_message(
                parent,
                tr("missionary_detail_missing_packet_title"),
                "\n\n".join(sections)
                + "\n\n"
                + tr("print_job_continue_question"),
                kind="warning",
                buttons="yes_no",
            )
            if response not in {1, 16384}:
                self._pending = False
                return

        self._loader.request(
            lambda: self.printing_service.finish_job(job),
            on_success=lambda result: self._completed(result, parent),
            on_error=lambda error: self._failed(error, parent),
        )

    def _completed(self, result, parent):
        self._pending = False
        if result.status == PrintStatus.COMPLETED:
            return
        logger.error("Print job ended with status %s", result.status)
        show_message(
            parent,
            tr("missionary_detail_print_failed_title"),
            tr("missionary_detail_print_failed"),
            kind="critical",
        )

    def _failed(self, error, parent):
        self._pending = False
        logger.error(
            "Print job preparation failed: %s",
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
        validation_error = isinstance(error, ValueError)
        message = str(error).strip() or tr("missionary_detail_print_failed")
        show_message(
            parent,
            tr(
                "print_job_information_incomplete"
                if validation_error
                else "missionary_detail_print_failed_title"
            ),
            message,
            kind="warning" if validation_error else "critical",
        )
