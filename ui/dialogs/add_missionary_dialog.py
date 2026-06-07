from PySide6.QtCore import Qt, QRegularExpression, QStringListModel
from PySide6.QtGui import QColor, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCompleter,
    QDialog,
    QFrame,
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

try:
    from qfluentwidgets import (
        BodyLabel,
        MaskDialogBase,
        SubtitleLabel,
    )

    FLUENT_DIALOG_AVAILABLE = True
except Exception:
    BodyLabel = QLabel
    SubtitleLabel = QLabel
    MaskDialogBase = QDialog
    FLUENT_DIALOG_AVAILABLE = False


class AddMissionaryDialog(MaskDialogBase):
    def __init__(self, parent=None):
        super().__init__(parent)

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

    def _onDone(self, code):
        if FLUENT_DIALOG_AVAILABLE:
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
            28, 26, 28, 18
        )
        layout.setSpacing(6)
        header.setLayout(layout)

        title = SubtitleLabel(
            "Add Missionary"
        )
        title.setObjectName("PageTitle")

        subtitle = BodyLabel(
            "Create the missionary record now, "
            "then let document uploads fill in "
            "the rest later."
        )
        subtitle.setObjectName("PageSubtitle")
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
            28, 10, 28, 22
        )
        layout.setSpacing(16)
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

        nationality_model = QStringListModel(
            list(PASSPORT_COUNTRY_CODES),
            self.nationality_input,
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
        for code in PASSPORT_COUNTRY_CODES:
            self.nationality_input.addItem(
                code,
                code,
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

    def _build_footer(self):
        footer = DialogFooter()

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
