import re

from datetime import date

from utils.constants import DOCUMENTS

from services.passport_parser import PassportParser

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


class DocumentParser:

    def parse(
        self,
        text,
        document_type,
    ):
        doc_config = DOCUMENTS.get(
            document_type,
            {},
        )

        ocr_fields = doc_config.get(
            "ocr_fields",
            [],
        )

        if not ocr_fields:
            return {}

        logger.info(
            f"Parsing OCR text for "
            f"document type: {document_type}"
        )

        if document_type == "PASSPORT":
            return self._parse_passport(text)

        return self._parse_by_fields(
            text,
            ocr_fields,
        )

    # ==========================================
    # PASSPORT
    # ==========================================

    def _parse_passport(self, text):
        parser = PassportParser()

        mrz_data = parser.parse(text)

        result = {}

        if mrz_data.get("passport_number"):
            result["passport_number"] = (
                mrz_data["passport_number"]
            )

        if mrz_data.get("nationality"):
            result["nationality"] = (
                mrz_data["nationality"]
            )

        surname = mrz_data.get("surname", "")

        given_names = mrz_data.get(
            "given_names",
            "",
        )

        if surname or given_names:
            result["full_name"] = (
                f"{surname} {given_names}".strip()
            )

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

        logger.info(
            f"Passport parse result: "
            f"{list(result.keys())}"
        )

        return result

    # ==========================================
    # GENERIC (date-based documents)
    # ==========================================

    def _parse_by_fields(
        self,
        text,
        ocr_fields,
    ):
        result = {}

        all_dates = self._extract_all_dates(text)

        logger.info(
            f"Found {len(all_dates)} dates in document"
        )

        for field in ocr_fields:

            # ======================================
            # Single-date fields
            # ======================================

            if field in (
                "arrival_date",
                "interpol_appointment_date",
                "biometric_appointment_date",
                "pickup_appointment_date",
                "prorroga_expiration",
                "cancelacion_date",
            ):
                if all_dates:
                    result[field] = all_dates[0]

            # ======================================
            # Carnet-specific fields
            # ======================================

            elif field == "carnet_number":
                carnet = self._extract_carnet_number(
                    text
                )

                if carnet:
                    result["carnet_number"] = carnet

            elif field == "carnet_issue_date":
                if len(all_dates) >= 2:
                    result["carnet_issue_date"] = (
                        all_dates[0]
                    )

                elif all_dates:
                    result["carnet_issue_date"] = (
                        all_dates[0]
                    )

            elif field == "residency_expiration":
                if len(all_dates) >= 2:
                    result["residency_expiration"] = (
                        all_dates[-1]
                    )

                elif all_dates:
                    result["residency_expiration"] = (
                        all_dates[0]
                    )

        return result

    # ==========================================
    # DATE EXTRACTION
    # ==========================================

    def _extract_all_dates(self, text):
        found = []

        seen = set()

        # DD/MM/YYYY or DD-MM-YYYY
        for d, m, y in re.findall(
            r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b',
            text,
        ):
            parsed = self._safe_date(
                int(y),
                int(m),
                int(d),
            )

            if parsed and str(parsed) not in seen:
                found.append(parsed)
                seen.add(str(parsed))

        # DD de MES de YYYY (Spanish)
        for d, m_str, y in re.findall(
            r'\b(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\b',
            text,
            re.IGNORECASE,
        ):
            month = SPANISH_MONTHS.get(m_str.lower())

            if month:
                parsed = self._safe_date(
                    int(y),
                    month,
                    int(d),
                )

                if parsed and str(parsed) not in seen:
                    found.append(parsed)
                    seen.add(str(parsed))

        # YYYY-MM-DD (ISO)
        for y, m, d in re.findall(
            r'\b(\d{4})\-(\d{2})\-(\d{2})\b',
            text,
        ):
            parsed = self._safe_date(
                int(y),
                int(m),
                int(d),
            )

            if parsed and str(parsed) not in seen:
                found.append(parsed)
                seen.add(str(parsed))

        return found

    def _extract_carnet_number(self, text):
        patterns = [
            r'\bCE[:\s#°]*([A-Z0-9]{6,12})\b',
            r'\bN[°º][:\s]*([A-Z0-9]{6,12})\b',
            r'[Cc]arnet[:\s#°]*([A-Z0-9]{6,12})\b',
            r'[Ee]xtranjeria[:\s#°]*([A-Z0-9]{6,12})\b',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)

            if match:
                return match.group(1)

        return None

    # ==========================================
    # DATE HELPERS
    # ==========================================

    def _parse_mrz_date(self, yymmdd):
        if not yymmdd or len(yymmdd) < 6:
            return None

        try:
            yy = int(yymmdd[0:2])
            mm = int(yymmdd[2:4])
            dd = int(yymmdd[4:6])

            year = (
                2000 + yy
                if yy < 50
                else 1900 + yy
            )

            return self._safe_date(year, mm, dd)

        except Exception:
            logger.warning(
                f"Could not parse MRZ date: {yymmdd}"
            )

            return None

    def _safe_date(self, year, month, day):
        try:
            return date(year, month, day)

        except Exception:
            return None
