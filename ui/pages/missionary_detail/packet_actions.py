"""Interpol packet selection, validation, and PDF generation."""

import tempfile
import time
from pathlib import Path

import fitz

from utils.constants import requires_fbi_document
from utils.logger import logger


INTERPOL_PACKET_DOCUMENT_TYPES = [
    "TAM",
    "PASSPORT",
    "PAGO_INTERPOL",
    "CONSTANCIA_DE_CITA_INTERPOL",
]
FBI_INTERPOL_PACKET_DOCUMENT_TYPES = [
    "TAM",
    "PASSPORT",
    "FBI",
    "PAGO_INTERPOL",
    "CONSTANCIA_DE_CITA_INTERPOL",
]


class InterpolPacketActions:
    """Build an official packet without depending on Missionary Detail widgets."""

    def __init__(
        self,
        missionary,
        document_service,
        *,
        document_label,
        temp_root=None,
        clock=None,
    ):
        self.missionary = missionary
        self.document_service = document_service
        self.document_label = document_label
        self.temp_root = Path(temp_root or tempfile.gettempdir())
        self._clock = clock or time.time

    def document_types(self):
        if requires_fbi_document(self.missionary):
            return list(FBI_INTERPOL_PACKET_DOCUMENT_TYPES)
        return list(INTERPOL_PACKET_DOCUMENT_TYPES)

    @staticmethod
    def document_is_newer(candidate, existing):
        candidate_uploaded = getattr(candidate, "uploaded_at", None)
        existing_uploaded = getattr(existing, "uploaded_at", None)
        if candidate_uploaded and existing_uploaded:
            if candidate_uploaded != existing_uploaded:
                return candidate_uploaded > existing_uploaded
        elif candidate_uploaded and not existing_uploaded:
            return True
        elif existing_uploaded and not candidate_uploaded:
            return False
        return getattr(candidate, "id", 0) > getattr(existing, "id", 0)

    def collect_documents(self):
        documents = self.document_service.get_documents(self.missionary.id)
        packet_document_types = self.document_types()
        docs_by_type = {}
        for document in documents:
            if getattr(document, "status", "ACTIVE") != "ACTIVE":
                continue
            document_type = getattr(document, "document_type", None)
            if document_type not in packet_document_types:
                continue
            existing = docs_by_type.get(document_type)
            if existing is None or self.document_is_newer(document, existing):
                docs_by_type[document_type] = document

        packet_docs = []
        missing_labels = []
        for document_type in packet_document_types:
            label = self.document_label(document_type)
            document = docs_by_type.get(document_type)
            file_path = (
                Path(getattr(document, "file_path", ""))
                if document is not None
                else None
            )
            if document is None or not file_path or not file_path.exists():
                missing_labels.append(label)
                continue
            packet_docs.append(
                {
                    "document_type": document_type,
                    "label": label,
                    "file_path": str(file_path),
                }
            )
        return packet_docs, missing_labels

    def create_temp_path(self):
        packet_dir = self.temp_root / "MissionLegalApp" / "print_packets"
        packet_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_old_files(packet_dir)
        missionary_name = getattr(self.missionary, "full_name", "missionary")
        safe_name = "".join(
            character if character.isalnum() else "_"
            for character in missionary_name
        ).strip("_") or "missionary"
        timestamp = time.strftime(
            "%Y%m%d_%H%M%S",
            time.localtime(self._clock()),
        )
        return str(packet_dir / f"interpol_packet_{safe_name}_{timestamp}.pdf")

    def cleanup_old_files(self, packet_dir):
        cutoff = self._clock() - (24 * 60 * 60)
        try:
            for file_path in Path(packet_dir).glob("interpol_packet_*.pdf"):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                except Exception:
                    logger.warning("Could not clean up old packet file: %s", file_path)
        except Exception:
            logger.warning("Could not scan packet temp directory")

    def build_pdf(self, packet_docs, output_path):
        packet = fitz.open()
        try:
            for document in packet_docs:
                first_page = packet.page_count
                source = fitz.open(document["file_path"])
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
                if (
                    document.get("document_type") == "PASSPORT"
                    and packet.page_count > first_page
                ):
                    self.annotate_passport(packet[first_page])
            if packet.page_count == 0:
                raise ValueError("Interpol packet has no printable pages")
            packet.save(output_path)
        finally:
            packet.close()

    def annotate_passport(self, page):
        lines = self.validated_annotation_lines()
        rect = page.rect
        point = fitz.Point(rect.width * 0.14, rect.height * 0.72)
        page.insert_textbox(
            fitz.Rect(point.x, point.y, rect.width * 0.9, rect.height * 0.95),
            "\n".join(lines),
            fontsize=10,
            fontname="helv",
            color=(0, 0, 0),
            lineheight=1.45,
        )

    def validated_annotation_lines(self):
        api_client = getattr(self.document_service, "api_client", None)
        if api_client is not None:
            details = api_client.get("/v1/server/configuration")
        else:
            from server.configuration import load_server_configuration

            details = load_server_configuration()

        def first_name(value, override):
            override = str(override or "").strip()
            if override:
                return override
            tokens = str(value or "").strip().split()
            return tokens[0] if tokens else ""

        values = {
            "Area Office address": str(
                details.get("interpol_area_office_address") or ""
            ).strip(),
            "home address": str(
                getattr(self.missionary, "home_address", "") or ""
            ).strip(),
            "father name": first_name(
                getattr(self.missionary, "father_name", ""),
                getattr(self.missionary, "father_first_name_override", ""),
            ),
            "mother name": first_name(
                getattr(self.missionary, "mother_name", ""),
                getattr(self.missionary, "mother_first_name_override", ""),
            ),
            "secretary phone": str(
                details.get("interpol_secretary_phone") or ""
            ).strip(),
        }
        missing = [label for label, value in values.items() if not value]
        if missing:
            raise ValueError(
                "Add the following before generating the official copy: "
                + ", ".join(missing)
                + "."
            )
        return [
            f"Dirección Actual: {values['Area Office address']}",
            f"Dirección en País de Origen: {values['home address']}",
            f"Nombre de Padre: {values['father name']}",
            f"Nombre de Madre: {values['mother name']}",
            f"Teléfono: {values['secretary phone']}",
        ]
