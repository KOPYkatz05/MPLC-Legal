from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QGridLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSlider,
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
    create_scroll_area,
    show_message,
)
from PySide6.QtGui import QIntValidator
from ui.widgets.animated_tab_strip import (
    AnimatedTabStrip,
    set_tab_indicator_thickness,
)
from PySide6.QtCore import QDate, Qt, QTime
from datetime import date, timedelta
import time
import json
from services.email_digest_service import EmailDigestService
from services.scheduler_service import SchedulerService
from services.settings_service import SettingsService
from services.api_client import MissionLegalApiClient
from ui.foundation.background_loader import LatestRequestLoader
from utils.language_helper import ui_text as tr
from utils.logger import logger
from version import APP_VERSION


class SettingsPage(QWidget):
    SERVER_CONFIGURATION_CACHE_TTL_SECONDS = 300.0

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
        self._update_coordinator = None
        self._update_status = "not-configured"
        self._update_progress = 0
        self._server_configuration = None
        self._server_configuration_refreshed_at = 0.0
        self._server_configuration_input_baseline = ""
        self._server_configuration_loader = LatestRequestLoader(parent=self)
        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

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
        self.tabs.addTab(self._build_ui_tab(), tr("settings_tab_ui"))
        self.tabs.addTab(self._build_calendar_settings_tab(), tr("settings_tab_calendar"))
        self.tabs.addTab(self._build_analytics_settings_tab(), tr("settings_tab_analytics"))
        self.tabs.addTab(
            self._build_missionaries_settings_tab(),
            tr("settings_tab_missionaries"),
        )
        self.tabs.tabBar().hide()

        self._settings_tab_keys = (
            "general",
            "notifications",
            "transfer",
            "ui",
            "calendar",
            "analytics",
            "missionaries",
        )
        self.settings_tab_strip = AnimatedTabStrip()
        for index, (key, label) in enumerate(
            zip(
                self._settings_tab_keys,
                (
                    tr("settings_tab_general"),
                    tr("settings_tab_notifications"),
                    tr("settings_tab_transfer"),
                    tr("settings_tab_ui"),
                    tr("settings_tab_calendar"),
                    tr("settings_tab_analytics"),
                    tr("settings_tab_missionaries"),
                ),
            )
        ):
            self.settings_tab_strip.add_tab(
                key,
                label,
                lambda selected_key, tab_index=index: self.tabs.setCurrentIndex(
                    tab_index
                ),
            )
        self.tabs.currentChanged.connect(self._settings_tab_changed)
        self._sync_settings_tab_strip(self.tabs.currentIndex())
        workspace_layout.addWidget(self.settings_tab_strip)
        workspace_layout.addWidget(self.tabs, stretch=1)
        outer.addWidget(workspace, stretch=1)

    def _sync_settings_tab_strip(self, index):
        if 0 <= index < len(self._settings_tab_keys):
            self.settings_tab_strip.set_active(
                self._settings_tab_keys[index], animate=False
            )

    def _settings_tab_changed(self, index):
        self._sync_settings_tab_strip(index)

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
            self.storage_input.clear()
            self.storage_input.setPlaceholderText(
                "Loading server storage location…"
            )
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

        card, body, _, _ = self._settings_card(
            "Interpol packet contact details",
            "These server-managed values print beneath the passport copy.",
        )
        self.interpol_address_input = self._set_field_width(
            create_line_edit("Area Office address", "InterpolAreaOfficeAddress"),
            760,
        )
        self.interpol_phone_input = self._set_field_width(
            create_line_edit("Secretary phone", "InterpolSecretaryPhone"),
            420,
        )
        if self.api_client is None:
            from server.configuration import load_server_configuration
            local_configuration = load_server_configuration()
            self.interpol_address_input.setText(
                local_configuration.get("interpol_area_office_address", "")
            )
            self.interpol_phone_input.setText(
                local_configuration.get("interpol_secretary_phone", "")
            )
        body.addWidget(self.interpol_address_input)
        body.addWidget(self.interpol_phone_input)
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

        card, body, self.updates_title, self.updates_hint_label = (
            self._settings_card(
                tr("settings_updates_title"),
                tr("settings_updates_hint"),
            )
        )
        self.update_version_label = QLabel(
            tr("settings_updates_current_version", version=APP_VERSION)
        )
        self.update_version_label.setObjectName("SettingsCardHint")
        body.addWidget(self.update_version_label)

        self.automatic_updates_check = create_check_box(
            tr("settings_updates_automatic"),
            "AutomaticUpdatesEnabled",
        )
        self.automatic_updates_check.setChecked(
            self.settings_service.get_automatic_updates_enabled()
        )
        body.addWidget(self.automatic_updates_check)

        self.update_status_label = QLabel()
        self.update_status_label.setObjectName("SettingsCardHint")
        self.update_status_label.setWordWrap(True)
        body.addWidget(self.update_status_label)

        self.check_updates_btn = create_button(
            tr("settings_updates_check"),
            "secondary",
        )
        self.check_updates_btn.clicked.connect(self._check_for_updates)
        self.check_updates_btn.setEnabled(False)
        body.addWidget(self._action_row(self.check_updates_btn))
        self._render_update_status()
        layout.addWidget(card)

        self.general_save_btn = create_button(tr("settings_save"), "primary")
        self.general_save_btn.clicked.connect(self._save)
        layout.addWidget(self._action_row(self.general_save_btn))

        layout.addStretch()
        return self._build_tab_scroll(content)

    def _build_ui_tab(self):
        content, layout = self._build_settings_content()
        card, body, _, _ = self._settings_card(
            tr("settings_ui_tab_thickness"),
            tr("settings_ui_tab_thickness_hint"),
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        self.tab_thickness_slider = QSlider(Qt.Horizontal)
        self.tab_thickness_slider.setObjectName("TabIndicatorThicknessSlider")
        self.tab_thickness_slider.setRange(1, 6)
        self.tab_thickness_slider.setFixedWidth(240)
        self.tab_thickness_input = self._set_field_width(
            create_line_edit("1", "TabIndicatorThicknessInput"), 72
        )
        self.tab_thickness_input.setValidator(QIntValidator(1, 6, self))
        thickness = getattr(
            self.settings_service, "get_tab_indicator_thickness", lambda: 1
        )()
        self.tab_thickness_slider.setValue(thickness)
        self.tab_thickness_input.setText(str(thickness))
        self.tab_thickness_slider.valueChanged.connect(self._set_tab_thickness)
        self.tab_thickness_input.editingFinished.connect(
            self._commit_tab_thickness_input
        )
        row.addWidget(self.tab_thickness_slider)
        row.addWidget(self.tab_thickness_input)
        row.addWidget(QLabel("px"))
        row.addStretch()
        body.addLayout(row)
        layout.addWidget(card)
        layout.addStretch()
        return self._build_tab_scroll(content)

    def _build_default_view_tab(self, title_key, hint_key, choices, getter, setter):
        content, layout = self._build_settings_content()
        card, body, _, _ = self._settings_card(tr(title_key), tr(hint_key))
        combo = create_combo_box()
        for label_key, value in choices:
            combo.addItem(tr(label_key), value)
        current = getattr(self.settings_service, getter, lambda: choices[0][1])()
        index = combo.findData(current)
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(
            lambda _index: getattr(
                self.settings_service, setter, lambda value: value
            )(combo.currentData())
        )
        body.addWidget(combo)
        layout.addWidget(card)
        layout.addStretch()
        return self._build_tab_scroll(content), combo

    def _build_calendar_settings_tab(self):
        tab, self.calendar_default_view_combo = self._build_default_view_tab(
            "settings_calendar_default_view",
            "settings_calendar_default_view_hint",
            (
                ("settings_calendar_view_calendar", "calendar"),
                ("settings_calendar_view_history", "history"),
            ),
            "get_calendar_default_view",
            "set_calendar_default_view",
        )
        return tab

    def _build_analytics_settings_tab(self):
        tab, self.analytics_default_view_combo = self._build_default_view_tab(
            "settings_analytics_default_view",
            "settings_analytics_default_view_hint",
            (
                ("settings_analytics_view_general", "general"),
                ("settings_analytics_view_process", "process"),
                ("settings_analytics_view_documents", "documents"),
            ),
            "get_analytics_default_view",
            "set_analytics_default_view",
        )
        return tab

    def _build_missionaries_settings_tab(self):
        tab, self.missionaries_default_view_combo = self._build_default_view_tab(
            "settings_missionaries_default_view",
            "settings_missionaries_default_view_hint",
            (
                ("settings_missionaries_view_active", "active"),
                ("settings_missionaries_view_groups", "groups"),
                ("settings_missionaries_view_archive", "archive"),
            ),
            "get_missionaries_default_view",
            "set_missionaries_default_view",
        )
        return tab

    def _set_tab_thickness(self, thickness):
        save_thickness = getattr(
            self.settings_service,
            "set_tab_indicator_thickness",
            lambda value: max(1, min(6, int(value))),
        )
        thickness = save_thickness(thickness)
        self.tab_thickness_input.setText(str(thickness))
        set_tab_indicator_thickness(thickness)

    def _commit_tab_thickness_input(self):
        try:
            thickness = int(self.tab_thickness_input.text())
        except ValueError:
            thickness = getattr(
                self.settings_service, "get_tab_indicator_thickness", lambda: 1
            )()
        thickness = max(1, min(6, thickness))
        self.tab_thickness_slider.setValue(thickness)
        self.tab_thickness_input.setText(str(thickness))

    def request_refresh(self, force=False):
        if self.api_client is None:
            return False

        now = time.monotonic()
        cache_is_fresh = (
            self._server_configuration is not None
            and (
                now - self._server_configuration_refreshed_at
                < self.SERVER_CONFIGURATION_CACHE_TTL_SECONDS
            )
        )
        if cache_is_fresh and not force:
            return False

        client = self.api_client
        self._server_configuration_input_baseline = self.storage_input.text()
        self._server_configuration_loader.request(
            lambda: client.get("/v1/server/configuration"),
            on_success=self._apply_server_configuration,
            on_error=self._server_configuration_refresh_failed,
        )
        return True

    def load_data(self):
        """Compatibility entry point for callers that need a forced refresh."""
        return self.request_refresh(force=True)

    def _apply_server_configuration(self, configuration):
        self._server_configuration = dict(configuration or {})
        self._server_configuration_refreshed_at = time.monotonic()
        if (
            self.storage_input.isReadOnly()
            or (
                self.storage_input.text()
                == self._server_configuration_input_baseline
            )
        ):
            self.storage_input.setText(
                self._server_configuration.get("mission_storage_root") or ""
            )
        self.interpol_address_input.setText(
            self._server_configuration.get(
                "interpol_area_office_address", ""
            )
        )
        self.interpol_phone_input.setText(
            self._server_configuration.get("interpol_secretary_phone", "")
        )

    def _server_configuration_refresh_failed(self, error):
        logger.error(
            "Could not load server storage configuration",
            exc_info=(type(error), error, error.__traceback__),
        )
        if self._server_configuration is None:
            self.storage_input.setPlaceholderText(
                "Server storage location is currently unavailable."
            )

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

    def _save(self):
        lang = self.lang_combo.currentData()
        self.settings_service.set_language(lang)
        if self.api_client is None:
            self.settings_service.set_storage_root(
                self.storage_input.text().strip()
            )
            from server.configuration import (
                load_server_configuration,
                save_server_configuration,
            )
            configuration = load_server_configuration()
            configuration.update({
                "interpol_area_office_address":
                    self.interpol_address_input.text().strip(),
                "interpol_secretary_phone":
                    self.interpol_phone_input.text().strip(),
            })
            save_server_configuration(configuration)
        else:
            self.api_client.patch(
                "/v1/server/configuration",
                json={
                    "interpol_area_office_address":
                        self.interpol_address_input.text().strip(),
                    "interpol_secretary_phone":
                        self.interpol_phone_input.text().strip(),
                },
            )
        self.settings_service.set_upload_auto_ocr_enabled(
            self.auto_ocr_check.isChecked()
        )
        self.settings_service.set_automatic_updates_enabled(
            self.automatic_updates_check.isChecked()
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

    def bind_update_coordinator(self, coordinator):
        self._update_coordinator = coordinator
        self.check_updates_btn.setEnabled(bool(coordinator and coordinator.enabled))
        if coordinator is None or not coordinator.enabled:
            self._update_status = "not-configured"
            self._render_update_status()
            return
        coordinator.status_changed.connect(self._set_update_status)
        coordinator.progress_changed.connect(self._set_update_progress)
        coordinator.update_ready.connect(self._set_ready_update_version)
        self._update_status = "idle"
        self._render_update_status()

    def _check_for_updates(self):
        coordinator = self._update_coordinator or getattr(
            self.main_window,
            "update_coordinator",
            None,
        )
        if coordinator is None:
            self._set_update_status("not-configured")
            return
        coordinator.check_for_updates(manual=True)

    def _set_update_status(self, status):
        self._update_status = str(status or "idle")
        self._render_update_status()

    def _set_update_progress(self, progress):
        self._update_progress = max(0, min(100, int(progress)))
        self._update_status = "downloading"
        self._render_update_status()

    def _set_ready_update_version(self, version):
        self._ready_update_version = str(version)

    def _render_update_status(self):
        if not hasattr(self, "update_status_label"):
            return
        if self._update_status == "downloading":
            text = tr(
                "settings_updates_status_downloading",
                progress=self._update_progress,
            )
        else:
            key = {
                "not-configured": "settings_updates_status_not_configured",
                "disabled": "settings_updates_status_disabled",
                "idle": "settings_updates_status_idle",
                "checking": "settings_updates_status_checking",
                "current": "settings_updates_status_current",
                "available": "settings_updates_status_available",
                "ready": "settings_updates_status_ready",
                "applying": "settings_updates_status_applying",
                "failed": "settings_updates_status_failed",
            }.get(self._update_status, "settings_updates_status_idle")
            text = tr(key)
        self.update_status_label.setText(text)

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
        self.tabs.setTabText(0, tr("settings_tab_general"))
        self.tabs.setTabText(1, tr("settings_tab_notifications"))
        self.tabs.setTabText(2, tr("settings_tab_transfer"))
        self.tabs.setTabText(3, tr("settings_tab_ui"))
        self.tabs.setTabText(4, tr("settings_tab_calendar"))
        self.tabs.setTabText(5, tr("settings_tab_analytics"))
        self.tabs.setTabText(6, tr("settings_tab_missionaries"))
        self.lang_label.setText(tr("settings_language"))
        self.hint_label.setText(tr("settings_language_hint"))
        self.storage_label.setText(tr("settings_storage_root"))
        self.storage_hint_label.setText(tr("settings_storage_root_hint"))
        self.upload_behavior_title.setText(tr("settings_upload_behavior"))
        self.upload_behavior_hint_label.setText(
            tr("settings_upload_behavior_hint")
        )
        self.auto_ocr_check.setText(tr("settings_auto_ocr"))
        self.updates_title.setText(tr("settings_updates_title"))
        self.updates_hint_label.setText(tr("settings_updates_hint"))
        self.update_version_label.setText(
            tr("settings_updates_current_version", version=APP_VERSION)
        )
        self.automatic_updates_check.setText(tr("settings_updates_automatic"))
        self.check_updates_btn.setText(tr("settings_updates_check"))
        self._render_update_status()
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
