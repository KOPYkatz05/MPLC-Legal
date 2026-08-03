from types import SimpleNamespace

import pytest

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
    monkeypatch.setattr(
        dialog_module,
        "show_message",
        lambda _parent, title, content, **_kwargs: pytest.fail(
            f"Unexpected dialog message: {title}: {content}"
        ),
    )

    dialog = dialog_module.AddMissionaryDialog()
    return dialog, fake_service


def _set_combo_text(combo, text):
    if hasattr(combo, "setText"):
        combo.setText(text)
    else:
        combo.setEditText(text)


def _completion_codes_for_prefix(dialog, prefix):
    completer = dialog.nationality_input.completer()
    assert completer is not None
    completer.setCompletionPrefix(prefix)
    model = completer.completionModel()
    return [
        model.data(model.index(i, 0))
        for i in range(model.rowCount())
    ]


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
    assert not hasattr(
        dialog,
        "nationality_country_label",
    )


def test_nationality_dropdown_shows_country_names(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    idx = dialog.nationality_input.findData("USA")
    assert idx >= 0
    if hasattr(dialog.nationality_input, "view"):
        model_index = dialog.nationality_input.view().model().index(idx, 0)
        assert dialog.nationality_input.view().model().data(
            model_index,
            dialog_module.COUNTRY_NAME_ROLE,
        ) == "United States"
        assert dialog.nationality_input.view().model().data(
            model_index,
            dialog_module.Qt.ToolTipRole,
        ) == "USA - United States"
    else:
        assert dialog.nationality_input.itemText(idx) == (
            "USA (United States)"
        )
        assert dialog.nationality_input.itemData(idx) == "USA"

    if dialog_module.FLUENT_DIALOG_AVAILABLE and hasattr(
        dialog.nationality_input,
        "_completerMenu",
    ):
        completer = dialog.nationality_input.completer()
        menu = dialog.nationality_input._completerMenu
        assert isinstance(
            menu,
            dialog_module.CountryCompleterMenu,
        )
        assert completer is not None
        assert menu.setCompletion(
            completer.completionModel(),
            completer.completionColumn(),
        )
        menu_index = next(
            i
            for i in range(menu.view.count())
            if menu.view.item(i).data(
                dialog_module.COUNTRY_CODE_ROLE
            ) == "USA"
        )
        item = menu.view.item(menu_index)
        assert item.text() == ""
        assert item.data(
            dialog_module.COUNTRY_CODE_ROLE,
        ) == "USA"
        assert item.data(
            dialog_module.COUNTRY_NAME_ROLE,
        ) == "United States"
        assert item.data(
            dialog_module.Qt.ToolTipRole,
        ) == "USA - United States"
        row_widget = menu.view.itemWidget(item)
        assert row_widget is not None
        assert row_widget.objectName() == "CountryCompletionRow"
        assert row_widget.findChild(
            dialog_module.QLabel,
            "CountryCompletionCode",
        ).text() == "USA"
        assert row_widget.findChild(
            dialog_module.QLabel,
            "CountryCompletionName",
        ).text() == "United States"


@pytest.mark.parametrize(
    ("code", "expected_name"),
    [
        ("SGP", "Singapore"),
        ("SHN", "Saint Helena"),
        ("SJM", "Svalbard and Jan Mayen Islands"),
        ("SLB", "Solomon Islands"),
        ("SLE", "Sierra Leone"),
        ("SLV", "El Salvador"),
        ("SMR", "San Marino"),
        ("SOM", "Somalia"),
        ("SPM", "Saint Pierre and Miquelon"),
        ("SRB", "Serbia"),
    ],
)
def test_nationality_dropdown_includes_all_country_names(
    monkeypatch,
    qapp,
    code,
    expected_name,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    idx = dialog.nationality_input.findData(code)
    assert idx >= 0
    assert dialog_module.COUNTRY_NAMES_BY_CODE[code] == expected_name

    if hasattr(dialog.nationality_input, "view"):
        model_index = dialog.nationality_input.view().model().index(idx, 0)
        assert dialog.nationality_input.view().model().data(
            model_index,
            dialog_module.COUNTRY_NAME_ROLE,
        ) == expected_name
        assert dialog.nationality_input.view().model().data(
            model_index,
            dialog_module.Qt.ToolTipRole,
        ) == f"{code} - {expected_name}"
    else:
        assert expected_name in dialog.nationality_input.itemText(idx)


def test_typed_exact_country_code_is_resolved(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    _set_combo_text(dialog.nationality_input, "per")

    assert dialog._selected_nationality() == "Peru"


def test_typed_country_name_is_accepted(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    _set_combo_text(dialog.nationality_input, "peru")

    assert dialog._selected_nationality() == "Peru"


@pytest.mark.parametrize(
    ("prefix", "expected_codes"),
    [
        ("u", ["AUS", "AUT", "BMU", "CUB", "CUW", "DEU", "ECU", "GUF", "GUM", "GUY"]),
        ("us", ["AUS", "MUS", "RUS", "USA"]),
        ("s", ["ASM", "AUS", "BES", "BHS", "ESH", "ESP", "EST", "FSM", "ISL", "ISR"]),
    ],
)
def test_nationality_completer_matches_expected_prefixes(
    monkeypatch,
    qapp,
    prefix,
    expected_codes,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    codes = _completion_codes_for_prefix(dialog, prefix)

    assert codes[: len(expected_codes)] == expected_codes
    assert len(codes) >= len(expected_codes)


def test_nationality_completer_no_match_prefix(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    codes = _completion_codes_for_prefix(dialog, "zzz")

    assert codes == []


def test_nationality_popup_smoke_single_letter(
    monkeypatch,
    qapp,
):
    dialog, _ = _build_dialog(monkeypatch, qapp)

    _set_combo_text(dialog.nationality_input, "u")
    dialog.nationality_input._showCompleterMenu()

    assert dialog.nationality_input.text() == "u"


def test_save_uses_selected_country_name(
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
    assert fake_service.calls[0]["nationality"] == "Peru"
    assert fake_service.calls[0]["full_name"] == "Test Missionary"
