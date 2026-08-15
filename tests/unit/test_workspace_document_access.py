from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QWidget

from services.document_service import MISSING, DocumentFileUnavailableError
from ui.workspace_document_access import WorkspaceDocumentAccess
import ui.workspace_document_access as access_module


class ImmediateLoader:
    def __init__(self, parent=None):
        self.parent = parent

    def request(self, operation, *, on_success=None, on_error=None):
        try:
            result = operation()
        except Exception as error:
            on_error(error)
        else:
            on_success(result)


class AccessHost(WorkspaceDocumentAccess, QWidget):
    def __init__(self, document_service):
        super().__init__()
        self.document_service = document_service
        self._init_workspace_document_access()


def test_workspace_document_access_uses_service_result(monkeypatch, qapp):
    _ = qapp
    local_path = Path("C:/client-cache/17.pdf")
    document = SimpleNamespace(id=17, file_path="C:/server/original.pdf")
    service = SimpleNamespace(ensure_local_copy=lambda _document: local_path)
    opened = []
    monkeypatch.setattr(access_module, "LatestRequestLoader", ImmediateLoader)

    host = AccessHost(service)
    host._ensure_workspace_document(document, opened.append)

    assert opened == [str(local_path)]
    assert document.file_path == str(local_path)
    assert host._pending_document_access == set()


def test_workspace_document_access_reports_server_missing(monkeypatch, qapp):
    _ = qapp
    document = SimpleNamespace(id=23, file_path="C:/server/missing.pdf")

    def unavailable(_document):
        raise DocumentFileUnavailableError(document.id, MISSING)

    messages = []
    service = SimpleNamespace(ensure_local_copy=unavailable)
    monkeypatch.setattr(access_module, "LatestRequestLoader", ImmediateLoader)
    monkeypatch.setattr(
        access_module,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )

    host = AccessHost(service)
    host._ensure_workspace_document(document, lambda _path: None)

    assert len(messages) == 1
    assert messages[0][1]["kind"] == "warning"
    assert host._pending_document_access == set()
