import json
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QProgressDialog, QApplication
from PySide6.QtCore import Qt

from database.db import SessionLocal
from database.models.missionary import Missionary
from services.document_parser import DocumentParser
from services.document_image_export_service import DocumentImageExportService
from services.document_service import DocumentService
from services.image_processing_service import ImageProcessingService
from utils.constants import DOCUMENTS, MISSIONARY_DATE_FIELDS
from utils.logger import logger

_ocr_service = None
_ocr_init_failed = False


@dataclass
class UploadPipelineResult:
    parsed_data: dict = field(default_factory=dict)
    confirmed_data: dict = field(default_factory=dict)
    ocr_status: str = "skipped"
    ocr_image_path: Optional[Path] = None
    ocr_image_paths: list = field(default_factory=list)
    raw_text: Optional[str] = None
    raw_text_by_page: list = field(default_factory=list)
    document_type: Optional[str] = None
    ocr_fields: list = field(default_factory=list)
    export_settings: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    def to_audit_payload(self):
        return {
            "status": self.ocr_status,
            "document_type": self.document_type,
            "ocr_fields": self.ocr_fields,
            "parsed_data": self.parsed_data,
            "raw_text": self.raw_text,
            "raw_text_by_page": self.raw_text_by_page,
            "image_paths": [
                str(path) for path in self.ocr_image_paths
            ],
            "export_settings": self.export_settings,
            "errors": self.errors,
        }


@dataclass
class OcrSaveResult:
    document: object = None
    updated_fields: list = field(default_factory=list)
    missing_documents: list = field(default_factory=list)


DATE_AUTO_UPDATE_FIELDS = set(MISSIONARY_DATE_FIELDS)


