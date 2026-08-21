from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QRegularExpression, QTimer
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
    AppDialog,
    GuidanceButton,
    create_button,
    create_combo_box,
    create_date_picker,
    create_guidance_button,
    create_line_edit,
    show_message,
)

from utils.logger import logger
from utils.nationalities import (
    COUNTRY_NAMES_BY_CODE,
    country_code,
    normalize_nationality,
)
from utils.passport_numbers import normalize_passport_number

try:
    from qfluentwidgets.components.widgets.line_edit import (
        CompleterMenu as FluentCompleterMenu,
    )
    from qfluentwidgets.components.widgets.menu import MenuAnimationType, RoundMenu
    from qfluentwidgets.common.style_sheet import updateDynamicStyle

    FLUENT_DIALOG_AVAILABLE = True
except Exception:
    FluentCompleterMenu = None
    MenuAnimationType = None
    RoundMenu = QDialog
    updateDynamicStyle = None
    FLUENT_DIALOG_AVAILABLE = False


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


class AddMissionaryDialog(AppDialog):
    def __init__(self, parent=None):
        self.missionary_service = (
            MissionaryService()
        )

        super().__init__(
            parent,
            title="Add Missionary",
            subtitle=(
                "Create the missionary record now, "
                "then let document uploads fill in "
                "the rest later."
            ),
            width=520,
            # QGraphicsDropShadowEffect caches the complete child surface on
            # Windows. This form changes shape when Peru is selected, and the
            # cached frame can leave duplicated controls behind.
            shadow=False,
        )
        # Keep the reusable AppDialog surface while allowing the form to have
        # the same purpose-specific hierarchy as the rest of Mission Legal.
        self.surface.setProperty("dialogVariant", "addMissionary")

        logger.info(
            "Opened Add Missionary dialog"
        )

        self.setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self.missionary_id_input.setFocus()

    def setup_ui(self):
        self.header.setObjectName("AddMissionaryHeader")
        title = self.header.findChild(QLabel, "AppDialogTitle")
        subtitle = self.header.findChild(QLabel, "AppDialogSubtitle")
        if title is not None:
            title.setObjectName("AddMissionaryTitle")
        if subtitle is not None:
            subtitle.setObjectName("AddMissionarySubtitle")

        self.body.setObjectName("AddMissionaryBody")
        self.body_layout.setContentsMargins(
            18, 16, 18, 16
        )
        self.body_layout.setSpacing(12)
        self.body_layout.setAlignment(Qt.AlignTop)
        self.footer.setObjectName("AddMissionaryFooter")

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

        self._nationality_ui_timer = QTimer(self)
        self._nationality_ui_timer.setSingleShot(True)
        self._nationality_ui_timer.setInterval(80)
        self._nationality_ui_timer.timeout.connect(
            self._update_nationality_dependent_fields
        )
        self._peruvian_fields_hidden = None

        nationality_changed = getattr(
            self.nationality_input,
            "currentTextChanged",
            None,
        )
        if nationality_changed is not None:
            nationality_changed.connect(
                self._schedule_nationality_field_update
            )
        nationality_index_changed = getattr(
            self.nationality_input,
            "currentIndexChanged",
            None,
        )
        if nationality_index_changed is not None:
            nationality_index_changed.connect(
                self._schedule_nationality_field_update
            )

        self.passport_input = create_line_edit(
            "Passport number",
            "AddMissionaryInput",
        )
        self.passport_input.textChanged.connect(
            self._normalize_passport_input
        )

        self.arrival_date_input = (
            create_date_picker(
                "AddMissionaryDatePicker"
            )
        )

        self.body_layout.addWidget(
            self._build_section_label("Identity")
        )

        self.body_layout.addWidget(
            self._build_field(
                "Missionary ID",
                self.missionary_id_input,
            )
        )

        self.body_layout.addWidget(
            self._build_field(
                "Full Name",
                self.full_name_input,
            )
        )

        self.body_layout.addWidget(
            self._build_field(
                "Nationality",
                self.nationality_input,
            )
        )

        self.passport_field = self._build_field(
            "Passport Number",
            self.passport_input,
        )
        self.body_layout.addWidget(self.passport_field)

        self.mission_history_label = self._build_section_label(
            "Mission history"
        )
        self.body_layout.addWidget(self.mission_history_label)

        self.arrival_date_field = self._build_field(
            "Original Entry Date",
            self.arrival_date_input,
            guidance_text=(
                "Use the date the missionary first arrived in the country, "
                "not the date they came to the mission."
            ),
            guidance_title="Original entry date",
        )
        self.body_layout.addWidget(self.arrival_date_field)

        self._update_nationality_dependent_fields()

        self._build_footer()

    @staticmethod
    def _build_section_label(text):
        label = QLabel(text)
        label.setObjectName("AddMissionarySectionLabel")
        return label

    def _build_field(
        self,
        label_text,
        control,
        hint_text="",
        guidance_text="",
        guidance_title="",
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

        if guidance_text:
            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(4)
            label_row.addWidget(label)
            help_button = create_guidance_button(
                guidance_text,
                title=guidance_title or label_text,
                parent=container,
            )
            label_row.addWidget(help_button)
            label_row.addStretch()
            layout.addLayout(label_row)
        else:
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
            self.nationality_input.setText(normalize_nationality(code))

    def _build_footer(self):
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

        self.footer.add_action(
            self.cancel_button
        )

        self.footer.add_action(
            self.save_button
        )

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

    def _normalize_passport_input(self, value):
        normalized = normalize_passport_number(value)
        if normalized != value:
            self.passport_input.setText(normalized)

    def _selected_nationality(self):
        typed = (
            self.nationality_input.currentText()
            .strip()
            .upper()
        )

        if typed:
            if country_code(typed):
                return normalize_nationality(typed)
            # An editable combo can retain the previous row's data while its
            # text is being replaced. Do not treat that stale data as the
            # user's current country.
            return None

        nationality = self.nationality_input.currentData()
        if nationality in PASSPORT_COUNTRY_CODES:
            return normalize_nationality(nationality)

        return None

    def _is_peruvian_nationality(self):
        return country_code(self._selected_nationality()) == "PER"

    def _schedule_nationality_field_update(self, *_args):
        """Coalesce the editable combo's intermediate change signals."""
        self._nationality_ui_timer.start()

    def _update_nationality_dependent_fields(self, *_args):
        """Keep Peru's DNI-only record path free of foreign requirements."""
        is_peruvian = self._is_peruvian_nationality()
        if self._peruvian_fields_hidden == is_peruvian:
            return

        self._peruvian_fields_hidden = is_peruvian
        self.passport_field.setVisible(not is_peruvian)
        self.mission_history_label.setVisible(not is_peruvian)
        self.arrival_date_field.setVisible(not is_peruvian)

        # Let Qt complete the layout normally. Temporarily disabling painting
        # here left stale source pixmaps inside the dialog's shadow effect,
        # which looked like duplicated controls at arbitrary positions.
        self.body_layout.activate()
        self.body.updateGeometry()
        self.surface.layout().activate()
        self.surface.updateGeometry()
        self.surface_container.update()

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

            nationality = self._selected_nationality()
            is_peruvian = country_code(nationality) == "PER"

            missionary = (
                self.missionary_service
                .create_missionary(
                    full_name=full_name,

                    missionary_code=(
                        self.missionary_id_input
                        .text()
                        .strip()
                    ),

                    nationality=nationality,

                    passport_number=(
                        None
                        if is_peruvian
                        else self.passport_input.text().strip()
                    ),

                    arrival_date=(
                        None
                        if is_peruvian
                        else self._selected_arrival_date()
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
