"""Qt workers used by the upload-session coordinator and compatibility dialog."""

from PySide6.QtCore import QObject, Signal

from services.upload_pipeline import get_ocr_service
from utils.logger import logger

from .models import UploadSaveResult


class UploadOcrWorker(QObject):
    finished = Signal(int, bool, str, object)

    def __init__(self, controller, index):
        super().__init__()
        self.controller = controller
        self.index = index

    def run(self):
        try:
            if self.index < 0 or self.index >= len(self.controller.items):
                raise IndexError("OCR item is no longer available.")
            item = self.controller.items[self.index]
            result = self.controller.run_ocr(item, parent=None)
            self.finished.emit(self.index, True, "", result)
        except Exception as exc:
            logger.exception("Async upload OCR failed")
            try:
                item = self.controller.items[self.index]
                item.status = "failed"
                item.error_text = str(exc)
            except Exception:
                pass
            self.finished.emit(self.index, False, str(exc), None)


class UploadOcrWarmupWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, service_factory=None):
        super().__init__()
        self._service_factory = service_factory or get_ocr_service

    def run(self):
        try:
            service = self._service_factory(parent=None)
            if service is None:
                self.finished.emit(False, "OCR service unavailable.")
                return
            self.finished.emit(True, "")
        except Exception as exc:
            logger.exception("Upload OCR warm-up failed")
            self.finished.emit(False, str(exc))


class UploadSaveWorker(QObject):
    finished = Signal(int, object)

    def __init__(self, controller, index):
        super().__init__()
        self.controller = controller
        self.index = index

    def run(self):
        try:
            if self.index < 0 or self.index >= len(self.controller.items):
                raise IndexError("Upload item is no longer available.")
            item = self.controller.items[self.index]
            result = self.controller.save_item(
                item,
                parent=None,
                run_ocr=False,
            )
        except Exception as exc:
            logger.exception("Background document save failed")
            item = (
                self.controller.items[self.index]
                if 0 <= self.index < len(self.controller.items)
                else None
            )
            if item is not None:
                item.status = "failed"
                item.error_text = str(exc)
            result = UploadSaveResult(
                item=item,
                status="failed",
                error_text=str(exc),
            )
        self.finished.emit(self.index, result)
