from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsBlurEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.missionary_service import (
    MissionaryService,
)
from ui.foundation import (
    DialogFooter,
    create_button,
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

        self._blur_target = (
            self._resolve_blur_target(parent)
        )

        self._blur_effect = None
        self._applied_blur = False

        self.setWindowTitle(
            "Add Missionary"
        )

        if FLUENT_DIALOG_AVAILABLE:
            self._configure_fluent_shell()
        else:
            self.setModal(True)
            self.setMinimumWidth(520)

        logger.info(
            "Opened Add Missionary dialog"
        )

        self.setup_ui()

    def _configure_fluent_shell(self):
        self.setMaskColor(
            QColor(74, 80, 90, 84)
        )

        self.setShadowEffect(
            70,
            (0, 16),
            QColor(15, 23, 42, 90),
        )

        self._hBoxLayout.setContentsMargins(
            24, 24, 24, 24
        )

        self._hBoxLayout.removeWidget(
            self.widget
        )

        self._hBoxLayout.addWidget(
            self.widget,
            1,
            Qt.AlignCenter,
        )

        self.widget.setObjectName(
            "AddMissionarySurface"
        )

        self.widget.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        self.widget.setFixedWidth(520)

    def _resolve_blur_target(self, parent):
        if not parent:
            return None

        window = parent.window()
        if window and window is not parent:
            central_widget_getter = getattr(
                window,
                "centralWidget",
                None,
            )

            if callable(central_widget_getter):
                central_widget = (
                    central_widget_getter()
                )

                if central_widget:
                    return central_widget

        central_widget_getter = getattr(
            parent,
            "centralWidget",
            None,
        )

        if callable(central_widget_getter):
            central_widget = (
                central_widget_getter()
            )

            if central_widget:
                return central_widget

        return parent

    def _apply_backdrop_effect(self):
        if not self._blur_target:
            return

        if self._blur_target.graphicsEffect():
            return

        self._blur_effect = (
            QGraphicsBlurEffect(self)
        )

        self._blur_effect.setBlurRadius(10)

        self._blur_target.setGraphicsEffect(
            self._blur_effect
        )

        self._applied_blur = True

    def _clear_backdrop_effect(self):
        if (
            not self._applied_blur
            or not self._blur_target
        ):
            return

        if (
            self._blur_target.graphicsEffect()
            is self._blur_effect
        ):
            self._blur_target.setGraphicsEffect(
                None
            )

        self._blur_effect = None
        self._applied_blur = False

    def showEvent(self, event):
        self._apply_backdrop_effect()
        super().showEvent(event)
        self.full_name_input.setFocus()

    def closeEvent(self, event):
        self._clear_backdrop_effect()
        super().closeEvent(event)

    def _onDone(self, code):
        self._clear_backdrop_effect()

        if FLUENT_DIALOG_AVAILABLE:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def setup_ui(self):
        surface = (
            self.widget
            if FLUENT_DIALOG_AVAILABLE
            else self
        )

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

        self.full_name_input = create_line_edit(
            "Enter full legal name",
            "AddMissionaryInput",
        )

        self.nationality_input = create_line_edit(
            "Country of citizenship",
            "AddMissionaryInput",
        )

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
                    "Visa expiration will be added "
                    "later from uploaded documents."
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

                    nationality=(
                        self.nationality_input
                        .text()
                        .strip()
                    ),

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