def get_ocr_service(parent=None):
    global _ocr_service, _ocr_init_failed
    if _ocr_init_failed:
        return None
    if _ocr_service is None:
        try:
            from utils.i18n import tr
            msg = tr("ocr_initializing")
        except ImportError:
            msg = "Initializing OCR engine..."
        progress = None
        if parent is not None:
            progress = QProgressDialog(
                msg, None, 0, 0, parent
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.show()
            QApplication.processEvents()
        try:
            from services.ocr_service import OCRService
            _ocr_service = OCRService()
        except Exception:
            logger.exception("Failed to initialize OCR service")
            _ocr_init_failed = True
            _ocr_service = None
        finally:
            if progress:
                progress.close()
    return _ocr_service


def export_for_ocr(
    file_path,
    export_settings=None,
    image_export_service=None,
):
    paths = export_pages_for_ocr(
        file_path=file_path,
        export_settings=export_settings,
        image_export_service=image_export_service,
    )
    if paths:
        return paths[0]
    return None


def export_pages_for_ocr(
    file_path,
    export_settings=None,
    image_export_service=None,
):
    file_path = Path(file_path)
    export_settings = export_settings or {
        "page": 0,
        "rotation": 0,
        "crop_rect": None,
    }
    if image_export_service is None:
        image_export_service = DocumentImageExportService()

    suffix = file_path.suffix.lower()
    processor = ImageProcessingService()
    output_paths = []

    try:
        if suffix == ".pdf":
            for page_index in _get_page_indexes(
                file_path, export_settings
            ):
                tmp_path = _temporary_png_path()
                image_export_service.export_pdf_page(
                    pdf_path=file_path,
                    page_index=page_index,
                    rotation_angle=export_settings.get("rotation", 0),
                    crop_rect=export_settings.get("crop_rect"),
                    output_path=str(tmp_path),
                )
                processor.clean_image_for_ocr(tmp_path)
                output_paths.append(tmp_path)
        else:
            from PIL import Image

            tmp_path = _temporary_png_path()
            img = Image.open(str(file_path))
            rotation = export_settings.get("rotation", 0)
            if rotation:
                img = img.rotate(-rotation, expand=True)
            crop_rect = export_settings.get("crop_rect")
            if crop_rect:
                img = img.crop((
                    int(crop_rect.left()),
                    int(crop_rect.top()),
                    int(crop_rect.right()),
                    int(crop_rect.bottom()),
                ))
            img.save(str(tmp_path))
            processor.clean_image_for_ocr(tmp_path)
            output_paths.append(tmp_path)

        return output_paths
    except Exception:
        logger.exception("Failed to export document image for OCR")
        return []


def _temporary_png_path():
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    return tmp_path


def _get_page_indexes(file_path, export_settings):
    page = export_settings.get("page", 0)
    pages = export_settings.get("pages")

    if pages == "all" or page == "all":
        try:
            import fitz
            with fitz.open(str(file_path)) as document:
                return list(range(len(document)))
        except Exception:
            logger.exception("Failed to inspect PDF page count")
            return [0]

    if isinstance(pages, (list, tuple)):
        return [int(p) for p in pages]

    return [int(page or 0)]


def run_ocr_pipeline(
    image_path,
    document_type,
    parent=None,
    ocr_fields=None,
):
    image_paths = []
    if image_path:
        image_paths = [Path(image_path)]
    return run_ocr_on_images(
        image_paths=image_paths,
        document_type=document_type,
        parent=parent,
        ocr_fields=ocr_fields,
    )


def run_ocr_on_images(
    image_paths,
    document_type,
    parent=None,
    ocr_fields=None,
    export_settings=None,
):
    ocr_fields = ocr_fields or DOCUMENTS.get(
        document_type, {}
    ).get("ocr_fields", [])

    image_paths = [Path(path) for path in image_paths if path]

    if not ocr_fields or not image_paths:
        return UploadPipelineResult(
            ocr_status="skipped",
            document_type=document_type,
            ocr_fields=list(ocr_fields),
            export_settings=_serialize_export_settings(
                export_settings or {}
            ),
            ocr_image_path=image_paths[0] if image_paths else None,
            ocr_image_paths=image_paths,
        )

    result = UploadPipelineResult(
        document_type=document_type,
        ocr_fields=list(ocr_fields),
        export_settings=_serialize_export_settings(
            export_settings or {}
        ),
        ocr_image_path=image_paths[0],
        ocr_image_paths=image_paths,
    )

    ocr = get_ocr_service(parent)
    if ocr is None:
        result.ocr_status = "failed"
        return result

    try:
        from utils.i18n import tr
        msg = tr("ocr_running")
    except ImportError:
        msg = "Reading document text..."
    progress = None
    if parent is not None:
        progress = QProgressDialog(msg, None, 0, 0, parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

    try:
        page_texts = []
        for page_index, image in enumerate(image_paths):
            page_text = ocr.extract_text(str(image))
            page_texts.append({
                "page": page_index,
                "image_path": str(image),
                "text": page_text,
            })

        raw_text = "\n\n".join(
            item["text"] for item in page_texts if item["text"]
        )
        result.raw_text = raw_text
        result.raw_text_by_page = page_texts
        parser = DocumentParser()
        parsed = parser.parse(raw_text, document_type)
        result.parsed_data = _serialize_parsed(parsed)

        filled = sum(
            1 for f in ocr_fields
            if result.parsed_data.get(f)
        )
        if not raw_text.strip():
            result.ocr_status = "failed"
        elif filled == len(ocr_fields):
            result.ocr_status = "success"
        elif filled > 0:
            result.ocr_status = "partial"
        else:
            result.ocr_status = "failed"

        logger.info(
            f"OCR status={result.ocr_status} "
            f"fields={list(result.parsed_data.keys())}"
        )
    except Exception:
        logger.exception(f"OCR failed for {document_type}")
        result.ocr_status = "failed"
        result.errors.append("OCR failed. Check logs for details.")
    finally:
        if progress:
            progress.close()

    return result


def prepare_ocr_ingestion(
    source_file,
    document_type,
    export_settings=None,
    parent=None,
    ocr_fields=None,
    image_export_service=None,
):
    export_settings = export_settings or {
        "page": 0,
        "rotation": 0,
        "crop_rect": None,
    }
    ocr_fields = ocr_fields or DOCUMENTS.get(
        document_type, {}
    ).get("ocr_fields", [])

    if not ocr_fields:
        return UploadPipelineResult(
            ocr_status="skipped",
            document_type=document_type,
            ocr_fields=[],
            export_settings=_serialize_export_settings(
                export_settings
            ),
        )

    image_paths = export_pages_for_ocr(
        source_file,
        export_settings,
        image_export_service,
    )

    result = run_ocr_on_images(
        image_paths=image_paths,
        document_type=document_type,
        parent=parent,
        ocr_fields=ocr_fields,
        export_settings=export_settings,
    )

    if not image_paths and ocr_fields:
        result.ocr_status = "failed"
        result.errors.append("Could not prepare an OCR image.")

    return result


def finalize_ocr_ingestion(
    missionary,
    source_file,
    document_type,
    workflow_stage,
    pipeline_result=None,
    confirmed_data=None,
    document_service=None,
):
    confirmed_data = confirmed_data or {}
    pipeline_result = pipeline_result or UploadPipelineResult(
        document_type=document_type,
        ocr_fields=DOCUMENTS.get(document_type, {}).get(
            "ocr_fields", []
        ),
    )
    pipeline_result.confirmed_data = confirmed_data

    doc = save_document_with_ocr(
        missionary=missionary,
        source_file=source_file,
        document_type=document_type,
        workflow_stage=workflow_stage,
        ocr_raw_data=pipeline_result.to_audit_payload(),
        ocr_confirmed_data=confirmed_data or None,
        document_service=document_service,
    )

    updated_fields = []
    if confirmed_data and doc:
        updated_fields = apply_missionary_updates(
            missionary.id,
            document_type,
            doc.id,
            confirmed_data,
        )

    if doc:
        from services.workflow_validator import WorkflowValidator
        WorkflowValidator().validate_workflows(missionary.id)

    current_stage = _get_current_stage(
        missionary.id,
        getattr(missionary, "current_stage", workflow_stage),
    )

    return OcrSaveResult(
        document=doc,
        updated_fields=updated_fields,
        missing_documents=get_missing_for_missionary(
            missionary.id,
            current_stage,
        ),
    )


def _get_current_stage(missionary_id, fallback):
    session = SessionLocal()
    try:
        missionary = (
            session.query(Missionary)
            .filter_by(id=missionary_id)
            .first()
        )
        if missionary and missionary.current_stage:
            return missionary.current_stage
        return fallback
    except Exception:
        logger.exception("Failed to reload missionary stage")
        return fallback
    finally:
        session.close()


def _serialize_export_settings(export_settings):
    serialized = {}
    for key, value in export_settings.items():
        if hasattr(value, "left") and hasattr(value, "top"):
            serialized[key] = {
                "left": value.left(),
                "top": value.top(),
                "right": value.right(),
                "bottom": value.bottom(),
            }
        else:
            serialized[key] = value
    return serialized


def _serialize_parsed(parsed: dict) -> dict:
    out = {}
    for key, val in parsed.items():
        if isinstance(val, date):
            out[key] = val.isoformat()
        else:
            out[key] = val
    return out


def parse_date_value(value_str):
    if not value_str:
        return None
    if isinstance(value_str, date):
        return value_str
    value_str = str(value_str).strip()
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value_str, fmt).date()
        except ValueError:
            continue
    return None


def apply_missionary_updates(
    missionary_id,
    document_type,
    document_id,
    confirmed_data,
    auto_update_fields=None,
):
    auto_update_fields = auto_update_fields or DOCUMENTS.get(
        document_type, {}
    ).get("auto_updates", [])

    updates = {}
    doc_label = DOCUMENTS.get(document_type, {}).get(
        "label", document_type
    )

    for field in auto_update_fields:
        value = confirmed_data.get(field, "")
        if not value:
            continue
        if field in DATE_AUTO_UPDATE_FIELDS:
            parsed_date = parse_date_value(value)
            if parsed_date:
                updates[field] = parsed_date
        else:
            updates[field] = str(value).strip()

    if not updates:
        return []

    session = SessionLocal()
    try:
        missionary = (
            session.query(Missionary)
            .filter_by(id=missionary_id)
            .first()
        )
        if not missionary:
            return []

        sources = {}
        if missionary.field_sources:
            try:
                sources = json.loads(missionary.field_sources)
            except (json.JSONDecodeError, TypeError):
                sources = {}

        for field in updates:
            sources[field] = {
                "document_id": document_id,
                "document_type": document_type,
                "label": doc_label,
            }

        missionary.field_sources = json.dumps(sources)

        for field, value in updates.items():
            setattr(missionary, field, value)

        session.commit()
        logger.info(
            f"Auto-updated missionary {missionary_id}: "
            f"{list(updates.keys())}"
        )
        return list(updates.keys())
    except Exception:
        session.rollback()
        logger.exception("Failed to apply missionary updates")
        return []
    finally:
        session.close()


def save_document_with_ocr(
    missionary,
    source_file,
    document_type,
    workflow_stage,
    ocr_raw_data=None,
    ocr_confirmed_data=None,
    document_service=None,
):
    document_service = document_service or DocumentService()
    doc = document_service.upload_document(
        missionary=missionary,
        source_file=source_file,
        document_type=document_type,
        workflow_stage=workflow_stage,
        ocr_raw_data=ocr_raw_data,
        ocr_confirmed_data=ocr_confirmed_data,
    )
    return doc


def get_missing_for_missionary(missionary_id, current_stage):
    from services.workflow_validator import WorkflowValidator
    validator = WorkflowValidator()
    return validator.get_missing_documents(
        missionary_id, current_stage
    )
