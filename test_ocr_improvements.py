import unittest
from datetime import date
from pathlib import Path

import services.upload_pipeline as upload_pipeline
from services.document_parser import DocumentParser


class FakeOcrService:
    def __init__(self, text_by_path):
        self.text_by_path = text_by_path

    def extract_text(self, image_path):
        return self.text_by_path.get(str(image_path), "")


class OcrImprovementTests(unittest.TestCase):

    def test_passport_mrz_parser(self):
        text = "\n".join([
            "P<USADOE<<JOHN<<<<<<<<<<<<<<<<<<<<<<<<<<",
            "1234567897USA9001011M3001019<<<<<<<<<<<<<<06",
        ])

        result = DocumentParser().parse(text, "PASSPORT")

        self.assertEqual(result["passport_number"], "123456789")
        self.assertEqual(result["nationality"], "USA")
        self.assertEqual(result["full_name"], "DOE JOHN")
        self.assertEqual(result["date_of_birth"], date(1990, 1, 1))
        self.assertEqual(
            result["passport_expiration"],
            date(2030, 1, 1),
        )

    def test_label_aware_appointment_parser(self):
        text = "CONSTANCIA\nFecha de cita\n14 de mayo de 2026"

        result = DocumentParser().parse(
            text,
            "CONSTANCIA_DE_CITA_INTERPOL",
        )

        self.assertEqual(
            result["interpol_appointment_date"],
            date(2026, 5, 14),
        )

    def test_tam_uses_label_dates_before_fallback(self):
        text = "\n".join([
            "Fecha de ingreso: 01/04/2026",
            "Fecha de vencimiento: 30/06/2026",
        ])

        result = DocumentParser().parse(text, "TAM")

        self.assertEqual(result["arrival_date"], date(2026, 4, 1))
        self.assertEqual(result["visa_expiration"], date(2026, 6, 30))

    def test_non_ocr_document_skips_export(self):
        result = upload_pipeline.prepare_ocr_ingestion(
            source_file="missing-file.pdf",
            document_type="PHOTO",
        )

        self.assertEqual(result.ocr_status, "skipped")
        self.assertEqual(result.ocr_fields, [])
        self.assertEqual(result.ocr_image_paths, [])

    def test_pipeline_combines_multi_page_text_and_audit_payload(self):
        old_service = upload_pipeline._ocr_service
        old_failed = upload_pipeline._ocr_init_failed
        image_paths = [Path("page1.png"), Path("page2.png")]

        try:
            upload_pipeline._ocr_service = FakeOcrService({
                str(image_paths[0]): "Fecha de ingreso: 01/04/2026",
                str(image_paths[1]): "Vencimiento: 30/06/2026",
            })
            upload_pipeline._ocr_init_failed = False

            result = upload_pipeline.run_ocr_on_images(
                image_paths=image_paths,
                document_type="TAM",
                ocr_fields=["arrival_date", "visa_expiration"],
                export_settings={"pages": "all"},
            )

            self.assertEqual(result.ocr_status, "success")
            self.assertIn("Fecha de ingreso", result.raw_text)
            self.assertEqual(len(result.raw_text_by_page), 2)
            self.assertEqual(
                result.parsed_data["arrival_date"],
                "2026-04-01",
            )
            self.assertEqual(
                result.parsed_data["visa_expiration"],
                "2026-06-30",
            )
            self.assertEqual(
                result.to_audit_payload()["raw_text_by_page"][1]["page"],
                1,
            )
        finally:
            upload_pipeline._ocr_service = old_service
            upload_pipeline._ocr_init_failed = old_failed


if __name__ == "__main__":
    unittest.main()
