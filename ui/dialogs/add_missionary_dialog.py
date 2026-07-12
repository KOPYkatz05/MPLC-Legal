import json

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCompleter,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from config import PASSPORT_COUNTRY_CODES
from services.missionary_service import (
    MissionaryCodeError,
    MissionaryService,
)
from ui.foundation import (
    setup_dialog_shell,
    DialogFooter,
    create_button,
    create_combo_box,
    create_date_picker,
    create_line_edit,
    show_message,
)

from utils.logger import logger
from utils.runtime_paths import resource_path

try:
    from qfluentwidgets import (
        BodyLabel,
        MaskDialogBase,
        SubtitleLabel,
    )
    from qfluentwidgets.components.widgets.line_edit import (
        CompleterMenu as FluentCompleterMenu,
    )
    from qfluentwidgets.components.widgets.menu import MenuAnimationType, RoundMenu
    from qfluentwidgets.common.style_sheet import updateDynamicStyle

    FLUENT_DIALOG_AVAILABLE = True
except Exception:
    BodyLabel = QLabel
    SubtitleLabel = QLabel
    MaskDialogBase = QDialog
    FluentCompleterMenu = None
    MenuAnimationType = None
    RoundMenu = QDialog
    updateDynamicStyle = None
    FLUENT_DIALOG_AVAILABLE = False


def _load_country_names_by_code():
    data_path = resource_path("data", "country_names_by_code.json")

    names = {}

    if data_path.exists():
        try:
            with data_path.open("r", encoding="utf-8") as f:
                names = json.load(f)
        except Exception:
            names = {}

    # Keep the labels a little friendlier where the ISO short names are
    # overly formal.
    names.update(
        {
            "GBR": "United Kingdom",
            "KOR": "South Korea",
            "SGS": "South Georgia and the South Sandwich Islands",
            "SLV": "El Salvador",
            "USA": "United States",
        }
    )

    return {
        code: name
        for code, name in names.items()
        if code in PASSPORT_COUNTRY_CODES
    }


COUNTRY_NAMES_BY_CODE = _load_country_names_by_code()
COUNTRY_NAME_ROLE = Qt.UserRole + 1
COUNTRY_CODE_ROLE = Qt.UserRole + 2


def _country_dropdown_text(code):
    country_name = COUNTRY_NAMES_BY_CODE.get(code)
    if not country_name:
        return code

    return f"{code} ({country_name})"


def _build_country_completer_model(parent=None):
    model = QStandardItemModel(parent)

    for code in PASSPORT_COUNTRY_CODES:
        item = QStandardItem(code)
        country_name = COUNTRY_NAMES_BY_CODE.get(code, "")
        if country_name:
            item.setData(country_name, COUNTRY_NAME_ROLE)
            item.setData(f"{code} - {country_name}", Qt.ToolTipRole)
        else:
            item.setData(code, Qt.ToolTipRole)

        model.appendRow(item)

    logger.info(
        "Built nationality completer model with %d country code(s)",
        model.rowCount(),
    )
    return model


def _build_country_completion_row(code, country_name, parent=None):
    row = QWidget(parent)
    row.setObjectName("CountryCompletionRow")
    row.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    row.setAutoFillBackground(False)

    layout = QHBoxLayout()
    layout.setContentsMargins(12, 0, 12, 0)
    layout.setSpacing(8)
    row.setLayout(layout)

    code_label = QLabel(code)
    code_label.setObjectName("CountryCompletionCode")
    code_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    code_font = code_label.font()
    code_font.setBold(True)
    code_label.setFont(code_font)

    country_label = QLabel(country_name)
    country_label.setObjectName("CountryCompletionName")
    country_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    layout.addWidget(code_label, 0, Qt.AlignVCenter)
    layout.addWidget(country_label, 1, Qt.AlignVCenter)
    row.setFixedHeight(33)

    return row


