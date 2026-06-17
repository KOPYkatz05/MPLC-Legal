from pathlib import Path

from utils.constants import DOCUMENTS
from utils.i18n import TRANSLATIONS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HIGH_VALUE_TEXT_FILES = [
    "utils/i18n.py",
    "utils/constants.py",
    "ui/pages/dashboard_page.py",
    "ui/pages/missionary_detail_page.py",
    "ui/pages/reports_page.py",
    "services/export_service.py",
    "services/document_parser.py",
]
MOJIBAKE_MARKERS = ("Ã", "Â", "â")


def test_high_value_text_sources_have_no_common_mojibake_markers():
    offenders = []

    for relative_path in HIGH_VALUE_TEXT_FILES:
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                offenders.append(f"{relative_path}: {marker}")

    assert offenders == []


def test_spanish_labels_keep_expected_accents():
    assert TRANSLATIONS["en"]["lang_spanish"] == "Español"
    assert TRANSLATIONS["es"]["settings_title"] == "Configuración"
    assert TRANSLATIONS["es"]["tramite_contrasena"] == (
        "Contraseña del trámite"
    )
    assert DOCUMENTS["CARNE_DE_EXTRANJERIA"]["label"] == (
        "Carné de Extranjería"
    )
    assert DOCUMENTS["APROBACION_DE_PRORROGA"]["label"] == (
        "Aprobación de Prórroga"
    )
