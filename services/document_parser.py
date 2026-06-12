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
    "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA": [
        (
            ["usuario", "user"],
            "tramite_usuario",
        ),
        (
            ["contraseña", "contrasena", "contraseÃ±a", "password"],
            "tramite_contrasena",
        ),
    ],
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


CREDENTIAL_FIELDS = {
    "tramite_usuario",
    "tramite_contrasena",
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
        if document_type == "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA":
            return self._parse_tramite_credentials(text, ocr_fields)

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

    def _parse_tramite_credentials(self, text, ocr_fields):
        result = {}
        normalized_text = self._normalize(text)

        if "tramite_usuario" in ocr_fields:
            usuario = self._extract_tramite_usuario(text, normalized_text)
            if usuario:
                result["tramite_usuario"] = usuario

        if "tramite_contrasena" in ocr_fields:
            contrasena = self._extract_tramite_contrasena(
                text,
                normalized_text,
            )
            if contrasena:
                result["tramite_contrasena"] = contrasena

        return result

    def _extract_tramite_usuario(self, text, normalized_text):
        return self._extract_credential_value(
            text,
            normalized_text,
            "tramite_usuario",
            prefer_previous=False,
        )

    def _extract_tramite_contrasena(self, text, normalized_text):
        return self._extract_credential_value(
            text,
            normalized_text,
            "tramite_contrasena",
            prefer_previous=True,
        )

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
            elif field in CREDENTIAL_FIELDS:
                found = self._extract_credential_value(
                    text,
                    normalized_text,
                    field,
                )
                if found:
                    result[field] = found
            elif field == "carnet_number":
                carnet = self._extract_carnet_number(text)
                if carnet:
                    result[field] = carnet

        return result

    def _extract_credential_value(
        self,
        text,
        normalized_text,
        field,
        prefer_previous=False,
    ):
        label_patterns = [
            patterns
            for patterns, mapped_field
            in LABEL_FIELD_MAP.get(
                "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA",
                [],
            )
            if mapped_field == field
        ]
        labels = label_patterns[0] if label_patterns else []
        if not labels:
            return None

        lines = text.splitlines()
        norm_lines = normalized_text.splitlines()

        for i, norm_line in enumerate(norm_lines):
            if not any(self._normalize(label) in norm_line for label in labels):
                continue

            line = lines[i] if i < len(lines) else ""
            value = self._value_after_credential_label(line, labels)
            if value:
                if self._is_credential_candidate(value):
                    return value
                continue

            if prefer_previous:
                value = self._nearest_credential_candidate(
                    lines,
                    range(i - 1, max(i - 8, -1), -1),
                    stop_on_gap=True,
                )
                if value:
                    return value

            value = self._nearest_credential_candidate(
                lines,
                range(i + 1, min(i + 8, len(lines))),
            )
            if value:
                return value

        for label in labels:
            label_index = normalized_text.find(self._normalize(label))
            if label_index < 0:
                continue
            snippet = text[label_index: label_index + 180]
            value = self._value_after_credential_label(snippet, labels)
            if value and self._is_credential_candidate(value):
                return value

        return None

    def _nearest_credential_candidate(
        self,
        lines,
        indexes,
        stop_on_gap=False,
    ):
        for index in indexes:
            if index < 0 or index >= len(lines):
                continue
            if stop_on_gap and not lines[index].strip():
                return None
            normalized = self._normalize(lines[index])
            if any(
                label in normalized
                for label in ("usuario", "user", "contrasena", "password")
            ):
                return None
            value = self._clean_credential_value(lines[index])
            if value and self._is_credential_candidate(value):
                return value
        return None

    def _value_after_credential_label(self, text, labels):
        label_pattern = "|".join(
            re.escape(label)
            for label in sorted(labels, key=len, reverse=True)
        )
        next_label_pattern = (
            r"usuario|user|contrase(?:n|ñ)a|password"
        )
        match = re.search(
            rf"(?:{label_pattern})\s*[:=\-]?\s*(.*?)"
            rf"(?=\s+(?:{next_label_pattern})\s*[:=\-]?|$)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        return self._clean_credential_value(match.group(1))

    def _clean_credential_value(self, value):
        if not value:
            return None
        value = re.sub(r"\s+", " ", str(value)).strip(" \t\r\n:=-")
        value = re.sub(
            r"^(usuario|user|contrase(?:n|ñ)a|password)\s*[:=\-]?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip(" \t\r\n:=-")
        if not value:
            return None
        if len(value) > 80:
            value = value[:80].strip()
        return value

    def _is_credential_candidate(self, value):
        normalized = self._normalize(value)
        if normalized in {
            "usuario",
            "user",
            "contrasena",
            "password",
            "enlace de",
        }:
            return False
        if "http" in normalized or "@" in value:
            return False
        if " " in value:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9._-]{4,40}", value))

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
