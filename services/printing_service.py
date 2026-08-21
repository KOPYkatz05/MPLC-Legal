"""Reusable preparation and PDF assembly for all application print jobs."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import fitz

from services.document_service import DocumentFileUnavailableError, DocumentService
from services.print_packet_registry import get_packet_definition
from services.print_transforms import PRINT_TRANSFORMS, interpol_annotation_lines
from services.printing_models import (
    PreparedDocument,
    PreparedPrintJob,
    PrintOutputMode,
    PrintResult,
    PrintStatus,
)
from utils.constants import DOCUMENTS
from utils.logger import logger


class PrintingService:
    """Prepare packet recipes and turn resolved documents into one PDF."""

    def __init__(self, document_service=None, *, temp_root=None, clock=None):
        self.document_service = document_service or DocumentService()
        self.temp_root = Path(temp_root or tempfile.gettempdir())
        self._clock = clock or time.time

    @staticmethod
    def document_label(document_type):
        return DOCUMENTS.get(document_type, {}).get("label", document_type)

    @staticmethod
    def document_is_newer(candidate, existing):
        candidate_uploaded = getattr(candidate, "uploaded_at", None)
        existing_uploaded = getattr(existing, "uploaded_at", None)
        if candidate_uploaded and existing_uploaded and candidate_uploaded != existing_uploaded:
            return candidate_uploaded > existing_uploaded
        if candidate_uploaded and not existing_uploaded:
            return True
        if existing_uploaded and not candidate_uploaded:
            return False
        return getattr(candidate, "id", 0) > getattr(existing, "id", 0)

    def prepare_packet(self, packet_key, missionary):
        definition = get_packet_definition(packet_key)
        rules = [rule for rule in definition.documents if rule.applies_to(missionary)]
        documents = self.document_service.get_documents(missionary.id)
        newest_by_type = {}
        wanted_types = {rule.document_type for rule in rules}
        for document in documents:
            if getattr(document, "status", "ACTIVE") != "ACTIVE":
                continue
            document_type = getattr(document, "document_type", None)
            if document_type not in wanted_types:
                continue
            existing = newest_by_type.get(document_type)
            if existing is None or self.document_is_newer(document, existing):
                newest_by_type[document_type] = document

        job = PreparedPrintJob(
            job_name=f"{definition.key.title()} Packet - "
            f"{getattr(missionary, 'full_name', 'Missionary')}",
            filename_prefix=definition.filename_prefix,
            missionary=missionary,
        )
        for rule in rules:
            label = self.document_label(rule.document_type)
            record = newest_by_type.get(rule.document_type)
            if record is None:
                if rule.required:
                    job.missing_documents.append(label)
                continue
            try:
                local_path = Path(self.document_service.ensure_local_copy(record))
                if not local_path.is_file():
                    raise DocumentFileUnavailableError(getattr(record, "id", None))
            except DocumentFileUnavailableError:
                if rule.required:
                    job.unavailable_documents.append(label)
                continue
            job.documents.append(
                PreparedDocument(
                    record=record,
                    document_type=rule.document_type,
                    label=label,
                    local_path=local_path,
                    transform_key=rule.transform_key,
                )
            )

        if any(doc.transform_key == "interpol_passport" for doc in job.documents):
            job.context["interpol_annotation_lines"] = interpol_annotation_lines(
                missionary, self.document_service
            )
        return job

    def prepare_documents(self, documents, *, job_name="Documents", transforms=None):
        transforms = transforms or {}
        job = PreparedPrintJob(
            job_name=job_name,
            filename_prefix="documents",
        )
        for record in documents:
            document_type = getattr(record, "document_type", "DOCUMENT")
            label = self.document_label(document_type)
            try:
                local_path = Path(self.document_service.ensure_local_copy(record))
                if not local_path.is_file():
                    raise DocumentFileUnavailableError(getattr(record, "id", None))
            except DocumentFileUnavailableError:
                job.unavailable_documents.append(label)
                continue
            job.documents.append(
                PreparedDocument(
                    record=record,
                    document_type=document_type,
                    label=label,
                    local_path=local_path,
                    transform_key=transforms.get(document_type),
                )
            )
        return job

    def create_temp_path(self, job):
        packet_dir = self.temp_root / "MissionLegalApp" / "print_packets"
        packet_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_old_files(packet_dir)
        safe_name = "".join(
            character if character.isalnum() else "_"
            for character in getattr(job.missionary, "full_name", "missionary")
        ).strip("_") or "missionary"
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(self._clock()))
        return packet_dir / f"{job.filename_prefix}_{safe_name}_{timestamp}.pdf"

    def cleanup_old_files(self, packet_dir):
        cutoff = self._clock() - (24 * 60 * 60)
        try:
            for file_path in Path(packet_dir).glob("*.pdf"):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                except Exception:
                    logger.warning("Could not clean old print file: %s", file_path)
        except Exception:
            logger.warning("Could not scan print temp directory")

    def build_pdf(self, job, output_path=None):
        if not job.documents:
            raise ValueError("Print job has no printable documents")
        output_path = Path(output_path or self.create_temp_path(job))
        partial_path = output_path.with_suffix(output_path.suffix + ".partial")
        try:
            packet = fitz.open()
            try:
                for document in job.documents:
                    first_page = packet.page_count
                    source = fitz.open(str(document.local_path))
                    try:
                        if source.is_pdf:
                            packet.insert_pdf(source)
                        else:
                            image_pdf = fitz.open("pdf", source.convert_to_pdf())
                            try:
                                packet.insert_pdf(image_pdf)
                            finally:
                                image_pdf.close()
                    finally:
                        source.close()
                    if document.transform_key and packet.page_count > first_page:
                        transform = PRINT_TRANSFORMS.get(document.transform_key)
                        if transform is None:
                            raise ValueError(
                                f"Unknown print transform: {document.transform_key}"
                            )
                        context = {"missionary": job.missionary, **job.context}
                        transform(packet[first_page], context=context)
                packet.save(str(partial_path))
            finally:
                packet.close()
            os.replace(partial_path, output_path)
        except Exception:
            try:
                partial_path.unlink(missing_ok=True)
            except Exception:
                logger.warning("Could not remove partial print file: %s", partial_path)
            raise
        return output_path

    def deliver(self, output_path, output_mode=PrintOutputMode.OPEN_PREVIEW):
        output_mode = PrintOutputMode(output_mode)
        if output_mode == PrintOutputMode.DIRECT_PRINT:
            raise NotImplementedError("Direct printer output is not implemented")
        if output_mode == PrintOutputMode.SAVE_AS:
            return
        path = str(output_path)
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def finish_job(self, job, output_mode=PrintOutputMode.OPEN_PREVIEW):
        if not job.documents:
            return PrintResult(
                status=PrintStatus.NOTHING_TO_PRINT,
                missing_documents=tuple(job.missing_documents),
                unavailable_documents=tuple(job.unavailable_documents),
            )
        output_path = None
        try:
            output_path = self.build_pdf(job)
            self.deliver(output_path, output_mode)
            logger.info("Print job completed: %s -> %s", job.job_name, output_path)
            return PrintResult(
                status=PrintStatus.COMPLETED,
                output_path=output_path,
                missing_documents=tuple(job.missing_documents),
                unavailable_documents=tuple(job.unavailable_documents),
            )
        except Exception as error:
            logger.exception("Print job failed: %s", job.job_name)
            return PrintResult(
                status=PrintStatus.OUTPUT_FAILED,
                output_path=output_path,
                missing_documents=tuple(job.missing_documents),
                unavailable_documents=tuple(job.unavailable_documents),
                error=error,
            )

    def print_packet(
        self,
        packet_key,
        missionary,
        *,
        output_mode=PrintOutputMode.OPEN_PREVIEW,
    ):
        """Synchronous service entry point for non-UI callers."""
        try:
            job = self.prepare_packet(packet_key, missionary)
        except Exception as error:
            logger.exception("Print packet preparation failed: %s", packet_key)
            return PrintResult(status=PrintStatus.PREPARATION_FAILED, error=error)
        return self.finish_job(job, output_mode)

    def print_documents(
        self,
        documents,
        *,
        job_name="Documents",
        transforms=None,
        output_mode=PrintOutputMode.OPEN_PREVIEW,
    ):
        """Synchronous entry point for arbitrary document collections."""
        try:
            job = self.prepare_documents(
                documents,
                job_name=job_name,
                transforms=transforms,
            )
        except Exception as error:
            logger.exception("Print document preparation failed: %s", job_name)
            return PrintResult(status=PrintStatus.PREPARATION_FAILED, error=error)
        return self.finish_job(job, output_mode)
