from PySide6.QtWidgets import (
    QFormLayout,
    QLineEdit,
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
from PySide6.QtCore import QTime
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

        content = QVBoxLayout()
        content.setContentsMargins(32, 24, 32, 24)
        content.setSpacing(16)

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
        outer.addLayout(content)

    def _save(self):
        lang = self.lang_combo.currentData()
        self.settings_service.set_language(lang)
        self.settings_service.set_storage_root(
            self.storage_input.text().strip()
        )
        self._save_daily_digest_settings()
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
