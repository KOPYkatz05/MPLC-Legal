"""Components used by the document upload session.

The public dialog remains available from ``ui.dialogs.upload_session_dialog``.
This package contains the smaller state, presentation, and orchestration units
used to assemble that compatibility facade.
"""

from .controller import UploadSessionController
from .models import UploadQueueItem, UploadSaveResult
from .orchestration import (
    UploadBatchCoordinator,
    UploadOcrWorkerCoordinator,
    UploadOperationState,
    UploadSaveWorkerCoordinator,
)
from .preview import UploadPreviewGraphicsView
from .progress import UploadSaveProgressDialog
from .workers import UploadOcrWarmupWorker, UploadOcrWorker, UploadSaveWorker

__all__ = [
    "UploadOcrWarmupWorker",
    "UploadOcrWorker",
    "UploadOcrWorkerCoordinator",
    "UploadBatchCoordinator",
    "UploadOperationState",
    "UploadSaveWorkerCoordinator",
    "UploadPreviewGraphicsView",
    "UploadSaveProgressDialog",
    "UploadQueueItem",
    "UploadSaveResult",
    "UploadSaveWorker",
    "UploadSessionController",
]
