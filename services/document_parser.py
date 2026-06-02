import re
import unicodedata

from datetime import date

from services.passport_parser import PassportParser
from utils.constants import DOCUMENTS
from utils.logger import logger


SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


LABEL_FIELD_MAP = {
    "CONSTANCIA_DE_CITA_INTERPOL": [
        (
            ["fecha de cita", "cita interpol", "cita:"],
            "interpol_appointment_date",
        ),
    ],
    "CONSTANCIA_DE_CITA_BIOMETRICO": [
        (
            ["fecha de cita", "cita biometrico", "biometrico"],
            "biometric_appointment_date",
        ),
    ],
    "CITA_RECOJO": [
        (
            ["fecha de recojo", "cita recojo", "recojo"],
            "pickup_appointment_date",
        ),
    ],
    "APROBACION_DE_PRORROGA": [
        (
            ["fecha de vencimiento", "vencimiento", "prorroga", "hasta"],
            "prorroga_expiration",
        ),
    ],
    "CONSTANCIA_CANCELACION": [
        (
            ["fecha de cancelacion", "cancelacion", "fecha"],
            "cancelacion_date",
        ),
    ],
    "TAM": [
        (
            ["fecha de ingreso", "ingreso", "arribo", "llegada"],
            "arrival_date",
        ),
        (
            ["fecha de vencimiento", "vencimiento", "vence", "validez"],
            "visa_expiration",
        ),
    ],
    "CARNE_DE_EXTRANJERIA": [
        (
            ["fecha de expedicion", "expedicion", "emision"],
            "carnet_issue_date",
        ),
        (
            ["fecha de vencimiento", "vencimiento", "vence", "validez"],
            "residency_expiration",
        ),
    ],
}


DATE_FIELDS = {
    "arrival_date",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
    "prorroga_expiration",
    "cancelacion_date",
    "visa_expiration",
    "carnet_issue_date",
    "residency_expiration",
}


