from PySide6.QtWidgets import (
    QFormLayout,
    QDateEdit,
    QLineEdit,
    QTabWidget,
    QTimeEdit,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
)

from ui.foundation import (
    PageHeader,
    create_button,
    create_check_box,
    create_combo_box,
    create_line_edit,
    divider,
    show_message,
)
from PySide6.QtCore import QDate, QTime
from datetime import date, timedelta
from services.email_digest_service import EmailDigestService
from services.scheduler_service import SchedulerService
from services.settings_service import SettingsService
from utils.i18n import tr
from utils.logger import logger


class SettingsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.setObjectName("SettingsPage")
        self.main_window = main_window
        self.settings_service = (
            main_window.settings_service
            if main_window
            else SettingsService()
        )
        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        self.header = PageHeader(
            tr("settings_title"),
            tr("settings_language_hint"),
        )
        outer.addWidget(self.header)

        outer.addWidget(divider())

        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")

        general_tab = QWidget()
        content = QVBoxLayout()
        content.setContentsMargins(32, 24, 32, 24)
        content.setSpacing(16)
        general_tab.setLayout(content)

        self.lang_label = QLabel(tr("settings_language"))
        content.addWidget(self.lang_label)

        self.hint_label = QLabel(tr("settings_language_hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setObjectName("MutedText")
        content.addWidget(self.hint_label)

        self.lang_combo = create_combo_box()
        self.lang_combo.addItem(tr("lang_english"), "en")
        self.lang_combo.addItem(tr("lang_spanish"), "es")

        current = self.settings_service.get_language()
        idx = self.lang_combo.findData(current)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        content.addWidget(self.lang_combo)

        self.storage_label = QLabel(tr("settings_storage_root"))
        content.addWidget(self.storage_label)

        self.storage_hint_label = QLabel(tr("settings_storage_root_hint"))
        self.storage_hint_label.setWordWrap(True)
        self.storage_hint_label.setObjectName("MutedText")
        content.addWidget(self.storage_hint_label)

        storage_row = QHBoxLayout()
        storage_row.setSpacing(8)

        self.storage_input = create_line_edit(
            tr("settings_storage_root"),
            "SettingsStorageInput",
        )
        self.storage_input.setText(
            self.settings_service.get_storage_root()
        )
        storage_row.addWidget(self.storage_input)

        self.browse_btn = create_button(
            tr("settings_browse"),
            "secondary",
        )
        self.browse_btn.clicked.connect(self._browse_storage_root)
        storage_row.addWidget(self.browse_btn)

        content.addLayout(storage_row)

        self.digest_title = QLabel(tr("settings_digest_title"))
        self.digest_title.setObjectName("SectionHeader")
        content.addWidget(self.digest_title)

        self.digest_hint_label = QLabel(tr("settings_digest_hint"))
        self.digest_hint_label.setWordWrap(True)
        self.digest_hint_label.setObjectName("MutedText")
        content.addWidget(self.digest_hint_label)

        digest_settings = self.settings_service.get_daily_digest_settings()

        self.email_enabled_check = create_check_box(
            tr("settings_digest_email_enabled"),
            "DailyDigestEmailEnabled",
        )
        self.email_enabled_check.setChecked(
            digest_settings.get("email_enabled", False)
        )
        content.addWidget(self.email_enabled_check)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)

        self.recipient_input = create_line_edit(
            tr("settings_digest_recipient"),
            "DailyDigestRecipientInput",
        )
        self.recipient_input.setText(
            digest_settings.get("recipient_email", "")
        )
        form.addRow(tr("settings_digest_recipient"), self.recipient_input)

        self.digest_time_input = QTimeEdit()
        self.digest_time_input.setDisplayFormat("HH:mm")
        self.digest_time_input.setFixedHeight(34)
        self.digest_time_input.setTime(
            QTime.fromString(
                digest_settings.get("digest_time", "10:00"),
                "HH:mm",
            )
            if QTime.fromString(
                digest_settings.get("digest_time", "10:00"),
                "HH:mm",
            ).isValid()
            else QTime(10, 0)
        )
        form.addRow(tr("settings_digest_time"), self.digest_time_input)

        self.include_overdue_check = create_check_box(
            tr("settings_digest_include_overdue"),
            "DailyDigestIncludeOverdue",
        )
        self.include_overdue_check.setChecked(
            digest_settings.get("include_overdue", True)
        )
        form.addRow("", self.include_overdue_check)

        self.detail_combo = create_combo_box()
        self.detail_combo.addItem(tr("settings_digest_detail_brief"), "brief")
        self.detail_combo.addItem(
            tr("settings_digest_detail_balanced"),
            "balanced",
        )
        self.detail_combo.addItem(
            tr("settings_digest_detail_detailed"),
            "detailed",
        )
        detail_idx = self.detail_combo.findData(
            digest_settings.get("detail_level", "balanced")
        )
        if detail_idx >= 0:
            self.detail_combo.setCurrentIndex(detail_idx)
        form.addRow(tr("settings_digest_detail"), self.detail_combo)

        self.smtp_host_input = create_line_edit(
            tr("settings_digest_smtp_host"),
            "DailyDigestSmtpHostInput",
        )
        self.smtp_host_input.setText(digest_settings.get("smtp_host", ""))
        form.addRow(tr("settings_digest_smtp_host"), self.smtp_host_input)

        self.smtp_port_input = create_line_edit(
            tr("settings_digest_smtp_port"),
            "DailyDigestSmtpPortInput",
        )
        self.smtp_port_input.setText(str(digest_settings.get("smtp_port", 587)))
        form.addRow(tr("settings_digest_smtp_port"), self.smtp_port_input)

        self.smtp_tls_combo = create_combo_box()
        self.smtp_tls_combo.addItem("STARTTLS", "starttls")
        self.smtp_tls_combo.addItem("SSL/TLS", "ssl")
        self.smtp_tls_combo.addItem(tr("settings_digest_tls_none"), "none")
        tls_idx = self.smtp_tls_combo.findData(
            digest_settings.get("smtp_tls", "starttls")
        )
        if tls_idx >= 0:
            self.smtp_tls_combo.setCurrentIndex(tls_idx)
        form.addRow(tr("settings_digest_tls"), self.smtp_tls_combo)

        self.sender_input = create_line_edit(
            tr("settings_digest_sender"),
            "DailyDigestSenderInput",
        )
        self.sender_input.setText(digest_settings.get("sender_email", ""))
        form.addRow(tr("settings_digest_sender"), self.sender_input)

        self.smtp_username_input = create_line_edit(
            tr("settings_digest_smtp_username"),
            "DailyDigestSmtpUsernameInput",
        )
        self.smtp_username_input.setText(
            digest_settings.get("smtp_username", "")
        )
        form.addRow(
            tr("settings_digest_smtp_username"),
            self.smtp_username_input,
        )

        self.smtp_password_input = create_line_edit(
            tr("settings_digest_smtp_password"),
            "DailyDigestSmtpPasswordInput",
        )
        self.smtp_password_input.setEchoMode(QLineEdit.Password)
        if self.settings_service.get_daily_digest_password():
            self.smtp_password_input.setPlaceholderText(
                tr("settings_digest_password_saved")
            )
        form.addRow(
            tr("settings_digest_smtp_password"),
            self.smtp_password_input,
        )

        content.addLayout(form)

        digest_actions = QHBoxLayout()
        digest_actions.setSpacing(8)
        self.test_email_btn = create_button(
            tr("settings_digest_send_test"),
            "secondary",
        )
        self.test_email_btn.clicked.connect(self._send_test_digest)
        digest_actions.addWidget(self.test_email_btn)

        self.install_task_btn = create_button(
            tr("settings_digest_install_task"),
            "secondary",
        )
        self.install_task_btn.clicked.connect(self._install_digest_task)
        digest_actions.addWidget(self.install_task_btn)
        digest_actions.addStretch()
        content.addLayout(digest_actions)

        self.save_btn = create_button("Save", "primary")
        self.save_btn.clicked.connect(self._save)
        content.addWidget(self.save_btn)

        content.addStretch()
        self.tabs.addTab(general_tab, "General")
        self.tabs.addTab(
            self._build_transfer_tab(),
            "Transfer Management",
        )
        outer.addWidget(self.tabs, stretch=1)

    def _build_transfer_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        tab.setLayout(layout)

        title = QLabel("Transfer Management")
        title.setObjectName("SectionHeader")
        layout.addWidget(title)

        hint = QLabel(
            "Transfers run on a six-week Wednesday cycle. Set the next "
            "transfer Wednesday here so the app can create generic FBI, "
            "flight-planning, and arrival-week reminders."
        )
        hint.setWordWrap(True)
        hint.setObjectName("MutedText")
        layout.addWidget(hint)

        self.transfer_enabled_check = create_check_box(
            "Enable transfer-cycle reminders",
            "TransferRemindersEnabled",
        )
        layout.addWidget(self.transfer_enabled_check)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)

        self.transfer_date_input = QDateEdit()
        self.transfer_date_input.setObjectName("NextTransferDateInput")
        self.transfer_date_input.setCalendarPopup(True)
        self.transfer_date_input.setDisplayFormat("yyyy-MM-dd")
        self.transfer_date_input.setFixedHeight(34)
        form.addRow("Next transfer Wednesday", self.transfer_date_input)
        layout.addLayout(form)

        self.transfer_warning_label = QLabel("")
        self.transfer_warning_label.setObjectName("MutedText")
        self.transfer_warning_label.setWordWrap(True)
        layout.addWidget(self.transfer_warning_label)

        self.transfer_preview_label = QLabel("")
        self.transfer_preview_label.setObjectName("MutedText")
        self.transfer_preview_label.setWordWrap(True)
        layout.addWidget(self.transfer_preview_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.save_transfer_btn = create_button("Save Transfer Settings", "primary")
        self.save_transfer_btn.clicked.connect(self._save_transfer_settings)
        actions.addWidget(self.save_transfer_btn)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()

        self.transfer_enabled_check.toggled.connect(
            self._transfer_enabled_changed
        )
        self.transfer_date_input.dateChanged.connect(
            self._refresh_transfer_preview
        )
        self._load_transfer_settings()
        return tab

    def _save(self):
        lang = self.lang_combo.currentData()
        self.settings_service.set_language(lang)
        self.settings_service.set_storage_root(
            self.storage_input.text().strip()
        )
        self._save_daily_digest_settings()
        if not self._save_transfer_settings(show_saved=False):
            return
        if self.main_window:
            self.main_window.retranslate_ui()
        show_message(
            self,
            tr("settings_title"),
            tr("settings_saved"),
        )

    def _browse_storage_root(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("settings_storage_root"),
            self.storage_input.text(),
        )
        if folder:
            self.storage_input.setText(folder)

    def _daily_digest_values(self):
        return {
            "email_enabled": self.email_enabled_check.isChecked(),
            "recipient_email": self.recipient_input.text().strip(),
            "digest_time": self.digest_time_input.time().toString("HH:mm"),
            "include_overdue": self.include_overdue_check.isChecked(),
            "detail_level": self.detail_combo.currentData(),
            "smtp_host": self.smtp_host_input.text().strip(),
            "smtp_port": self.smtp_port_input.text().strip() or "587",
            "smtp_tls": self.smtp_tls_combo.currentData(),
            "sender_email": self.sender_input.text().strip(),
            "smtp_username": self.smtp_username_input.text().strip(),
        }

    def _save_daily_digest_settings(self):
        self.settings_service.set_daily_digest_settings(
            self._daily_digest_values()
        )
        password = self.smtp_password_input.text()
        if password:
            saved = self.settings_service.set_daily_digest_password(password)
            if not saved:
                show_message(
                    self,
                    tr("settings_digest_title"),
                    tr("settings_digest_password_error"),
                    kind="warning",
                )
            self.smtp_password_input.clear()
            self.smtp_password_input.setPlaceholderText(
                tr("settings_digest_password_saved")
            )

    def _load_transfer_settings(self):
        saved = self.settings_service.get_next_transfer_wednesday()
        self.transfer_enabled_check.setChecked(saved is not None)
        selected = saved or self._next_wednesday(date.today())
        self.transfer_date_input.setDate(
            QDate(selected.year, selected.month, selected.day)
        )
        self._transfer_enabled_changed(saved is not None)
        self._refresh_transfer_preview()

    def _save_transfer_settings(self, show_saved=True):
        if not hasattr(self, "transfer_enabled_check"):
            return True
        if not self.transfer_enabled_check.isChecked():
            self.settings_service.set_next_transfer_wednesday(None)
            self._refresh_transfer_preview()
            if show_saved:
                show_message(
                    self,
                    "Transfer Management",
                    "Transfer-cycle reminders are disabled.",
                )
            return True

        selected = self._qdate_to_date(self.transfer_date_input.date())
        try:
            self.settings_service.set_next_transfer_wednesday(selected)
        except ValueError:
            show_message(
                self,
                "Transfer Management",
                "Please choose a Wednesday for the transfer cycle.",
                kind="warning",
            )
            return False
        self._refresh_transfer_preview()
        if show_saved:
            show_message(
                self,
                "Transfer Management",
                "Transfer settings saved.",
            )
        return True

    def _transfer_enabled_changed(self, enabled):
        self.transfer_date_input.setEnabled(enabled)
        self._refresh_transfer_preview()

    def _refresh_transfer_preview(self):
        if not hasattr(self, "transfer_preview_label"):
            return
        if not self.transfer_enabled_check.isChecked():
            self.transfer_warning_label.setText(
                "Transfer reminders are off. No transfer-cycle tasks will be "
                "generated until this is enabled and saved."
            )
            self.transfer_preview_label.setText("")
            return

        selected = self._qdate_to_date(self.transfer_date_input.date())
        if selected.weekday() != 2:
            self.transfer_warning_label.setText(
                "The selected date is not a Wednesday. Choose a Wednesday "
                "before saving."
            )
            self.transfer_preview_label.setText("")
            return

        self.transfer_warning_label.setText(
            "The app will calculate future transfers every six weeks from "
            "this Wednesday."
        )
        previews = [
            selected + timedelta(days=42 * offset)
            for offset in range(6)
        ]
        self.transfer_preview_label.setText(
            "Upcoming transfer Wednesdays:\n"
            + "\n".join(item.strftime("%b %d, %Y") for item in previews)
        )

    @staticmethod
    def _next_wednesday(today):
        days = (2 - today.weekday()) % 7
        return today + timedelta(days=days)

    @staticmethod
    def _qdate_to_date(value):
        return date(value.year(), value.month(), value.day())

    def _send_test_digest(self):
        self._save_daily_digest_settings()
        try:
            result = EmailDigestService(self.settings_service).send_test_email()
        except Exception:
            logger.exception("Failed to send test daily digest email")
            show_message(
                self,
                tr("settings_digest_title"),
                tr("settings_digest_test_failed"),
                kind="critical",
            )
            return

        if result.get("sent"):
            show_message(
                self,
                tr("settings_digest_title"),
                tr("settings_digest_test_sent"),
            )
            return

        missing = ", ".join(result.get("missing", []))
        show_message(
            self,
            tr("settings_digest_title"),
            tr("settings_digest_missing_settings", missing=missing),
            kind="warning",
        )

    def _install_digest_task(self):
        self._save_daily_digest_settings()
        try:
            SchedulerService().install_daily_digest_task(
                self.digest_time_input.time().toString("HH:mm")
            )
        except Exception as exc:
            logger.exception("Failed to install daily digest scheduled task")
            show_message(
                self,
                tr("settings_digest_title"),
                str(exc) or tr("settings_digest_task_failed"),
                kind="critical",
            )
            return

        show_message(
            self,
            tr("settings_digest_title"),
            tr("settings_digest_task_installed"),
        )

    def retranslate_ui(self):
        self.header.set_title(tr("settings_title"))
        self.header.set_subtitle(tr("settings_language_hint"))
        self.lang_label.setText(tr("settings_language"))
        self.hint_label.setText(tr("settings_language_hint"))
        self.storage_label.setText(tr("settings_storage_root"))
        self.storage_hint_label.setText(tr("settings_storage_root_hint"))
        self.browse_btn.setText(tr("settings_browse"))
        self.digest_title.setText(tr("settings_digest_title"))
        self.digest_hint_label.setText(tr("settings_digest_hint"))
        self.email_enabled_check.setText(tr("settings_digest_email_enabled"))
        self.include_overdue_check.setText(
            tr("settings_digest_include_overdue")
        )
        self.test_email_btn.setText(tr("settings_digest_send_test"))
        self.install_task_btn.setText(tr("settings_digest_install_task"))
        current = self.lang_combo.currentData()
        self.lang_combo.clear()
        self.lang_combo.addItem(tr("lang_english"), "en")
        self.lang_combo.addItem(tr("lang_spanish"), "es")
        idx = self.lang_combo.findData(current)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