if FLUENT_DIALOG_AVAILABLE:
    class CountryCompleterMenu(FluentCompleterMenu):
        def __init__(self, lineEdit):
            super().__init__(lineEdit)
            logger.info("Initialized nationality completer menu")

        def popup(self):
            """Show the completer menu using the normal qfluentwidgets flow."""
            try:
                if not self.items:
                    logger.info(
                        "Nationality completer popup skipped because there are no items"
                    )
                    return self.close()

                p = self.lineEdit
                visible_preview = ", ".join(
                    self.items[:5]
                )
                logger.info(
                    "Nationality completer popup opening for prefix=%r with %d item(s); preview=%s",
                    p.text(),
                    len(self.items),
                    visible_preview,
                )

                if self.view.width() < p.width():
                    self.view.setMinimumWidth(p.width())
                    self.adjustSize()

                x = -self.width() // 2 + self.layout().contentsMargins().left() + p.width() // 2
                y = p.height() - self.layout().contentsMargins().top() + 2
                pd = p.mapToGlobal(QPoint(x, y))
                hd = self.view.heightForAnimation(
                    pd,
                    MenuAnimationType.FADE_IN_DROP_DOWN,
                )

                pu = p.mapToGlobal(QPoint(x, 7))
                hu = self.view.heightForAnimation(
                    pu,
                    MenuAnimationType.FADE_IN_PULL_UP,
                )

                if hd >= hu:
                    pos = pd
                    aniType = MenuAnimationType.FADE_IN_DROP_DOWN
                else:
                    pos = pu
                    aniType = MenuAnimationType.FADE_IN_PULL_UP

                self.view.adjustSize(pos, aniType)
                self.view.setProperty(
                    "dropDown",
                    aniType == MenuAnimationType.FADE_IN_DROP_DOWN,
                )

                if updateDynamicStyle is not None:
                    updateDynamicStyle(self.view)

                self.adjustSize()
                RoundMenu.exec(self, pos, True, aniType)

                self.view.setFocusPolicy(Qt.NoFocus)
                self.setFocusPolicy(Qt.NoFocus)
                p.setFocus()
            except Exception:
                logger.exception(
                    "Nationality completer popup failed"
                )
                try:
                    self.close()
                except Exception:
                    logger.exception(
                        "Failed to close nationality completer popup after error"
                    )

        def setCompletion(self, model, column=0):
            try:
                items = []
                self.indexes.clear()
                prefix = ""
                if hasattr(self.lineEdit, "text"):
                    try:
                        prefix = self.lineEdit.text()
                    except Exception:
                        prefix = ""

                for i in range(model.rowCount()):
                    index = model.index(i, column)
                    code = model.data(index, Qt.DisplayRole) or ""
                    country_name = model.data(index, COUNTRY_NAME_ROLE) or ""
                    items.append(code)
                    self.indexes.append(index)

                logger.info(
                    "Nationality completer rebuilt for prefix=%r with %d item(s)",
                    prefix,
                    len(items),
                )
                if items:
                    logger.info(
                        "Nationality completer visible items for prefix=%r: %s",
                        prefix,
                        ", ".join(items[:10]),
                    )
                else:
                    logger.info(
                        "Nationality completer has no visible items for prefix=%r",
                        prefix,
                    )

                if self.items == items and self.isVisible():
                    return False

                self.view.clear()
                self.items = items
                self.view.addItems(items)

                for i, code in enumerate(items):
                    item = self.view.item(i)
                    if item is None:
                        continue
                    # The visible text is provided by the row widget below.
                    # Keeping QListWidgetItem text visible causes qfluentwidgets
                    # to paint a second copy underneath the widget row.
                    item.setText("")
                    item.setData(COUNTRY_CODE_ROLE, code)
                    country_name = self.indexes[i].data(COUNTRY_NAME_ROLE) or ""
                    if country_name:
                        item.setData(COUNTRY_NAME_ROLE, country_name)
                        item.setData(
                            Qt.ToolTipRole,
                            f"{code} - {country_name}",
                        )
                    else:
                        item.setData(Qt.ToolTipRole, code)
                    item.setSizeHint(QSize(1, self.itemHeight))
                    row = _build_country_completion_row(
                        code,
                        country_name,
                        self.view,
                    )
                    self.view.setItemWidget(item, row)

                return True
            except Exception:
                logger.exception(
                    "Nationality completer setCompletion failed"
                )
                return False

        def _onCompletionItemSelected(self, text, row):
            if 0 <= row < len(self.indexes):
                code = self.indexes[row].data(Qt.DisplayRole) or text
            else:
                code = text

            logger.info(
                "Nationality completer item selected: row=%s code=%r text=%r",
                row,
                code,
                text,
            )

            self.lineEdit.setText(code)
            self.activated.emit(code)

            if 0 <= row < len(self.indexes):
                self.indexActivated.emit(self.indexes[row])


