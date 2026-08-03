"""Canonical country-name handling for missionary nationality values."""

import json

from config import PASSPORT_COUNTRY_CODES
from utils.runtime_paths import resource_path


def _load_country_names_by_code():
    data_path = resource_path("data", "country_names_by_code.json")
    names = {}
    if data_path.exists():
        try:
            with data_path.open("r", encoding="utf-8") as handle:
                names = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            names = {}

    names.update(
        {
            "GBR": "United Kingdom",
            "KOR": "South Korea",
            "SGS": "South Georgia and the South Sandwich Islands",
            "SLV": "El Salvador",
            "USA": "United States",
        }
    )
    return {code: name for code, name in names.items() if code in PASSPORT_COUNTRY_CODES}


COUNTRY_NAMES_BY_CODE = _load_country_names_by_code()
_COUNTRY_CODES_BY_NAME = {
    name.casefold(): code for code, name in COUNTRY_NAMES_BY_CODE.items()
}


def country_code(value):
    """Return the known three-letter code for a code or country name."""
    text = str(value or "").strip()
    if not text:
        return None
    code = text.upper()
    if code in PASSPORT_COUNTRY_CODES:
        return code
    return _COUNTRY_CODES_BY_NAME.get(text.casefold())


def normalize_nationality(value):
    """Convert known passport codes to the app's full country-name format."""
    text = str(value or "").strip()
    if not text:
        return None
    code = country_code(text)
    return COUNTRY_NAMES_BY_CODE.get(code, text)
