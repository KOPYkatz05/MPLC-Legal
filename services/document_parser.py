import re
import unicodedata

from datetime import date

from services.passport_parser import PassportParser
from utils.constants import DOCUMENTS
from utils.logger import logger


TRAMITE_DOCUMENT_TYPE = "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA"
INTERPOL_CITA_DOCUMENT_TYPE = "CONSTANCIA_DE_CITA_INTERPOL"

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

COMPACT_MONTHS = {
    **SPANISH_MONTHS,
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
    "jan": 1,
    "apr": 4,
    "aug": 8,
    "dec": 12,
}


LABEL_FIELD_MAP = {
    "CONSTANCIA_DE_TRAMITE_CARNE_DE_EXTRANJERIA": [
        (
            ["usuario", "user"],
            "tramite_usuario",
        ),
        (
            ["contraseña", "contrasena", "password"],
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


LAYOUT_APPOINTMENT_DATE_LABELS = {
    INTERPOL_CITA_DOCUMENT_TYPE: {
        "interpol_appointment_date": (
            "fecha de cita",
            "fecha cita",
            "programacion de cita",
        ),
    },
    "CONSTANCIA_DE_CITA_BIOMETRICO": {
        "biometric_appointment_date": (
            "fecha de cita",
            "fecha cita",
            "programacion de cita",
        ),
    },
    "CITA_RECOJO": {
        "pickup_appointment_date": (
            "fecha de cita",
            "fecha cita",
            "fecha de recojo",
            "cita recojo",
            "programacion de cita",
        ),
    },
    "APROBACION_DE_PRORROGA": {
        "prorroga_expiration": (
            "fecha de vencimiento de su residencia",
            "fecha de vencimiento",
            "vencimiento residencia",
        ),
    },
    "TAM": {
        "arrival_date": (
            "fecha de ingreso",
            "ingreso",
            "arribo",
            "llegada",
        ),
    },
}


TRAMITE_CREDENTIAL_LABELS = {
    "tramite_usuario": ("usuario", "user"),
    "tramite_contrasena": ("contrasena", "contraseña", "password"),
}


class DocumentParser:

    def parse(self, text, document_type, layout_pages=None):
        doc_config = DOCUMENTS.get(document_type, {})
        ocr_fields = doc_config.get("ocr_fields", [])

        if not ocr_fields:
            return {}

        logger.info(
            f"Parsing OCR text for document type: {document_type}"
        )

        if document_type == "PASSPORT":
            return self._parse_passport(text)
        if document_type == TRAMITE_DOCUMENT_TYPE:
            return self._parse_tramite_credentials(
                text,
                ocr_fields,
                layout_pages=layout_pages,
            )
        if document_type in LAYOUT_APPOINTMENT_DATE_LABELS:
            return self._parse_layout_appointment_dates(
                text,
                document_type,
                ocr_fields,
                layout_pages=layout_pages,
            )

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

    def _parse_layout_appointment_dates(
        self,
        text,
        document_type,
        ocr_fields,
        layout_pages=None,
    ):
        result = {}
        rows = self._layout_rows(layout_pages or [])
        label_map = LAYOUT_APPOINTMENT_DATE_LABELS.get(document_type, {})

        for field in ocr_fields:
            labels = label_map.get(field)
            if not labels:
                continue
            value = self._date_from_layout_rows(rows, labels)
            if value:
                result[field] = value

        if all(result.get(field) for field in ocr_fields):
            return result

        if rows and any(
            self._layout_rows_contain_label(rows, labels)
            for labels in label_map.values()
        ):
            return result

        fallback = self._parse_by_fields(text, document_type, ocr_fields)
        for field, value in fallback.items():
            if not result.get(field):
                result[field] = value
        return result

    def _parse_tramite_credentials(
        self,
        text,
        ocr_fields,
        layout_pages=None,
    ):
        result = self._parse_tramite_credentials_from_layout(
            layout_pages or [],
            ocr_fields,
        )
        if all(result.get(field) for field in ocr_fields):
            return result

        fallback = self._parse_tramite_credentials_from_text(
            text,
            ocr_fields,
        )
        for field, value in fallback.items():
            if not result.get(field):
                result[field] = value
        return result

    def _parse_tramite_credentials_from_layout(
        self,
        layout_pages,
        ocr_fields,
    ):
        result = {}
        used_values = set()
        rows = self._layout_rows(layout_pages)
        for field in ocr_fields:
            if field not in CREDENTIAL_FIELDS:
                continue
            value = self._credential_from_layout_rows(
                rows,
                field,
                used_values,
            )
            if value:
                result[field] = value
                used_values.add(value)
        return result

    def _layout_rows(self, layout_pages):
        items = []
        for page in layout_pages or []:
            page_number = page.get("page", 0)
            for item in page.get("words") or page.get("lines") or []:
                normalized = self._layout_item(item, page_number)
                if normalized:
                    items.append(normalized)

        if not items:
            return []

        heights = [
            max(item["y1"] - item["y0"], 1.0)
            for item in items
        ]
        median_height = sorted(heights)[len(heights) // 2]
        threshold = max(median_height * 0.8, 3.0)
        rows = []

        for item in sorted(
            items,
            key=lambda value: (
                value["page"],
                value["cy"],
                value["x0"],
            ),
        ):
            if (
                rows
                and rows[-1]["page"] == item["page"]
                and abs(rows[-1]["cy"] - item["cy"]) <= threshold
            ):
                rows[-1]["items"].append(item)
                count = len(rows[-1]["items"])
                rows[-1]["cy"] = (
                    (rows[-1]["cy"] * (count - 1)) + item["cy"]
                ) / count
            else:
                rows.append({
                    "page": item["page"],
                    "cy": item["cy"],
                    "items": [item],
                })

        for row in rows:
            row["items"].sort(key=lambda item: item["x0"])

        return rows

    def _row_text(self, row):
        return " ".join(
            item["text"]
            for item in row.get("items", [])
        )

    def _date_from_layout_rows(self, rows, labels):
        for row_index, row in enumerate(rows):
            label_spans = self._label_spans_in_row(row, labels)
            if not label_spans:
                continue

            date_on_label_row = self._extract_all_dates(
                self._row_text(row)
            )
            if date_on_label_row:
                return date_on_label_row[0]

            candidates = []

            for candidate_row in rows[row_index + 1:]:
                if candidate_row["page"] != row["page"]:
                    break

                vertical_distance = candidate_row["cy"] - row["cy"]
                if vertical_distance < 0:
                    continue
                if vertical_distance > 220:
                    break

                for date_candidate in self._date_candidates_in_row(
                    candidate_row
                ):
                    for label_span in label_spans:
                        horizontal_distance = abs(
                            date_candidate["center"] - label_span["center"]
                        )
                        overlap = min(
                            date_candidate["right"],
                            label_span["right"],
                        ) - max(
                            date_candidate["left"],
                            label_span["left"],
                        )
                        tolerance = max(
                            160.0,
                            (label_span["right"] - label_span["left"]) * 2.5,
                        )
                        if overlap < 0 and horizontal_distance > tolerance:
                            continue
                        candidates.append((
                            vertical_distance,
                            horizontal_distance,
                            date_candidate["date"],
                        ))

            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]))
                return candidates[0][2]

        return None

    def _layout_rows_contain_label(self, rows, labels):
        return any(
            self._label_spans_in_row(row, labels)
            for row in rows
        )

    def _label_spans_in_row(self, row, labels):
        items = row.get("items", [])
        spans = []
        normalized_labels = [
            self._normalize(label).strip(" :ï¼š=-")
            for label in labels
        ]

        for index, item in enumerate(items):
            item_text = self._normalize(item["text"]).strip(" :ï¼š=-")
            for label in normalized_labels:
                if item_text == label or label in item_text:
                    spans.append(self._span_from_items([item]))

        for label in normalized_labels:
            label_word_count = len(label.split())
            max_window = min(len(items), label_word_count + 1)
            for start in range(len(items)):
                for end in range(
                    start + 1,
                    min(len(items), start + max_window) + 1,
                ):
                    window_items = items[start:end]
                    text = self._normalize(
                        " ".join(item["text"] for item in window_items)
                    ).strip(" :ï¼š=-")
                    if text == label:
                        spans.append(self._span_from_items(window_items))

        deduped = []
        seen = set()
        for span in spans:
            key = (
                round(span["left"], 2),
                round(span["right"], 2),
                round(span["center"], 2),
            )
            if key not in seen:
                deduped.append(span)
                seen.add(key)
        return deduped

    def _span_from_items(self, items):
        left = min(item["x0"] for item in items)
        right = max(item["x1"] for item in items)
        return {
            "left": left,
            "right": right,
            "center": (left + right) / 2,
        }

    def _date_candidates_in_row(self, row):
        candidates = []
        for item in row.get("items", []):
            dates = self._extract_all_dates(item["text"])
            for parsed_date in dates:
                candidates.append({
                    "date": parsed_date,
                    "left": item["x0"],
                    "right": item["x1"],
                    "center": (item["x0"] + item["x1"]) / 2,
                })

        if candidates:
            return candidates

        dates = self._extract_all_dates(self._row_text(row))
        if not dates:
            return []

        left = min(item["x0"] for item in row["items"])
        right = max(item["x1"] for item in row["items"])
        return [
            {
                "date": parsed_date,
                "left": left,
                "right": right,
                "center": (left + right) / 2,
            }
            for parsed_date in dates
        ]

    def _layout_item(self, item, page_number=0):
        text = str(item.get("text") or "").strip()
        if not text:
            return None

        x0 = item.get("x0")
        y0 = item.get("y0")
        x1 = item.get("x1")
        y1 = item.get("y1")
        if None in {x0, y0, x1, y1}:
            bbox = item.get("bbox") or []
            xs = []
            ys = []
            for point in bbox:
                try:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
                except Exception:
                    continue
            if xs and ys:
                x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)

        try:
            x0 = float(x0)
            y0 = float(y0)
            x1 = float(x1)
            y1 = float(y1)
        except (TypeError, ValueError):
            return None

        return {
            "text": text,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "cy": (y0 + y1) / 2,
            "page": int(item.get("page", page_number)),
        }

    def _credential_from_layout_rows(
        self,
        rows,
        field,
        used_values=None,
    ):
        labels = TRAMITE_CREDENTIAL_LABELS.get(field, ())
        used_values = used_values or set()

        for row in rows:
            items = row["items"]
            for index, item in enumerate(items):
                if not self._is_credential_label(
                    item["text"],
                    labels,
                    require_marker=True,
                ):
                    continue

                inline_value = self._value_after_credential_label(
                    item["text"],
                    labels,
                )
                if (
                    inline_value
                    and inline_value not in used_values
                    and self._is_credential_candidate(inline_value)
                ):
                    return inline_value

                right_candidates = [
                    candidate["text"]
                    for candidate in items[index + 1:]
                    if candidate["x0"] >= item["x1"] - 2
                ]
                for candidate in right_candidates:
                    cleaned = self._clean_credential_value(candidate)
                    if (
                        cleaned
                        and cleaned not in used_values
                        and self._is_credential_candidate(cleaned)
                    ):
                        return cleaned

        return None

    def _is_credential_label(self, text, labels, require_marker=False):
        if require_marker and not any(
            marker in str(text)
            for marker in (":", "：")
        ):
            return False
        normalized = self._normalize(text).strip(" :：=-")
        return normalized in labels

    def _parse_tramite_credentials_from_text(self, text, ocr_fields):
        result = {}
        normalized_text = self._normalize(text)
        used_values = set()
        for field in ocr_fields:
            if field not in CREDENTIAL_FIELDS:
                continue
            value = self._extract_credential_value(
                text,
                normalized_text,
                field,
                used_values=used_values,
            )
            if value:
                result[field] = value
                used_values.add(value)
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
        used_values=None,
    ):
        labels = TRAMITE_CREDENTIAL_LABELS.get(field, ())
        used_values = used_values or set()
        lines = text.splitlines()
        norm_lines = normalized_text.splitlines()

        for index in range(len(norm_lines)):
            line = lines[index] if index < len(lines) else ""
            if not any(
                self._is_credential_label(part, labels)
                for part in line.split()
            ):
                continue

            value = self._value_after_credential_label(line, labels)
            if (
                value
                and value not in used_values
                and self._is_credential_candidate(value)
            ):
                return value

            for next_index in range(index + 1, min(index + 6, len(lines))):
                value = self._clean_credential_value(lines[next_index])
                if (
                    value
                    and value not in used_values
                    and self._is_credential_candidate(value)
                ):
                    return value

        return None

    def _value_after_credential_label(self, text, labels):
        label_pattern = "|".join(
            re.escape(label)
            for label in sorted(labels, key=len, reverse=True)
        )
        match = re.search(
            rf"(?:{label_pattern})\s*[:：=\-]?\s*(.+)$",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        return self._clean_credential_value(match.group(1))

    def _clean_credential_value(self, value):
        if not value:
            return None
        value = re.sub(r"\s+", " ", str(value)).strip(" \t\r\n:：=-")
        value = re.sub(
            r"^(usuario|user|contrasena|contraseña|password)\s*[:：=\-]?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip(" \t\r\n:：=-")
        return value or None

    def _is_credential_candidate(self, value):
        if not value:
            return False
        normalized = self._normalize(value).strip()
        if normalized in {
            "usuario",
            "user",
            "contrasena",
            "password",
            "enlace",
            "enlace de",
        }:
            return False
        if "http" in normalized or "@" in normalized:
            return False
        if " " in normalized:
            return False
        return bool(re.fullmatch(r"[a-z0-9._-]{4,40}", normalized))

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

        for d, m_str, y in re.findall(
            r"\b(\d{1,2})([a-z]{3,10})(\d{4})\b",
            normalized,
            re.IGNORECASE,
        ):
            month = COMPACT_MONTHS.get(m_str.lower())
            if month:
                self._append_date(found, seen, int(y), month, int(d))

        return found

    def _extract_carnet_number(self, text):
        patterns = [
            r"\bCE[:\s#°º]*([A-Z0-9]{6,16})\b",
            r"\bN[°º][:\s]*([A-Z0-9]{6,16})\b",
            r"\bCARNET[:\s#°º]*([A-Z0-9]{6,16})\b",
            r"\bEXTRANJERIA[:\s#°º]*([A-Z0-9]{6,16})\b",
        ]

        upper_text = self._normalize(text).upper()
        for pattern in patterns:
            match = re.search(pattern, upper_text)
            if match:
                return self._clean_carnet_number(match.group(1))

        return None

    def _clean_carnet_number(self, value):
        value = str(value or "").strip().upper()
        country_prefixed = re.fullmatch(r"[A-Z]{3}(\d{6,13})", value)
        if country_prefixed:
            return country_prefixed.group(1)
        return value or None

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
