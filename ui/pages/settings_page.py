from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QGridLayout,
    QLineEdit,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFileDialog,
)

from ui.foundation import (
    create_button,
    create_check_box,
    create_combo_box,
    create_date_picker,
    create_line_edit,
    create_list_widget,
    create_scroll_area,
    show_message,
)
from PySide6.QtCore import QDate, Qt, QTime
from datetime import date, timedelta
from types import SimpleNamespace
from services.email_digest_service import EmailDigestService
from services.scheduler_service import SchedulerService
from services.settings_service import SettingsService
from services.api_client import MissionLegalApiClient
from services.workspace_service import (
    WorkspaceService,
    new_block,
    new_workspace,
)
from services.workspace_layout import (
    WORKSPACE_GRID_COLUMNS,
    normalize_workspace_layout,
    validate_block_layout,
)
from ui.dialogs.missionary_workspace_dialog import (
    BLOCK_LABELS,
    FIELD_KEYS,
    MissionaryWorkspaceDialog,
    WorkspaceBlockFactory,
    clear_layout,
)
from ui.widgets.workspace_layout_editor import WorkspaceLayoutEditor
from utils.constants import DOCUMENTS
from utils.language_helper import ui_text as tr
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
        self.api_client = MissionLegalApiClient.from_environment()
        self.workspace_service = (
            getattr(main_window, "workspace_service", None)
            if main_window
            else None
        ) or WorkspaceService()
        self._workspaces = []
        self._selected_workspace_id = None
        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        outer.addWidget(self._build_top_bar())

        workspace = QWidget()
        workspace.setObjectName("SettingsWorkspace")
        workspace.setAttribute(Qt.WA_StyledBackground, True)
        workspace_layout = QVBoxLayout()
        workspace_layout.setContentsMargins(12, 12, 24, 24)
        workspace_layout.setSpacing(0)
        workspace.setLayout(workspace_layout)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")

        self.tabs.addTab(self._build_general_tab(), tr("settings_tab_general"))
        self.tabs.addTab(
            self._build_notifications_tab(),
            tr("settings_tab_notifications"),
        )
        self.tabs.addTab(self._build_transfer_tab(), tr("settings_tab_transfer"))
        workspace_layout.addWidget(self.tabs, stretch=1)
        outer.addWidget(workspace, stretch=1)

    def _build_top_bar(self):
        top_bar = QFrame()
        top_bar.setObjectName("SettingsTopBar")
        top_bar.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 16, 0)
        layout.setSpacing(0)
        top_bar.setLayout(layout)

        tabs = QFrame()
        tabs.setObjectName("SettingsTopTabStrip")
        tabs.setAttribute(Qt.WA_StyledBackground, True)
        tabs_layout = QHBoxLayout()
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(0)
        tabs.setLayout(tabs_layout)

        self.settings_top_tab_labels = {}
        for key, active in [
            ("settings_top_tab_main", True),
            ("settings_top_tab_notifications", False),
            ("settings_top_tab_workspaces", False),
            ("settings_top_tab_calendar", False),
            ("settings_top_tab_analytics", False),
            ("settings_top_tab_missionaries", False),
        ]:
            label = QLabel(tr(key))
            label.setObjectName("SettingsTopTab")
            label.setProperty("active", active)
            label.setFixedHeight(30)
            label.setAlignment(Qt.AlignCenter)
            tabs_layout.addWidget(label)
            self.settings_top_tab_labels[key] = label
        tabs_layout.addStretch()
        layout.addWidget(tabs)

        self.settings_title_label = QLabel(tr("settings_title"), top_bar)
        self.settings_title_label.setObjectName("SettingsTitle")
        self.settings_title_label.hide()
        self.settings_subtitle_label = QLabel(tr("settings_subtitle"), top_bar)
        self.settings_subtitle_label.setObjectName("SettingsSubtitle")
        self.settings_subtitle_label.hide()

        return top_bar

    def _build_tab_scroll(self, content_widget, *, full_width=False):
        tab = QWidget()
        tab.setObjectName("SettingsTabPage")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tab.setLayout(layout)

        scroll = create_scroll_area("SettingsScrollArea", transparent=True)
        shell = QWidget()
        shell.setObjectName("SettingsScrollShell")
        shell_layout = QHBoxLayout()
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell.setLayout(shell_layout)
        if full_width:
            shell_layout.addWidget(content_widget, stretch=1, alignment=Qt.AlignTop)
        else:
            shell_layout.addStretch()
            shell_layout.addWidget(content_widget, alignment=Qt.AlignTop)
            shell_layout.addStretch()
        scroll.setWidget(shell)
        layout.addWidget(scroll, stretch=1)
        return tab

    def _build_settings_content(self, *, full_width=False):
        content = QWidget()
        content.setObjectName("SettingsContent")
        if full_width:
            content.setMinimumWidth(980)
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        else:
            content.setMaximumWidth(1180)
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(16, 16, 16, 20)
        content_layout.setSpacing(12)
        content.setLayout(content_layout)
        return content, content_layout

    def _settings_card(self, title, hint=None):
        card = QFrame()
        card.setObjectName("SettingsCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)
        card.setLayout(layout)

        title_label = QLabel(title)
        title_label.setObjectName("SettingsCardTitle")
        layout.addWidget(title_label)

        hint_label = None
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("SettingsCardHint")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)

        body = QVBoxLayout()
        body.setContentsMargins(0, 2, 0, 0)
        body.setSpacing(10)
        layout.addLayout(body)
        return card, body, title_label, hint_label

    @staticmethod
    def _set_field_width(widget, width):
        widget.setMaximumWidth(width)
        return widget

    @staticmethod
    def _action_row(*buttons):
        row = QWidget()
        row.setObjectName("SettingsActionRow")
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        row.setLayout(layout)
        for button in buttons:
            layout.addWidget(button)
        layout.addStretch()
        return row

    @staticmethod
    def _settings_form():
        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        return form

    def _build_general_tab(self):
        content, layout = self._build_settings_content()

        card, body, self.language_title, self.hint_label = self._settings_card(
            tr("settings_language"),
            tr("settings_language_hint"),
        )
        self.lang_label = self.language_title
        self.lang_combo = self._set_field_width(create_combo_box(), 320)
        self.lang_combo.addItem(tr("lang_english"), "en")
        self.lang_combo.addItem(tr("lang_spanish"), "es")

        current = self.settings_service.get_language()
        idx = self.lang_combo.findData(current)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        body.addWidget(self.lang_combo)
        layout.addWidget(card)

        card, body, self.storage_label, self.storage_hint_label = self._settings_card(
            tr("settings_storage_root"),
            tr("settings_storage_root_hint"),
        )
        storage_row = QHBoxLayout()
        storage_row.setSpacing(8)

        self.storage_input = self._set_field_width(
            create_line_edit(
                tr("settings_storage_root"),
                "SettingsStorageInput",
            ),
            760,
        )
        self.storage_input.setText(self.settings_service.get_storage_root())
        if self.api_client is not None:
            try:
                server_configuration = self.api_client.get(
                    "/v1/server/configuration"
                )
                self.storage_input.setText(
                    server_configuration.get("mission_storage_root") or ""
                )
            except Exception:
                logger.exception("Could not load server storage configuration")
            self.storage_input.setReadOnly(True)
        storage_row.addWidget(self.storage_input)

        self.browse_btn = create_button(tr("settings_browse"), "secondary")
        self.browse_btn.clicked.connect(self._browse_storage_root)
        if self.api_client is not None:
            self.browse_btn.setEnabled(False)
        storage_row.addWidget(self.browse_btn)
        storage_row.addStretch()

        body.addLayout(storage_row)
        layout.addWidget(card)

        card, body, self.upload_behavior_title, self.upload_behavior_hint_label = (
            self._settings_card(
                tr("settings_upload_behavior"),
                tr("settings_upload_behavior_hint"),
            )
        )
        self.auto_ocr_check = create_check_box(
            tr("settings_auto_ocr"),
            "UploadAutoOcrEnabled",
        )
        self.auto_ocr_check.setChecked(
            self.settings_service.get_upload_auto_ocr_enabled()
        )
        body.addWidget(self.auto_ocr_check)
        layout.addWidget(card)

        self.general_save_btn = create_button(tr("settings_save"), "primary")
        self.general_save_btn.clicked.connect(self._save)
        layout.addWidget(self._action_row(self.general_save_btn))

        layout.addStretch()
        return self._build_tab_scroll(content)

    def _build_notifications_tab(self):
        content, layout = self._build_settings_content()

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        notification_settings = self.settings_service.get_notification_settings()
        digest_settings = self.settings_service.get_daily_digest_settings()

        card, body, self.notifications_title, self.notifications_hint_label = (
            self._settings_card(
                tr("settings_notifications_title"),
                tr("settings_notifications_hint"),
            )
        )
        self.startup_popup_check = create_check_box(
            tr("settings_startup_popup"),
            "StartupPopupEnabled",
        )
        self.startup_popup_check.setChecked(
            notification_settings.get("startup_popup_enabled", True)
        )
        body.addWidget(self.startup_popup_check)

        notification_form = self._settings_form()
        self.expiration_window_input = self._set_field_width(QSpinBox(), 140)
        self.expiration_window_input.setRange(1, 365)
        self.expiration_window_input.setFixedHeight(34)
        self.expiration_window_input.setValue(
            notification_settings.get("dashboard_expiration_days", 60)
        )
        notification_form.addRow(
            tr("settings_expiration_window"),
            self.expiration_window_input,
        )

        self.critical_window_input = self._set_field_width(QSpinBox(), 140)
        self.critical_window_input.setRange(1, 120)
        self.critical_window_input.setFixedHeight(34)
        self.critical_window_input.setValue(
            notification_settings.get("critical_expiration_days", 7)
        )
        notification_form.addRow(
            tr("settings_critical_window"),
            self.critical_window_input,
        )
        body.addLayout(notification_form)
        grid.addWidget(card, 0, 0)

        card, body, self.included_alerts_title, _ = self._settings_card(
            tr("settings_included_alerts")
        )
        self.notify_overdue_tasks_check = create_check_box(
            tr("settings_notify_overdue_tasks"),
            "NotifyOverdueTasks",
        )
        self.notify_overdue_tasks_check.setChecked(
            notification_settings.get("include_overdue_tasks", True)
        )
        body.addWidget(self.notify_overdue_tasks_check)

        self.notify_due_today_tasks_check = create_check_box(
            tr("settings_notify_due_today_tasks"),
            "NotifyDueTodayTasks",
        )
        self.notify_due_today_tasks_check.setChecked(
            notification_settings.get("include_due_today_tasks", True)
        )
        body.addWidget(self.notify_due_today_tasks_check)

        self.notify_appointments_check = create_check_box(
            tr("settings_notify_appointments"),
            "NotifyAppointments",
        )
        self.notify_appointments_check.setChecked(
            notification_settings.get("include_appointments", True)
        )
        body.addWidget(self.notify_appointments_check)

        self.notify_expiring_docs_check = create_check_box(
            tr("settings_notify_expiring_docs"),
            "NotifyExpiringDocuments",
        )
        self.notify_expiring_docs_check.setChecked(
            notification_settings.get("include_expiring_documents", True)
        )
        body.addWidget(self.notify_expiring_docs_check)

        self.notify_missing_docs_check = create_check_box(
            tr("settings_notify_missing_docs"),
            "NotifyMissingDocuments",
        )
        self.notify_missing_docs_check.setChecked(
            notification_settings.get("include_missing_documents", True)
        )
        body.addWidget(self.notify_missing_docs_check)

        self.notify_transfer_check = create_check_box(
            tr("settings_notify_transfer"),
            "NotifyTransferReminders",
        )
        self.notify_transfer_check.setChecked(
            notification_settings.get("include_transfer_reminders", True)
        )
        body.addWidget(self.notify_transfer_check)
        grid.addWidget(card, 1, 0)

        card, body, self.digest_title, self.digest_hint_label = self._settings_card(
            tr("settings_digest_title"),
            tr("settings_digest_hint"),
        )
        self.email_enabled_check = create_check_box(
            tr("settings_digest_email_enabled"),
            "DailyDigestEmailEnabled",
        )
        self.email_enabled_check.setChecked(
            digest_settings.get("email_enabled", False)
        )
        body.addWidget(self.email_enabled_check)

        digest_form = self._settings_form()
        self.recipient_input = self._set_field_width(
            create_line_edit(
                tr("settings_digest_recipient"),
                "DailyDigestRecipientInput",
            ),
            520,
        )
        self.recipient_input.setText(digest_settings.get("recipient_email", ""))
        digest_form.addRow(tr("settings_digest_recipient"), self.recipient_input)

        self.digest_time_input = self._set_field_width(QTimeEdit(), 180)
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
        digest_form.addRow(tr("settings_digest_time"), self.digest_time_input)

        self.include_overdue_check = create_check_box(
            tr("settings_digest_include_overdue"),
            "DailyDigestIncludeOverdue",
        )
        self.include_overdue_check.setChecked(
            digest_settings.get("include_overdue", True)
        )
        digest_form.addRow("", self.include_overdue_check)

        self.detail_combo = self._set_field_width(create_combo_box(), 260)
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
        digest_form.addRow(tr("settings_digest_detail"), self.detail_combo)
        body.addLayout(digest_form)
        grid.addWidget(card, 0, 1)

        card, body, self.email_delivery_title, _ = self._settings_card(
            tr("settings_email_delivery")
        )
        email_form = self._settings_form()
        self.smtp_host_input = self._set_field_width(
            create_line_edit(
                tr("settings_digest_smtp_host"),
                "DailyDigestSmtpHostInput",
            ),
            520,
        )
        self.smtp_host_input.setText(digest_settings.get("smtp_host", ""))
        email_form.addRow(tr("settings_digest_smtp_host"), self.smtp_host_input)

        self.smtp_port_input = self._set_field_width(
            create_line_edit(
                tr("settings_digest_smtp_port"),
                "DailyDigestSmtpPortInput",
            ),
            180,
        )
        self.smtp_port_input.setText(str(digest_settings.get("smtp_port", 587)))
        email_form.addRow(tr("settings_digest_smtp_port"), self.smtp_port_input)

        self.smtp_tls_combo = self._set_field_width(create_combo_box(), 260)
        self.smtp_tls_combo.addItem("STARTTLS", "starttls")
        self.smtp_tls_combo.addItem("SSL/TLS", "ssl")
        self.smtp_tls_combo.addItem(tr("settings_digest_tls_none"), "none")
        tls_idx = self.smtp_tls_combo.findData(
            digest_settings.get("smtp_tls", "starttls")
        )
        if tls_idx >= 0:
            self.smtp_tls_combo.setCurrentIndex(tls_idx)
        email_form.addRow(tr("settings_digest_tls"), self.smtp_tls_combo)

        self.sender_input = self._set_field_width(
            create_line_edit(
                tr("settings_digest_sender"),
                "DailyDigestSenderInput",
            ),
            520,
        )
        self.sender_input.setText(digest_settings.get("sender_email", ""))
        email_form.addRow(tr("settings_digest_sender"), self.sender_input)

        self.smtp_username_input = self._set_field_width(
            create_line_edit(
                tr("settings_digest_smtp_username"),
                "DailyDigestSmtpUsernameInput",
            ),
            520,
        )
        self.smtp_username_input.setText(
            digest_settings.get("smtp_username", "")
        )
        email_form.addRow(
            tr("settings_digest_smtp_username"),
            self.smtp_username_input,
        )

        self.smtp_password_input = self._set_field_width(
            create_line_edit(
                tr("settings_digest_smtp_password"),
                "DailyDigestSmtpPasswordInput",
            ),
            520,
        )
        self.smtp_password_input.setEchoMode(QLineEdit.Password)
        if self.settings_service.get_daily_digest_password():
            self.smtp_password_input.setPlaceholderText(
                tr("settings_digest_password_saved")
            )
        email_form.addRow(
            tr("settings_digest_smtp_password"),
            self.smtp_password_input,
        )
        body.addLayout(email_form)

        self.test_email_btn = create_button(
            tr("settings_digest_send_test"),
            "secondary",
        )
        self.test_email_btn.clicked.connect(self._send_test_digest)
        self.install_task_btn = create_button(
            tr("settings_digest_install_task"),
            "secondary",
        )
        self.install_task_btn.clicked.connect(self._install_digest_task)
        body.addWidget(
            self._action_row(self.test_email_btn, self.install_task_btn)
        )
        grid.addWidget(card, 1, 1)

        self.save_btn = create_button(tr("settings_save"), "primary")
        self.save_btn.clicked.connect(self._save)
        layout.addWidget(self._action_row(self.save_btn))
        layout.addStretch()
        return self._build_tab_scroll(content)

    def _build_transfer_tab(self):
        content, layout = self._build_settings_content()

        card, body, self.transfer_title, self.transfer_hint_label = (
            self._settings_card(
                tr("settings_transfer_title"),
                tr("settings_transfer_hint"),
            )
        )
        self.transfer_enabled_check = create_check_box(
            tr("settings_transfer_enabled"),
            "TransferRemindersEnabled",
        )
        body.addWidget(self.transfer_enabled_check)

        form = self._settings_form()

        transfer_date_row = QHBoxLayout()
        transfer_date_row.setSpacing(8)

        self.transfer_date_input = create_date_picker(
            "NextTransferDateInput"
        )
        self.transfer_date_input.setObjectName("NextTransferDateInput")
        self._set_field_width(self.transfer_date_input, 320)
        transfer_date_row.addWidget(self.transfer_date_input)

        self.transfer_help_btn = QPushButton("?")
        self.transfer_help_btn.setObjectName("SettingsHelpButton")
        self.transfer_help_btn.setFixedSize(24, 24)
        self.transfer_help_btn.clicked.connect(self._show_transfer_help)
        transfer_date_row.addWidget(self.transfer_help_btn)
        transfer_date_row.addStretch()

        form.addRow(tr("settings_transfer_anchor"), transfer_date_row)
        body.addLayout(form)

        self.save_transfer_btn = create_button(tr("settings_save"), "primary")
        self.save_transfer_btn.clicked.connect(self._save_transfer_settings)
        body.addWidget(self._action_row(self.save_transfer_btn))
        layout.addWidget(card)

        preview_card, preview_body, self.transfer_preview_title, _ = (
            self._settings_card(tr("settings_transfer_preview_title"))
        )
        self.transfer_warning_label = QLabel("")
        self.transfer_warning_label.setObjectName("MutedText")
        self.transfer_warning_label.setWordWrap(True)
        preview_body.addWidget(self.transfer_warning_label)

        self.transfer_preview_label = QLabel("")
        self.transfer_preview_label.setObjectName("MutedText")
        self.transfer_preview_label.setWordWrap(True)
        preview_body.addWidget(self.transfer_preview_label)
        layout.addWidget(preview_card)
        layout.addStretch()

        self.transfer_enabled_check.toggled.connect(
            self._transfer_enabled_changed
        )
        if hasattr(self.transfer_date_input, "dateChanged"):
            self.transfer_date_input.dateChanged.connect(
                self._refresh_transfer_preview
            )
        elif hasattr(self.transfer_date_input, "dateChangedSignal"):
            self.transfer_date_input.dateChangedSignal.connect(
                self._refresh_transfer_preview
            )
        self._load_transfer_settings()
        return self._build_tab_scroll(content)

    def _build_workspaces_tab(self):
        content, layout = self._build_settings_content(full_width=True)

        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(16)
        layout.addLayout(shell)

        list_card, list_body, self.workspaces_list_title, _ = self._settings_card(
            tr("workspaces_title"),
            tr("workspaces_hint"),
        )
        self.workspaces_list = create_list_widget("SettingsWorkspaceList")
        self.workspaces_list.setObjectName("SettingsWorkspaceList")
        self.workspaces_list.currentItemChanged.connect(
            self._workspace_selection_changed
        )
        list_body.addWidget(self.workspaces_list)

        self.workspace_new_btn = create_button(tr("workspace_new"), "primary")
        self.workspace_duplicate_btn = create_button(
            tr("workspace_duplicate"),
            "secondary",
        )
        self.workspace_delete_btn = create_button(tr("workspace_delete"), "danger")
        self.workspace_new_btn.clicked.connect(self._new_workspace)
        self.workspace_duplicate_btn.clicked.connect(self._duplicate_workspace)
        self.workspace_delete_btn.clicked.connect(self._delete_workspace)
        list_body.addWidget(
            self._action_row(
                self.workspace_new_btn,
                self.workspace_duplicate_btn,
                self.workspace_delete_btn,
            )
        )
        shell.addWidget(list_card, stretch=2)

        editor_card, editor_body, self.workspace_editor_title, _ = (
            self._settings_card(
                tr("workspace_editor_title"),
                tr("workspace_editor_hint"),
            )
        )
        form = self._settings_form()
        self.workspace_name_input = create_line_edit(
            tr("workspace_name"),
            "WorkspaceNameInput",
        )
        self.workspace_name_input.textChanged.connect(self._update_workspace_name)
        form.addRow(tr("workspace_name"), self.workspace_name_input)

        self.workspace_size_combo = create_combo_box()
        self.workspace_size_combo.addItem(tr("workspace_size_medium"), "medium")
        self.workspace_size_combo.addItem(tr("workspace_size_large"), "large")
        self.workspace_size_combo.addItem(tr("workspace_size_wide"), "wide")
        self.workspace_size_combo.currentIndexChanged.connect(
            self._update_workspace_size
        )
        form.addRow(tr("workspace_dialog_size"), self.workspace_size_combo)
        editor_body.addLayout(form)

        block_header = QHBoxLayout()
        block_header.setContentsMargins(0, 4, 0, 0)
        self.workspace_blocks_label = QLabel(tr("workspace_blocks"))
        self.workspace_blocks_label.setObjectName("SettingsCardTitle")
        block_header.addWidget(self.workspace_blocks_label)
        block_header.addStretch()
        self.block_add_combo = create_combo_box()
        for block_type in BLOCK_LABELS:
            self.block_add_combo.addItem(tr(BLOCK_LABELS[block_type]), block_type)
        block_header.addWidget(self.block_add_combo)
        self.block_add_btn = create_button(tr("workspace_add_block"), "secondary")
        self.block_add_btn.clicked.connect(self._add_workspace_block)
        block_header.addWidget(self.block_add_btn)
        editor_body.addLayout(block_header)

        self.blocks_list = create_list_widget("SettingsWorkspaceBlockList")
        self.blocks_list.setObjectName("SettingsWorkspaceBlockList")
        self.blocks_list.currentItemChanged.connect(
            self._workspace_block_selection_changed
        )
        editor_body.addWidget(self.blocks_list)

        self.block_up_btn = create_button(tr("workspace_move_up"), "secondary")
        self.block_down_btn = create_button(tr("workspace_move_down"), "secondary")
        self.block_remove_btn = create_button(tr("workspace_remove_block"), "danger")
        self.block_up_btn.clicked.connect(lambda: self._move_workspace_block(-1))
        self.block_down_btn.clicked.connect(lambda: self._move_workspace_block(1))
        self.block_remove_btn.clicked.connect(self._remove_workspace_block)
        editor_body.addWidget(
            self._action_row(
                self.block_up_btn,
                self.block_down_btn,
                self.block_remove_btn,
            )
        )

        self.workspace_layout_editor = WorkspaceLayoutEditor(
            lambda block_type: tr(
                BLOCK_LABELS.get(block_type, "workspace_block_unsupported")
            )
        )
        self.workspace_layout_editor.blockSelected.connect(
            self._select_block_from_layout
        )
        self.workspace_layout_editor.layoutChanged.connect(
            self._workspace_layout_changed
        )
        editor_body.addWidget(self.workspace_layout_editor)

        self.block_options_card = QFrame()
        self.block_options_card.setObjectName("SettingsCard")
        options_layout = QFormLayout()
        options_layout.setContentsMargins(16, 14, 16, 14)
        options_layout.setSpacing(10)
        self.block_options_card.setLayout(options_layout)

        self.block_title_input = create_line_edit(
            tr("workspace_block_title"),
            "WorkspaceBlockTitleInput",
        )
        self.block_title_input.textChanged.connect(self._update_block_title)
        options_layout.addRow(tr("workspace_block_title"), self.block_title_input)

        self.block_width_combo = create_combo_box()
        self.block_width_combo.addItem(tr("workspace_width_half"), "half")
        self.block_width_combo.addItem(tr("workspace_width_full"), "full")
        self.block_width_combo.currentIndexChanged.connect(self._update_block_width)
        options_layout.addRow(tr("workspace_block_width"), self.block_width_combo)

        self.block_height_combo = create_combo_box()
        self.block_height_combo.addItem(tr("workspace_height_compact"), "compact")
        self.block_height_combo.addItem(tr("workspace_height_normal"), "normal")
        self.block_height_combo.addItem(tr("workspace_height_tall"), "tall")
        self.block_height_combo.currentIndexChanged.connect(self._update_block_height)
        options_layout.addRow(tr("workspace_block_height"), self.block_height_combo)

        self.block_col_span_spin = QSpinBox()
        self.block_col_span_spin.setRange(1, WORKSPACE_GRID_COLUMNS)
        self.block_col_span_spin.valueChanged.connect(self._update_block_col_span)
        options_layout.addRow(tr("workspace_block_columns"), self.block_col_span_spin)

        self.block_row_span_spin = QSpinBox()
        self.block_row_span_spin.setRange(1, 8)
        self.block_row_span_spin.valueChanged.connect(self._update_block_row_span)
        options_layout.addRow(tr("workspace_block_rows"), self.block_row_span_spin)

        field_editor = QWidget()
        field_editor_layout = QVBoxLayout()
        field_editor_layout.setContentsMargins(0, 0, 0, 0)
        field_editor_layout.setSpacing(8)
        field_editor.setLayout(field_editor_layout)
        self.block_fields_widget = field_editor

        field_add_row = QHBoxLayout()
        field_add_row.setContentsMargins(0, 0, 0, 0)
        field_add_row.setSpacing(8)
        self.field_add_combo = create_combo_box()
        for field_key in FIELD_KEYS:
            self.field_add_combo.addItem(field_key, field_key)
        self.field_add_btn = create_button(tr("workspace_add_field"), "secondary")
        self.field_add_btn.clicked.connect(self._add_block_field)
        field_add_row.addWidget(self.field_add_combo, stretch=1)
        field_add_row.addWidget(self.field_add_btn)
        field_editor_layout.addLayout(field_add_row)

        self.block_fields_list = create_list_widget("WorkspaceBlockFieldsList")
        self.block_fields_list.setMinimumHeight(120)
        field_editor_layout.addWidget(self.block_fields_list)

        field_actions = QHBoxLayout()
        field_actions.setContentsMargins(0, 0, 0, 0)
        field_actions.setSpacing(8)
        self.field_up_btn = create_button(tr("workspace_move_up"), "secondary")
        self.field_down_btn = create_button(tr("workspace_move_down"), "secondary")
        self.field_remove_btn = create_button(tr("workspace_remove_field"), "danger")
        self.field_up_btn.clicked.connect(lambda: self._move_block_field(-1))
        self.field_down_btn.clicked.connect(lambda: self._move_block_field(1))
        self.field_remove_btn.clicked.connect(self._remove_block_field)
        field_actions.addWidget(self.field_up_btn)
        field_actions.addWidget(self.field_down_btn)
        field_actions.addWidget(self.field_remove_btn)
        field_actions.addStretch()
        field_editor_layout.addLayout(field_actions)
        options_layout.addRow(tr("workspace_block_fields"), field_editor)

        self.block_document_combo = create_combo_box()
        self.block_document_combo.addItem(tr("workspace_first_available_document"), "")
        for document_type, config in DOCUMENTS.items():
            self.block_document_combo.addItem(
                config.get("label", document_type),
                document_type,
            )
        self.block_document_combo.currentIndexChanged.connect(
            self._update_block_document_type
        )
        options_layout.addRow(
            tr("workspace_block_document_type"),
            self.block_document_combo,
        )

        self.block_web_url_input = create_line_edit(
            tr("workspace_block_web_url"),
            "WorkspaceBlockWebUrlInput",
        )
        self.block_web_url_input.textChanged.connect(self._update_block_web_url)
        options_layout.addRow(tr("workspace_block_web_url"), self.block_web_url_input)
        editor_body.addWidget(self.block_options_card)

        self.workspace_save_btn = create_button(tr("workspace_save"), "primary")
        self.workspace_save_btn.clicked.connect(self._save_current_workspace)
        editor_body.addWidget(self._action_row(self.workspace_save_btn))
        shell.addWidget(editor_card, stretch=6)

        preview_card, preview_body, self.workspace_preview_title, _ = (
            self._settings_card(
                tr("workspace_preview_title"),
                tr("workspace_preview_hint"),
            )
        )
        self.workspace_preview_grid = QGridLayout()
        self.workspace_preview_grid.setContentsMargins(0, 0, 0, 0)
        self.workspace_preview_grid.setHorizontalSpacing(10)
        self.workspace_preview_grid.setVerticalSpacing(10)
        preview_body.addLayout(self.workspace_preview_grid)
        shell.addWidget(preview_card, stretch=5)

        layout.addStretch()
        self._load_workspaces()
        return self._build_tab_scroll(content, full_width=True)

    def _load_workspaces(self):
        self._workspaces = self.workspace_service.list_workspaces()
        self.workspaces_list.blockSignals(True)
        self.workspaces_list.clear()
        for workspace in self._workspaces:
            item = QListWidgetItem(workspace.get("name", tr("workspace_title")))
            item.setData(Qt.UserRole, workspace.get("id"))
            self.workspaces_list.addItem(item)
        self.workspaces_list.blockSignals(False)
        if self._workspaces:
            self.workspaces_list.setCurrentRow(0)
        else:
            self._selected_workspace_id = None
            self._set_workspace_editor_enabled(False)

    def _current_workspace(self):
        return next(
            (
                workspace
                for workspace in self._workspaces
                if workspace.get("id") == self._selected_workspace_id
            ),
            None,
        )

    def _current_block(self):
        workspace = self._current_workspace()
        item = self.blocks_list.currentItem()
        if not workspace or item is None:
            return None
        block_id = item.data(Qt.UserRole)
        return next(
            (
                block
                for block in workspace.get("blocks", [])
                if block.get("id") == block_id
            ),
            None,
        )

    def _set_workspace_editor_enabled(self, enabled):
        for widget in (
            self.workspace_name_input,
            self.workspace_size_combo,
            self.blocks_list,
            self.block_add_combo,
            self.block_add_btn,
            self.block_up_btn,
            self.block_down_btn,
            self.block_remove_btn,
            self.workspace_layout_editor,
            self.block_options_card,
            self.workspace_save_btn,
            self.workspace_duplicate_btn,
            self.workspace_delete_btn,
        ):
            widget.setEnabled(enabled)

    def _workspace_selection_changed(self, current, previous):
        _ = previous
        self._selected_workspace_id = current.data(Qt.UserRole) if current else None
        self._populate_workspace_editor()

    def _populate_workspace_editor(self):
        workspace = self._current_workspace()
        self._set_workspace_editor_enabled(workspace is not None)
        if not workspace:
            self.workspace_name_input.clear()
            self.blocks_list.clear()
            self.workspace_layout_editor.set_workspace(None)
            self._refresh_workspace_preview()
            return
        normalized = normalize_workspace_layout(workspace)
        workspace["blocks"] = normalized.get("blocks", [])
        self.workspace_name_input.blockSignals(True)
        self.workspace_name_input.setText(workspace.get("name", ""))
        self.workspace_name_input.blockSignals(False)
        idx = self.workspace_size_combo.findData(workspace.get("dialog_size", "large"))
        if idx >= 0:
            self.workspace_size_combo.blockSignals(True)
            self.workspace_size_combo.setCurrentIndex(idx)
            self.workspace_size_combo.blockSignals(False)
        self._refresh_blocks_list()
        self.workspace_layout_editor.set_workspace(workspace)
        self._refresh_workspace_preview()

    def _refresh_blocks_list(self, selected_block_id=None):
        workspace = self._current_workspace()
        current_block = self._current_block()
        if selected_block_id is None and current_block is not None:
            selected_block_id = current_block.get("id")
        self.blocks_list.blockSignals(True)
        self.blocks_list.clear()
        if workspace:
            for block in workspace.get("blocks", []):
                item = QListWidgetItem(
                    f"{block.get('title', '')}  ({tr(BLOCK_LABELS.get(block.get('type'), 'workspace_block_unsupported'))})"
                )
                item.setData(Qt.UserRole, block.get("id"))
                self.blocks_list.addItem(item)
        self.blocks_list.blockSignals(False)
        if selected_block_id and self._select_block_item(selected_block_id):
            return
        if self.blocks_list.count():
            self.blocks_list.setCurrentRow(0)
        else:
            self._populate_block_options(None)

    def _workspace_block_selection_changed(self, current, previous):
        _ = previous
        self._populate_block_options(self._current_block() if current else None)

    def _populate_block_options(self, block):
        enabled = block is not None
        for widget in (
            self.block_title_input,
            self.block_width_combo,
            self.block_height_combo,
            self.block_col_span_spin,
            self.block_row_span_spin,
            self.block_fields_widget,
            self.field_add_combo,
            self.field_add_btn,
            self.block_fields_list,
            self.field_up_btn,
            self.field_down_btn,
            self.field_remove_btn,
            self.block_document_combo,
            self.block_web_url_input,
        ):
            widget.setEnabled(enabled)
        if not block:
            self.block_title_input.clear()
            self.block_fields_list.clear()
            self.block_fields_widget.setVisible(False)
            self.block_document_combo.setVisible(False)
            self.block_web_url_input.setVisible(False)
            return
        self.block_title_input.blockSignals(True)
        self.block_title_input.setText(block.get("title", ""))
        self.block_title_input.blockSignals(False)
        for combo, key, default in (
            (self.block_width_combo, "width", "half"),
            (self.block_height_combo, "height", "normal"),
        ):
            idx = combo.findData(block.get(key, default))
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)
        layout = validate_block_layout(block)
        self.block_col_span_spin.blockSignals(True)
        self.block_col_span_spin.setValue(layout["col_span"])
        self.block_col_span_spin.blockSignals(False)
        self.block_row_span_spin.blockSignals(True)
        self.block_row_span_spin.setValue(layout["row_span"])
        self.block_row_span_spin.blockSignals(False)
        self.workspace_layout_editor.set_selected_block(block.get("id"))
        self._refresh_block_fields_list()
        doc_idx = self.block_document_combo.findData(block.get("document_type", ""))
        self.block_document_combo.blockSignals(True)
        self.block_document_combo.setCurrentIndex(max(doc_idx, 0))
        self.block_document_combo.blockSignals(False)
        self.block_web_url_input.blockSignals(True)
        self.block_web_url_input.setText(block.get("web_url", ""))
        self.block_web_url_input.blockSignals(False)
        self.block_fields_widget.setVisible(block.get("type") == "personal_info")
        self.block_document_combo.setVisible(block.get("type") == "document_viewer")
        self.block_web_url_input.setVisible(block.get("type") == "web_viewer")

    def _select_block_item(self, block_id):
        for row in range(self.blocks_list.count()):
            item = self.blocks_list.item(row)
            if item.data(Qt.UserRole) == block_id:
                self.blocks_list.setCurrentRow(row)
                return True
        return False

    def _select_block_from_layout(self, block_id):
        if block_id:
            self._select_block_item(block_id)

    def _workspace_layout_changed(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        selected_id = self.workspace_layout_editor.selected_block_id
        self._refresh_blocks_list(selected_id)
        self._populate_block_options(self._current_block())
        self._refresh_workspace_preview()

    def _new_workspace(self):
        workspace = self.workspace_service.save_workspace(
            new_workspace(tr("workspace_default_name"))
        )
        self._load_workspaces()
        self._select_workspace(workspace.get("id"))

    def _duplicate_workspace(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        duplicate = self.workspace_service.duplicate_workspace(workspace["id"])
        self._load_workspaces()
        if duplicate:
            self._select_workspace(duplicate.get("id"))

    def _delete_workspace(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        self.workspace_service.delete_workspace(workspace["id"])
        self._load_workspaces()

    def _select_workspace(self, workspace_id):
        for row in range(self.workspaces_list.count()):
            item = self.workspaces_list.item(row)
            if item.data(Qt.UserRole) == workspace_id:
                self.workspaces_list.setCurrentRow(row)
                return

    def _update_workspace_name(self, value):
        workspace = self._current_workspace()
        if workspace is not None:
            workspace["name"] = value
            self._refresh_workspace_preview()

    def _update_workspace_size(self):
        workspace = self._current_workspace()
        if workspace is not None:
            workspace["dialog_size"] = self.workspace_size_combo.currentData()
            self._refresh_workspace_preview()

    def _add_workspace_block(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        block = new_block(self.block_add_combo.currentData())
        workspace.setdefault("blocks", []).append(block)
        workspace["blocks"] = normalize_workspace_layout(workspace).get("blocks", [])
        self._refresh_blocks_list(block.get("id"))
        self.workspace_layout_editor.set_workspace(workspace)
        self._refresh_workspace_preview()

    def _move_workspace_block(self, direction):
        workspace = self._current_workspace()
        item = self.blocks_list.currentItem()
        if not workspace or item is None:
            return
        block_id = item.data(Qt.UserRole)
        blocks = workspace.get("blocks", [])
        index = next((i for i, block in enumerate(blocks) if block.get("id") == block_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(blocks):
            return
        blocks[index], blocks[target] = blocks[target], blocks[index]
        workspace["blocks"] = normalize_workspace_layout(workspace).get("blocks", [])
        self._refresh_blocks_list(block_id)
        self.blocks_list.setCurrentRow(target)
        self.workspace_layout_editor.set_workspace(workspace)
        self._refresh_workspace_preview()

    def _remove_workspace_block(self):
        workspace = self._current_workspace()
        item = self.blocks_list.currentItem()
        if not workspace or item is None:
            return
        block_id = item.data(Qt.UserRole)
        workspace["blocks"] = [
            block
            for block in workspace.get("blocks", [])
            if block.get("id") != block_id
        ]
        self._refresh_blocks_list()
        self.workspace_layout_editor.set_workspace(workspace)
        self._refresh_workspace_preview()

    def _update_block_title(self, value):
        block = self._current_block()
        if block is not None:
            block["title"] = value
            self._refresh_blocks_list(block.get("id"))
            self.workspace_layout_editor.set_workspace(self._current_workspace())
            self._refresh_workspace_preview()

    def _update_block_width(self):
        block = self._current_block()
        if block is not None:
            block["width"] = self.block_width_combo.currentData()
            layout = validate_block_layout(block)
            layout["col_span"] = (
                WORKSPACE_GRID_COLUMNS
                if block["width"] == "full"
                else WORKSPACE_GRID_COLUMNS // 2
            )
            block["layout"] = validate_block_layout({"layout": layout})
            self.block_col_span_spin.blockSignals(True)
            self.block_col_span_spin.setValue(block["layout"]["col_span"])
            self.block_col_span_spin.blockSignals(False)
            self.workspace_layout_editor.set_workspace(self._current_workspace())
            self._refresh_workspace_preview()

    def _update_block_height(self):
        block = self._current_block()
        if block is not None:
            block["height"] = self.block_height_combo.currentData()
            layout = validate_block_layout(block)
            layout["row_span"] = {
                "compact": 1,
                "normal": 2,
                "tall": 3,
            }.get(block["height"], 2)
            block["layout"] = validate_block_layout({"layout": layout})
            self.block_row_span_spin.blockSignals(True)
            self.block_row_span_spin.setValue(block["layout"]["row_span"])
            self.block_row_span_spin.blockSignals(False)
            self.workspace_layout_editor.set_workspace(self._current_workspace())
            self._refresh_workspace_preview()

    def _update_block_col_span(self, value):
        block = self._current_block()
        if block is not None:
            block["width"] = "full" if value >= WORKSPACE_GRID_COLUMNS else "half"
            self.workspace_layout_editor.update_selected_layout(col_span=value)
            self._refresh_workspace_preview()

    def _update_block_row_span(self, value):
        block = self._current_block()
        if block is not None:
            block["height"] = "compact" if value <= 1 else "tall" if value >= 3 else "normal"
            self.workspace_layout_editor.update_selected_layout(row_span=value)
            self._refresh_workspace_preview()

    def _refresh_block_fields_list(self):
        block = self._current_block()
        self.block_fields_list.blockSignals(True)
        self.block_fields_list.clear()
        if block is not None:
            for field_key in block.get("fields", []):
                self.block_fields_list.addItem(QListWidgetItem(field_key))
        self.block_fields_list.blockSignals(False)

    def _add_block_field(self):
        block = self._current_block()
        if block is None or block.get("type") != "personal_info":
            return
        field_key = self.field_add_combo.currentData() or self.field_add_combo.currentText()
        if not field_key:
            return
        fields = block.setdefault("fields", [])
        if field_key not in fields:
            fields.append(field_key)
            self._refresh_block_fields_list()
            self._refresh_workspace_preview()

    def _remove_block_field(self):
        block = self._current_block()
        item = self.block_fields_list.currentItem()
        if block is None or item is None:
            return
        fields = list(block.get("fields", []))
        row = self.block_fields_list.row(item)
        if 0 <= row < len(fields):
            fields.pop(row)
            block["fields"] = fields
            self._refresh_block_fields_list()
            self.block_fields_list.setCurrentRow(min(row, len(fields) - 1))
            self._refresh_workspace_preview()

    def _move_block_field(self, direction):
        block = self._current_block()
        item = self.block_fields_list.currentItem()
        if block is None or item is None:
            return
        fields = list(block.get("fields", []))
        row = self.block_fields_list.row(item)
        target = row + direction
        if row < 0 or target < 0 or target >= len(fields):
            return
        fields[row], fields[target] = fields[target], fields[row]
        block["fields"] = fields
        self._refresh_block_fields_list()
        self.block_fields_list.setCurrentRow(target)
        self._refresh_workspace_preview()

    def _update_block_document_type(self):
        block = self._current_block()
        if block is not None and block.get("type") == "document_viewer":
            block["document_type"] = self.block_document_combo.currentData() or ""
            self._refresh_workspace_preview()

    def _update_block_web_url(self, value):
        block = self._current_block()
        if block is not None and block.get("type") == "web_viewer":
            block["web_url"] = value
            self._refresh_workspace_preview()

    def _sample_workspace_context(self):
        missionary = SimpleNamespace(
            id=0,
            full_name=tr("workspace_preview_sample_name"),
            missionary_code="SAMPLE-001",
            nationality="Peru",
            passport_number="P000000",
            carnet_number="CE-000000",
            date_of_birth=date(2000, 1, 1),
            arrival_date=date.today(),
            visa_expiration=None,
            passport_expiration=None,
            residency_expiration=None,
            prorroga_expiration=None,
            carnet_issue_date=None,
            interpol_appointment_date=None,
            biometric_appointment_date=None,
            pickup_appointment_date=None,
            folder_path="",
            current_stage="INTERPOL",
            notes=tr("workspace_preview_sample_notes"),
        )
        workflow = SimpleNamespace(
            id=0,
            stage_name="INTERPOL",
            status="IN PROGRESS",
        )
        return SimpleNamespace(
            missionary=missionary,
            documents=[],
            workflows=[workflow],
            tasks=[
                {
                    "id": 0,
                    "title": tr("workspace_preview_sample_task"),
                    "priority": "NORMAL",
                    "status": "TODO",
                    "due_date": None,
                }
            ],
            residency_rows=[],
            missing_groups=[("INTERPOL", ["PASSPORT"], True)],
        )

    def _refresh_workspace_preview(self):
        if not hasattr(self, "workspace_preview_grid"):
            return
        clear_layout(self.workspace_preview_grid)
        workspace = self._current_workspace()
        if not workspace:
            label = QLabel(tr("workspace_no_workspaces"))
            label.setObjectName("MutedText")
            self.workspace_preview_grid.addWidget(label, 0, 0, 1, WORKSPACE_GRID_COLUMNS)
            return
        preview_workspace = normalize_workspace_layout(workspace)
        fake_dialog = SimpleNamespace(
            preview_mode=True,
            context=self._sample_workspace_context(),
            find_document=lambda document_type=None: None,
            normalized_web_url=MissionaryWorkspaceDialog.normalized_web_url,
            open_web_url=lambda url: None,
            open_document_viewer=lambda doc: None,
            open_document_notes=lambda doc: None,
            open_document_file=lambda doc: None,
            change_workflow_status=lambda workflow: None,
            add_task=lambda: None,
            complete_task=lambda task: None,
            edit_task=lambda task: None,
        )
        factory = WorkspaceBlockFactory(fake_dialog)
        for col in range(WORKSPACE_GRID_COLUMNS):
            self.workspace_preview_grid.setColumnStretch(col, 1)
        for block in preview_workspace.get("blocks", []):
            layout = validate_block_layout(block)
            self.workspace_preview_grid.addWidget(
                factory.build(block),
                layout["row"],
                layout["col"],
                layout["row_span"],
                layout["col_span"],
            )

    def _save_current_workspace(self):
        workspace = self._current_workspace()
        if not workspace:
            return
        saved = self.workspace_service.save_workspace(workspace)
        self._load_workspaces()
        self._select_workspace(saved.get("id"))
        if self.main_window and hasattr(self.main_window, "refresh_workspace_actions"):
            self.main_window.refresh_workspace_actions()
        show_message(
            self,
            tr("workspaces_title"),
            tr("workspace_saved"),
        )

    def _save(self):
        lang = self.lang_combo.currentData()
        self.settings_service.set_language(lang)
        if self.api_client is None:
            self.settings_service.set_storage_root(
                self.storage_input.text().strip()
            )
        self.settings_service.set_upload_auto_ocr_enabled(
            self.auto_ocr_check.isChecked()
        )
        self._save_notification_settings()
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

    def _notification_values(self):
        return {
            "startup_popup_enabled": self.startup_popup_check.isChecked(),
            "dashboard_expiration_days": self.expiration_window_input.value(),
            "critical_expiration_days": self.critical_window_input.value(),
            "include_overdue_tasks": self.notify_overdue_tasks_check.isChecked(),
            "include_due_today_tasks": self.notify_due_today_tasks_check.isChecked(),
            "include_appointments": self.notify_appointments_check.isChecked(),
            "include_expiring_documents": self.notify_expiring_docs_check.isChecked(),
            "include_missing_documents": self.notify_missing_docs_check.isChecked(),
            "include_transfer_reminders": self.notify_transfer_check.isChecked(),
        }

    def _save_notification_settings(self):
        self.settings_service.set_notification_settings(
            self._notification_values()
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
                    tr("settings_transfer_title"),
                    tr("settings_transfer_off_saved"),
                )
            return True

        selected = self._transfer_date_value()
        self.settings_service.set_next_transfer_wednesday(selected)
        self._refresh_transfer_preview()
        if show_saved:
            show_message(
                self,
                tr("settings_transfer_title"),
                tr("settings_transfer_saved"),
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
                tr("settings_transfer_disabled")
            )
            self.transfer_preview_label.setText("")
            return

        selected = self._transfer_date_value()

        self.transfer_warning_label.setText(
            tr("settings_transfer_preview_intro")
        )
        previews = [
            selected + timedelta(days=42 * offset)
            for offset in range(6)
        ]
        self.transfer_preview_label.setText(
            "\n".join(item.strftime("%b %d, %Y") for item in previews)
        )

    @staticmethod
    def _next_wednesday(today):
        days = (2 - today.weekday()) % 7
        return today + timedelta(days=days)

    @staticmethod
    def _qdate_to_date(value):
        return date(value.year(), value.month(), value.day())

    def _transfer_date_value(self):
        if hasattr(self.transfer_date_input, "getDate"):
            return self._qdate_to_date(self.transfer_date_input.getDate())
        return self._qdate_to_date(self.transfer_date_input.date())

    def _show_transfer_help(self):
        show_message(
            self,
            tr("settings_transfer_title"),
            tr("settings_transfer_help"),
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
        self.settings_title_label.setText(tr("settings_title"))
        self.settings_subtitle_label.setText(tr("settings_subtitle"))
        for key, label in self.settings_top_tab_labels.items():
            label.setText(tr(key))
        self.tabs.setTabText(0, tr("settings_tab_general"))
        self.tabs.setTabText(1, tr("settings_tab_notifications"))
        self.tabs.setTabText(2, tr("settings_tab_transfer"))
        self.lang_label.setText(tr("settings_language"))
        self.hint_label.setText(tr("settings_language_hint"))
        self.storage_label.setText(tr("settings_storage_root"))
        self.storage_hint_label.setText(tr("settings_storage_root_hint"))
        self.upload_behavior_title.setText(tr("settings_upload_behavior"))
        self.upload_behavior_hint_label.setText(
            tr("settings_upload_behavior_hint")
        )
        self.auto_ocr_check.setText(tr("settings_auto_ocr"))
        self.browse_btn.setText(tr("settings_browse"))
        self.general_save_btn.setText(tr("settings_save"))
        self.notifications_title.setText(tr("settings_notifications_title"))
        self.notifications_hint_label.setText(tr("settings_notifications_hint"))
        self.included_alerts_title.setText(tr("settings_included_alerts"))
        self.startup_popup_check.setText(tr("settings_startup_popup"))
        self.notify_overdue_tasks_check.setText(tr("settings_notify_overdue_tasks"))
        self.notify_due_today_tasks_check.setText(
            tr("settings_notify_due_today_tasks")
        )
        self.notify_appointments_check.setText(tr("settings_notify_appointments"))
        self.notify_expiring_docs_check.setText(tr("settings_notify_expiring_docs"))
        self.notify_missing_docs_check.setText(tr("settings_notify_missing_docs"))
        self.notify_transfer_check.setText(tr("settings_notify_transfer"))
        self.digest_title.setText(tr("settings_digest_title"))
        self.digest_hint_label.setText(tr("settings_digest_hint"))
        self.email_enabled_check.setText(tr("settings_digest_email_enabled"))
        self.include_overdue_check.setText(
            tr("settings_digest_include_overdue")
        )
        self.test_email_btn.setText(tr("settings_digest_send_test"))
        self.install_task_btn.setText(tr("settings_digest_install_task"))
        self.email_delivery_title.setText(tr("settings_email_delivery"))
        self.save_btn.setText(tr("settings_save"))
        self.transfer_title.setText(tr("settings_transfer_title"))
        self.transfer_hint_label.setText(tr("settings_transfer_hint"))
        self.transfer_enabled_check.setText(tr("settings_transfer_enabled"))
        self.transfer_preview_title.setText(tr("settings_transfer_preview_title"))
        self.save_transfer_btn.setText(tr("settings_save"))
        current = self.lang_combo.currentData()
        self.lang_combo.clear()
        self.lang_combo.addItem(tr("lang_english"), "en")
        self.lang_combo.addItem(tr("lang_spanish"), "es")
        idx = self.lang_combo.findData(current)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
