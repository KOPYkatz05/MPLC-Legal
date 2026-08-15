from services.document_service import (
    AMBIGUOUS,
    CLOUD_UNAVAILABLE,
    MISSING,
    UNREADABLE,
    DocumentFileUnavailableError,
)
from ui.foundation import show_message
from ui.foundation.background_loader import LatestRequestLoader
from utils.language_helper import ui_text as tr
from utils.logger import logger


class WorkspaceDocumentAccess:
    """Give workspace views the server-authoritative document-open behavior."""

    def _init_workspace_document_access(self):
        self._document_access_loaders = {}
        self._pending_document_access = set()

    def _ensure_workspace_document(self, document, on_ready):
        document_id = getattr(document, "id", None)
        if document_id is None or document_id in self._pending_document_access:
            return

        def complete(local_path):
            self._pending_document_access.discard(document_id)
            path_text = str(local_path)
            document.file_path = path_text
            try:
                on_ready(path_text)
            except Exception:
                logger.exception(
                    "Workspace document action failed for document %s",
                    document_id,
                )

        def failed(error):
            self._pending_document_access.discard(document_id)
            logger.error(
                "Workspace document %s could not be loaded: %s",
                document_id,
                error,
            )
            if isinstance(error, DocumentFileUnavailableError):
                message_key = {
                    MISSING: "missionary_detail_document_missing",
                    CLOUD_UNAVAILABLE: "missionary_detail_document_server_unavailable",
                    AMBIGUOUS: "missionary_detail_document_ambiguous",
                    UNREADABLE: "missionary_detail_document_unreadable",
                }.get(error.reason, "missionary_detail_document_download_failed")
            else:
                message_key = "missionary_detail_document_download_failed"
            show_message(
                self,
                tr("missionary_detail_file_not_found_title"),
                tr(message_key),
                kind="warning",
            )

        self._pending_document_access.add(document_id)
        loader = self._document_access_loaders.get(document_id)
        if loader is None:
            loader = LatestRequestLoader(parent=self)
            self._document_access_loaders[document_id] = loader
        loader.request(
            lambda: self.document_service.ensure_local_copy(document),
            on_success=complete,
            on_error=failed,
        )