class DocumentParser:

    def parse(self, text, document_type):
        doc_config = DOCUMENTS.get(document_type, {})
        ocr_fields = doc_config.get("ocr_fields", [])

        if not ocr_fields:
            return {}

        logger.info(
            f"Parsing OCR text for document type: {document_type}"
        )

        if document_type == "PASSPORT":
            return self._parse_passport(text)

        return self._parse_by_fields(
            text, document_type, ocr_fields
        )

    def _parse_passport(self, text):
        parser = PassportParser()
        mrz_data = parser.parse(text)
        result = {}

        if mrz_data.get("passport_number"):
            result["passport_number"] = mrz_data["passport_number"]

        if mrz_data.get("nationality"):
            result["nationality"] = mrz_data["nationality"]

        surname = mrz_data.get("surname", "")
        given_names = mrz_data.get("given_names", "")

        if surname or given_names:
            result["full_name"] = f"{surname} {given_names}".strip()

        dob = mrz_data.get("date_of_birth", "")
        if dob:
            parsed_dob = self._parse_mrz_date(dob)
            if parsed_dob:
                result["date_of_birth"] = parsed_dob

        expiry = mrz_data.get("date_of_expiry", "")
        if expiry:
            parsed_expiry = self._parse_mrz_date(expiry)
            if parsed_expiry:
                result["passport_expiration"] = parsed_expiry

        logger.info(f"Passport parse result: {list(result.keys())}")
        return result

    def _parse_by_fields(self, text, document_type, ocr_fields):
        result = {}
        normalized_text = self._normalize(text)

        for patterns, field in LABEL_FIELD_MAP.get(document_type, []):
            if field not in ocr_fields:
                continue

            found = self._extract_date_near_labels(
                text, normalized_text, patterns
            )
            if found:
                result[field] = found

        all_dates = self._extract_all_dates(text)

        for field in ocr_fields:
            if field in result:
                continue

            if field in DATE_FIELDS:
                found = self._fallback_date_for_field(field, all_dates)
                if found:
                    result[field] = found
            elif field == "carnet_number":
                carnet = self._extract_carnet_number(text)
                if carnet:
                    result[field] = carnet

        return result

    def _extract_date_near_labels(
        self, text, normalized_text, patterns
    ):
        lines = text.splitlines()
        norm_lines = normalized_text.splitlines()

        for i, norm_line in enumerate(norm_lines):
            for pattern in patterns:
                if self._normalize(pattern) in norm_line:
                    date_on_line = self._extract_all_dates(
                        lines[i] if i < len(lines) else ""
                    )
                    if date_on_line:
                        return date_on_line[0]

                    for j in range(i + 1, min(i + 5, len(lines))):
                        dates = self._extract_all_dates(lines[j])
                        if dates:
                            return dates[0]

        for pattern in patterns:
            idx = normalized_text.find(self._normalize(pattern))
            if idx >= 0:
                snippet = text[idx: idx + 160]
                dates = self._extract_all_dates(snippet)
                if dates:
                    return dates[0]

        return None

    def _fallback_date_for_field(self, field, all_dates):
        if not all_dates:
            return None

        if field in {
            "residency_expiration",
            "prorroga_expiration",
            "visa_expiration",
        }:
            return all_dates[-1]

        return all_dates[0]

    def _extract_all_dates(self, text):
        found = []
        seen = set()
        normalized = self._normalize(text)

        for d, m, y in re.findall(
            r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b",
            text,
        ):
            self._append_date(found, seen, int(y), int(m), int(d))

        for y, m, d in re.findall(
            r"\b(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})\b",
            text,
        ):
            self._append_date(found, seen, int(y), int(m), int(d))

        for d, m_str, y in re.findall(
            r"\b(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})\b",
            normalized,
            re.IGNORECASE,
        ):
            month = SPANISH_MONTHS.get(m_str.lower())
            if month:
                self._append_date(found, seen, int(y), month, int(d))

        for d, m_str, y in re.findall(
            r"\b(\d{1,2})\s+([a-z]+)\s+(\d{4})\b",
            normalized,
            re.IGNORECASE,
        ):
            month = SPANISH_MONTHS.get(m_str.lower())
            if month:
                self._append_date(found, seen, int(y), month, int(d))

        return found

    def _extract_carnet_number(self, text):
        patterns = [
            r"\bCE[:\s#°º]*([A-Z0-9]{6,12})\b",
            r"\bN[°º][:\s]*([A-Z0-9]{6,12})\b",
            r"\bCARNET[:\s#°º]*([A-Z0-9]{6,12})\b",
            r"\bEXTRANJERIA[:\s#°º]*([A-Z0-9]{6,12})\b",
        ]

        upper_text = self._normalize(text).upper()
        for pattern in patterns:
            match = re.search(pattern, upper_text)
            if match:
                return match.group(1)

        return None

    def _parse_mrz_date(self, yymmdd):
        if not yymmdd or len(yymmdd) < 6:
            return None

        try:
            yy = int(yymmdd[0:2])
            mm = int(yymmdd[2:4])
            dd = int(yymmdd[4:6])
            year = 2000 + yy if yy < 50 else 1900 + yy
            return self._safe_date(year, mm, dd)
        except Exception:
            logger.warning(f"Could not parse MRZ date: {yymmdd}")
            return None

    def _normalize(self, text):
        text = text.lower()
        text = unicodedata.normalize("NFD", text)
        return "".join(
            c for c in text
            if unicodedata.category(c) != "Mn"
        )

    def _append_date(self, found, seen, year, month, day):
        parsed = self._safe_date(year, month, day)
        if parsed and str(parsed) not in seen:
            found.append(parsed)
            seen.add(str(parsed))

    def _safe_date(self, year, month, day):
        try:
            return date(year, month, day)
        except Exception:
            return None
