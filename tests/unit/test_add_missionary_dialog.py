from types import SimpleNamespace

from config import PASSPORT_COUNTRY_CODES
from ui.dialogs import add_missionary_dialog as dialog_module


class FakeMissionaryService:
    def __init__(self):
        self.calls = []

    def create_missionary(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(full_name=kwargs["full_name"])


def _build_dialog(monkeypatch, qapp):
    fake_service = FakeMissionaryService()
    monkeypatch.setattr(
        dialog_module,
        "MissionaryService",
        lambda: fake_service,
    )

    dialog = dialog_module.AddMissionaryDialog()
    return dialog, fake_service


def _set_combo_text(combo, text):
    if hasattr(combo, "setText"):
        combo.setText(text)
    else:
        combo.setEditText(text)


def test_nationality_uses_locked_passport_country_codes(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    assert dialog.nationality_input.count() == (
        len(PASSPORT_COUNTRY_CODES)
    )
    assert dialog.nationality_input.findData("USA") >= 0
    assert hasattr(dialog.nationality_input, "setCompleter")
    assert dialog.nationality_input.currentIndex() == -1
    assert dialog.nationality_input.currentText() == ""
    assert dialog.nationality_input.placeholderText() == (
        "Type to search passport country codes"
    )


def test_typed_exact_country_code_is_resolved(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    _set_combo_text(dialog.nationality_input, "per")

    assert dialog._selected_nationality() == "PER"


def test_typed_arbitrary_text_is_not_accepted(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    _set_combo_text(dialog.nationality_input, "peru")

    assert dialog._selected_nationality() is None


def test_save_uses_selected_passport_country_code(
    monkeypatch,
    qapp,
):
    dialog, fake_service = _build_dialog(monkeypatch, qapp)

    dialog.full_name_input.setText("Test Missionary")
    dialog.missionary_id_input.setText("12345")
    dialog.passport_input.setText("P1234567")

    idx = dialog.nationality_input.findData("PER")
    assert idx >= 0
    dialog.nationality_input.setCurrentIndex(idx)

    dialog.save_missionary()

    assert len(fake_service.calls) == 1
    assert fake_service.calls[0]["nationality"] == "PER"
    assert fake_service.calls[0]["full_name"] == "Test Missionary"
