---
name: OCR pipeline
description: How the full document upload + OCR + auto-update flow works
---

The upload pipeline in `ui/pages/missionary_detail_page.py` (`upload_document` method):

1. FileDialog → select file (PDF/image)
2. `UploadDocumentDialog` — pick document type (human label), stage auto-fills from `DOCUMENTS[type]["stage"]`
3. `DocumentEditorDialog` — view/crop/rotate; returns export_settings {page, rotation, crop_rect}
4. `_export_for_ocr()` — PDF uses `DocumentImageExportService.export_pdf_page`; images use PIL directly; writes to tempfile
5. `_run_ocr()` — `OCRService.extract_text()` → `DocumentParser.parse(text, document_type)`
6. `OCRReviewDialog` — generic, driven by `DOCUMENTS[type]["ocr_fields"]`; shown only if ocr_fields is non-empty
7. `DocumentService.upload_document()` — saves file to folder + DB
8. `_apply_auto_updates()` — writes confirmed OCR values to Missionary record via `MissionaryService.update_fields()`; date fields in DATE_AUTO_UPDATE_FIELDS are parsed from string

**Why OCR service is lazy-initialized:** PaddleOCR is slow to start; only loaded on first upload attempt.

**DocumentParser logic:**
- PASSPORT → PassportParser (MRZ regex)
- All others → `_extract_all_dates()` (regex for DD/MM/YYYY, DD de MES de YYYY, ISO) mapped to the correct ocr_field by position (first date, last date, etc.)
- CARNE_DE_EXTRANJERIA → also extracts carnet number via CE pattern regex
