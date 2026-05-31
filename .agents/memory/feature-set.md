---
name: Feature set
description: Major features built into the app and where they live
---

## Implemented Features

| Feature | Files | Notes |
|---|---|---|
| Batch Document Upload | `ui/dialogs/batch_upload_dialog.py` | Multi-file, type picker table, no OCR review in batch mode |
| Expiration Alerts | `services/alert_service.py`, `ui/dialogs/expiration_alert_dialog.py` | Shown on startup via QTimer in MainWindow; checks visa/residency/prórroga |
| Stage Transition Wizard | `ui/dialogs/stage_advance_dialog.py` | Checklist of required docs, marks current stage COMPLETED, sets next stage IN PROGRESS |
| Excel Export | `services/export_service.py` | openpyxl, styled headers, "Export to Excel" button on missionaries page |
| Missionary Notes | `database/models/missionary.py` (notes column) | Notes tab on detail page; saved via MissionaryService.update_fields |
| Document Notes | `database/models/document.py` (notes column) | Right-click document in list → "View / Edit Notes" → QDialog_Notes |
| Document Thumbnails | `services/thumbnail_service.py` | PIL + fitz; 60x75px; shown as QListWidget icons on detail page |
| Auto-Advance Banner | In `missionary_detail_page.py` | Green banner shows when all required docs for current stage are uploaded |
| Duplicate Detection | In `missionary_detail_page.py` `upload_document()` | Warning before replacing existing document of same type |

## Key Architecture Notes
- `AlertService.get_all_alerts(within_days=30)` returns overdue + expiring-soon combined
- `StageAdvanceDialog` queries DB directly and commits changes on accept
- `BatchUploadDialog` copies files to missionary folder without OCR; uses try/except per file
- **Missing Documents list only shows current stage** — stage-advance logic was incorrectly showing all 4 stages' missing docs at once. Now it only shows the stage the missionary is currently in (e.g., INTERPOL docs only, not PRORROGA/CANCELACION docs).
- `ThumbnailService.get_pixmap(file_path)` returns `QPixmap | None`; used in `load_documents()`
- `_document_data` list on `MissionaryDetailPage` caches doc dicts (id, label, file_path, notes) to avoid detached SQLAlchemy objects in context menus
- **StageHistory** model tracks every stage transition with `from_stage`, `to_stage`, and `created_at`. Shown on Timeline tab.
- **Missionary model** has `deleted_at` for soft delete, `passport_expiration` for alert tracking.
- **Sidebar pages** (by stack index): 0=Dashboard, 1=Missionaries, 2=Detail (not in sidebar), 3=Appointments, 4=Reports, 5=Trash.
- **DocumentViewerDialog** uses `fitz` (PyMuPDF) for PDF rendering and `QPixmap` for images; zoom in/out with buttons or +/- keys.
- **Multi-selection table** on Missionaries page allows Batch Actions (Advance Stage via `BatchStageAdvanceDialog`).
- **Nationality filter** dropdown auto-populates from loaded missionaries.
