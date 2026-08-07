from types import SimpleNamespace

from ui.dialogs.upload_session_dialog import (
    DocumentTypeMenuPicker,
    document_type_menu_sections,
)


def _missionary(nationality="PER"):
    return SimpleNamespace(nationality=nationality, tracking_profile="LEGAL")


def test_document_type_menu_groups_stage_general_dni_and_other_documents():
    sections, direct_items = document_type_menu_sections(_missionary())
    grouped = dict(sections)

    assert [title for title, _keys in sections] == [
        "INTERPOL",
        "CARNET DE EXTRANJERIA",
        "PRORROGA",
        "CANCELACION",
        "GENERAL",
        "OTHER",
    ]
    assert grouped["GENERAL"] == ["TAM", "PASSPORT"]
    assert direct_items == [("DNI", "DNI Copy")]
    assert "CONSTANCIA_DE_PRORROGA" in grouped["PRORROGA"]
    assert grouped["OTHER"] == ["PHOTO", "OTHER"]
    assert "TAM" not in grouped["INTERPOL"]
    assert "CONSTANCIA_DE_PRORROGA" not in grouped["OTHER"]


def test_document_type_menu_includes_conditional_fbi_for_usa_missionary():
    sections, _direct_items = document_type_menu_sections(
        _missionary("USA")
    )

    assert dict(sections)["INTERPOL"][0] == "FBI"


def test_document_type_menu_picker_exposes_combo_compatible_selection(qtbot):
    picker = DocumentTypeMenuPicker(_missionary())
    qtbot.addWidget(picker)

    changes = []
    picker.currentIndexChanged.connect(changes.append)
    picker.setCurrentData("PASSPORT")

    assert picker.currentData() == "PASSPORT"
    assert picker.button.text() == "Passport and Visa"
    assert changes == [picker.findData("PASSPORT")]

    picker.blockSignals(True)
    picker.setCurrentData("OTHER")
    picker.blockSignals(False)
    assert picker.currentData() == "OTHER"
    assert picker.button.text() == "Custom"
    assert len(changes) == 1
