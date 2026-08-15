"""Backward-compatible imports for the canonical document viewer module."""

from ui.dialogs.document_viewer_dialog import (
    PREVIEW_MAX_SCALE,
    PREVIEW_MIN_SCALE,
    DocumentPreviewGraphicsView,
    DocumentPreviewWidget,
    DocumentViewerDialog,
)

__all__ = [
    "PREVIEW_MAX_SCALE",
    "PREVIEW_MIN_SCALE",
    "DocumentPreviewGraphicsView",
    "DocumentPreviewWidget",
    "DocumentViewerDialog",
]