class AddMissionaryDialog(MaskDialogBase):
    def __init__(self, parent=None):
        if FLUENT_DIALOG_AVAILABLE and parent is None:
            QDialog.__init__(self, parent)
            self._using_plain_dialog_shell = True
        else:
            super().__init__(parent)
            self._using_plain_dialog_shell = False

        self.missionary_service = (
            MissionaryService()
        )

        self.setWindowTitle(
            "Add Missionary"
        )

        self.surface = setup_dialog_shell(
            self,
            surface_width=520,
        )

        logger.info(
            "Opened Add Missionary dialog"
        )

        self.setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self.missionary_id_input.setFocus()

    def done(self, code):
        if (
            FLUENT_DIALOG_AVAILABLE
            and not getattr(self, "_using_plain_dialog_shell", False)
        ):
            super().done(code)
        else:
            QDialog.done(self, code)

    def _onDone(self, code):
        if (
            FLUENT_DIALOG_AVAILABLE
            and not getattr(self, "_using_plain_dialog_shell", False)
        ):
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def setup_ui(self):
        surface = self.surface

        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        surface.setLayout(layout)

        layout.addWidget(
            self._build_header()
        )

        layout.addWidget(
            self._build_form_body()
        )

        layout.addWidget(
            self._build_footer()
        )

    def _build_header(self):
        header = QFrame()
        header.setObjectName(
            "AddMissionaryHeader"
        )
        header.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(
            18, 16, 18, 12
        )
        layout.setSpacing(4)
        header.setLayout(layout)

        title = SubtitleLabel(
            "Add Missionary"
        )
        title.setObjectName("AddMissionaryTitle")

        subtitle = BodyLabel(
            "Create the missionary record now, "
            "then let document uploads fill in "
            "the rest later."
        )
        subtitle.setObjectName("AddMissionarySubtitle")
        subtitle.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)

        return header

    def _build_form_body(self):
        body = QWidget()
        body.setObjectName("AddMissionaryBody")
        body.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(
            18, 16, 18, 16
        )
        layout.setSpacing(12)
        body.setLayout(layout)

        self.missionary_id_input = create_line_edit(
            "Enter numeric missionary ID",
            "AddMissionaryInput",
        )

        self.missionary_id_input.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"\d*"),
                self.missionary_id_input,
            )
        )

        self.full_name_input = create_line_edit(
            "Enter full legal name",
            "AddMissionaryInput",
        )

        self.nationality_input = create_combo_box(
            "AddMissionaryCombo",
            editable=True,
        )
        self.nationality_input.setPlaceholderText(
            "Type to search passport country codes"
        )

        use_fluent_completer_menu = (
            FLUENT_DIALOG_AVAILABLE
            and hasattr(
                self.nationality_input,
                "setCompleterMenu",
            )
        )

        nationality_model = _build_country_completer_model(
            self.nationality_input
        )
        logger.info(
            "Nationality input completer model created with %d row(s)",
            nationality_model.rowCount(),
        )
        nationality_completer = QCompleter(
            nationality_model,
            self.nationality_input,
        )
        nationality_completer.setCaseSensitivity(
            Qt.CaseInsensitive
        )
        nationality_completer.setFilterMode(
            Qt.MatchContains
        )
        nationality_completer.setCompletionMode(
            QCompleter.PopupCompletion
        )
        self.nationality_input.setCompleter(
            nationality_completer
        )
        logger.info(
            "Nationality completer configured: caseInsensitive=%s, contains=%s, popupCompletion=%s",
            True,
            True,
            True,
        )

        if use_fluent_completer_menu:
            logger.info(
                "Nationality input using Fluent completer menu for popup rendering"
            )

        if use_fluent_completer_menu:
            self.nationality_input.setCompleterMenu(
                CountryCompleterMenu(
                    self.nationality_input
                )
            )
            logger.info(
                "Nationality completer menu installed for fluent combo box"
            )

        has_popup_model = (
            hasattr(self.nationality_input, "view")
            and hasattr(self.nationality_input.view(), "model")
        )
        nationality_model_ref = (
            self.nationality_input.view().model()
            if has_popup_model
            else None
        )

        for code in PASSPORT_COUNTRY_CODES:
            display_text = (
                code
                if has_popup_model
                else _country_dropdown_text(code)
            )
            self.nationality_input.addItem(
                display_text,
                code,
            )
            index = self.nationality_input.count() - 1
            country_name = COUNTRY_NAMES_BY_CODE.get(code, "")
            if nationality_model_ref is not None:
                model_index = nationality_model_ref.index(index, 0)
                if country_name:
                    nationality_model_ref.setData(
                        model_index,
                        country_name,
                        COUNTRY_NAME_ROLE,
                    )
                    nationality_model_ref.setData(
                        model_index,
                        f"{code} - {country_name}",
                        Qt.ToolTipRole,
                    )
                else:
                    nationality_model_ref.setData(
                        model_index,
                        code,
                        Qt.ToolTipRole,
                    )
        if not has_popup_model and hasattr(
            self.nationality_input,
            "currentIndexChanged",
        ):
            self.nationality_input.currentIndexChanged.connect(
                self._sync_nationality_edit_text
            )

        if hasattr(self.nationality_input, "setCurrentIndex"):
            self.nationality_input.setCurrentIndex(-1)

        self.passport_input = create_line_edit(
            "Passport number",
            "AddMissionaryInput",
        )

        self.arrival_date_input = (
            create_date_picker(
                "AddMissionaryDatePicker"
            )
        )

        layout.addWidget(
            self._build_field(
                "Missionary ID",
                self.missionary_id_input,
            )
        )

        layout.addWidget(
            self._build_field(
                "Full Name",
                self.full_name_input,
            )
        )

        layout.addWidget(
            self._build_field(
                "Nationality",
                self.nationality_input,
            )
        )

        layout.addWidget(
            self._build_field(
                "Passport Number",
                self.passport_input,
            )
        )

        layout.addWidget(
            self._build_field(
                "Arrival Date",
                self.arrival_date_input,
                (
                    "Use the arrival date only. "
                    "It should be the date the missionary arrived in "
                    "the country, not the date they came to the mission. "
                ),
            )
        )

        return body

    def _build_field(
        self,
        label_text,
        control,
        hint_text="",
    ):
        container = QWidget()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        container.setLayout(layout)

        label = QLabel(label_text)
        label.setObjectName(
            "AddMissionaryFieldLabel"
        )

        layout.addWidget(label)
        layout.addWidget(control)

        if hint_text:
            hint = QLabel(hint_text)
            hint.setObjectName(
                "AddMissionaryHint"
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

        return container

    def _sync_nationality_edit_text(self, index):
        code = self.nationality_input.itemData(index)
        if code in PASSPORT_COUNTRY_CODES:
            self.nationality_input.setText(code)

    def _build_footer(self):
        footer = DialogFooter()
        footer.setObjectName("AddMissionaryFooter")

        self.cancel_button = create_button(
            "Cancel",
            "secondary",
        )

        self.save_button = create_button(
            "Save Missionary",
            "primary",
        )

        self.cancel_button.clicked.connect(
            self.reject
        )

        self.save_button.clicked.connect(
            self.save_missionary
        )

        footer.add_action(
            self.cancel_button
        )

        footer.add_action(
            self.save_button
        )

        return footer

    def _selected_arrival_date(self):
        if hasattr(
            self.arrival_date_input,
            "getDate",
        ):
            return (
                self.arrival_date_input
                .getDate()
                .toPython()
            )

        return (
            self.arrival_date_input
            .date()
            .toPython()
        )

    def _selected_nationality(self):
        nationality = self.nationality_input.currentData()
        if nationality in PASSPORT_COUNTRY_CODES:
            return nationality

        typed = (
            self.nationality_input.currentText()
            .strip()
            .upper()
        )

        if typed in PASSPORT_COUNTRY_CODES:
            return typed

        return None

    def save_missionary(self):
        try:
            full_name = (
                self.full_name_input.text()
                .strip()
            )

            if not full_name:
                logger.warning(
                    "Attempted to create "
                    "missionary without "
                    "full name"
                )

                show_message(
                    self,
                    "Error",
                    "Full name is required.",
                    kind="warning",
                )

                return

            missionary = (
                self.missionary_service
                .create_missionary(
                    full_name=full_name,

                    missionary_code=(
                        self.missionary_id_input
                        .text()
                        .strip()
                    ),

                    nationality=self._selected_nationality(),

                    passport_number=(
                        self.passport_input
                        .text()
                        .strip()
                    ),

                    arrival_date=(
                        self._selected_arrival_date()
                    ),
                )
            )

            logger.info(
                f"Successfully created "
                f"missionary from dialog: "
                f"{missionary.full_name}"
            )

            self.accept()

        except MissionaryCodeError as exc:
            logger.warning(
                f"Invalid missionary ID: {exc}"
            )

            show_message(
                self,
                "Invalid Missionary ID",
                str(exc),
                kind="warning",
            )

        except Exception:
            logger.exception(
                "Failed to save missionary "
                "from AddMissionaryDialog"
            )

            show_message(
                self,
                "Error",
                (
                    "An unexpected error "
                    "occurred while saving "
                    "the missionary."
                ),
                kind="critical",
            )
