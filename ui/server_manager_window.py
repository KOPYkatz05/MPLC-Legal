"""Small, per-user control surface for the Mission Legal Windows service."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QEvent,
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.pairing_package import PAIRING_PACKAGE_PREFIX
from services.server_update_service import ServerUpdateService
from ui.foundation import AppTitleBar, create_pill_button, lucide_icon


WINDOW_WIDTH = 760
WINDOW_HEIGHT = 520
RESTART_POLL_INTERVAL_MS = 750
RESTART_VERIFY_TIMEOUT_SECONDS = 45
PUBLIC_CA_FOLDER = Path(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData")
) / "MissionLegal" / "Public"


def create_management_client():
    """Import the Windows-only transport lazily so tests can inject a fake."""

    from server.management_pipe import MissionLegalManagementClient

    return MissionLegalManagementClient()


class _TaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _RequestTask(QRunnable):
    def __init__(self, operation: Callable[[], Any]):
        super().__init__()
        self.operation = operation
        self.signals = _TaskSignals()

    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.succeeded.emit(result)


class AsyncRequestRunner(QObject):
    """Run management-pipe calls without blocking the Qt event loop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._active_tasks: set[_RequestTask] = set()

    def submit(self, operation, on_success, on_error):
        task = _RequestTask(operation)
        self._active_tasks.add(task)

        def finish_success(result):
            self._active_tasks.discard(task)
            on_success(result)

        def finish_error(message):
            self._active_tasks.discard(task)
            on_error(message)

        task.signals.succeeded.connect(finish_success)
        task.signals.failed.connect(finish_error)
        self.pool.start(task)


class _MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("ServerMetricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        title_label = QLabel(title, self)
        title_label.setObjectName("ServerMetricTitle")
        self.value_label = QLabel(value, self)
        self.value_label.setObjectName("ServerMetricValue")
        self.value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: Any):
        self.value_label.setText("—" if value in (None, "") else str(value))


class ServerManagerWindow(QMainWindow):
    """Frameless manager window; closing it leaves the tray process running."""

    server_state_changed = Signal(str)
    server_address_availability_changed = Signal(bool)
    update_launched = Signal()

    def __init__(
        self,
        management_client=None,
        request_runner=None,
        update_service=None,
        *,
        confirm_revoke=None,
        confirm_restart=None,
        parent=None,
    ):
        super().__init__(parent)
        self.management_client = management_client or create_management_client()
        self.request_runner = request_runner or AsyncRequestRunner(self)
        self.update_service = (
            update_service if update_service is not None else ServerUpdateService()
        )
        self.confirm_revoke = confirm_revoke or self._default_confirm_revoke
        self.confirm_restart = confirm_restart or self._default_confirm_restart
        self._allow_close = False
        self._status_request_pending = False
        self._devices_request_serial = 0
        self._pairing_request_serial = 0
        self._pairing_request_pending = False
        self._restart_poll_active = False
        self._restart_deadline = 0.0
        self._pairing_expires_at: datetime | None = None
        self._current_pairing_code = ""
        self._current_setup_code = ""
        self._server_address = ""
        self._network_available = False
        self._network_trusted = False
        self._cached_status: dict[str, Any] = {}
        self._available_update = None
        self._update_request_pending = False

        self.setObjectName("ServerManagerWindow")
        self.setWindowTitle("Mission Legal Server Manager")
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowSystemMenuHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._build_ui()
        self._apply_local_style()

        self.pairing_timer = QTimer(self)
        self.pairing_timer.setInterval(1000)
        self.pairing_timer.timeout.connect(self._update_pairing_countdown)
        self.pairing_timer.start()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(5000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

        self.restart_poll_timer = QTimer(self)
        self.restart_poll_timer.setSingleShot(True)
        self.restart_poll_timer.timeout.connect(self._poll_restart_status)
        QTimer.singleShot(0, self.refresh_status)
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(6 * 60 * 60 * 1000)
        self.update_timer.timeout.connect(self.check_for_updates)
        self.update_timer.start()
        if self.update_service.enabled:
            QTimer.singleShot(1500, self.check_for_updates)

    def _build_ui(self):
        outer = QWidget(self)
        outer.setObjectName("ServerManagerOuter")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(0)

        self.surface = QFrame(outer)
        self.surface.setObjectName("ServerManagerSurface")
        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(0)

        self.title_bar = AppTitleBar("Mission Legal Server Manager", self.surface)
        self.title_bar.maximize_button.hide()
        self.title_bar.drag_region.installEventFilter(self)
        title_label = QLabel("Mission Legal Server", self.title_bar.drag_region)
        title_label.setObjectName("ServerManagerTitle")
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.title_bar.drag_region.layout().insertWidget(1, title_label)
        surface_layout.addWidget(self.title_bar)

        content = QWidget(self.surface)
        content.setObjectName("ServerManagerContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 18)
        content_layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(2, 0, 2, 0)
        heading_row.setSpacing(8)
        heading = QLabel("Server Manager", content)
        heading.setObjectName("ServerManagerHeading")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        self.header_status = QLabel("Checking…", content)
        self.header_status.setObjectName("ServerStateBadge")
        self.header_status.setProperty("state", "checking")
        heading_row.addWidget(self.header_status)
        content_layout.addLayout(heading_row)

        self.tabs = QTabWidget(content)
        self.tabs.setObjectName("ServerManagerTabs")
        self.tabs.setDocumentMode(True)
        self.pairing_tab = self._build_pairing_tab()
        self.status_tab = self._build_status_tab()
        self.devices_tab = self._build_devices_tab()
        self.tools_tab = self._build_tools_tab()
        self.updates_tab = self._build_updates_tab()
        self.tabs.addTab(self.pairing_tab, "Pairing")
        self.tabs.addTab(self.status_tab, "Status")
        self.tabs.addTab(self.devices_tab, "Paired Devices")
        self.tabs.addTab(self.tools_tab, "Tools")
        self.tabs.addTab(self.updates_tab, "Updates")
        self.tabs.currentChanged.connect(self._tab_changed)
        content_layout.addWidget(self.tabs, stretch=1)
        surface_layout.addWidget(content, stretch=1)
        outer_layout.addWidget(self.surface)
        self.setCentralWidget(outer)

    def _page(self):
        page = QWidget(self.tabs)
        page.setObjectName("ServerManagerPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(12)
        return page

    @staticmethod
    def _section_header(parent, title, subtitle):
        container = QWidget(parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title_label = QLabel(title, container)
        title_label.setObjectName("ServerSectionTitle")
        subtitle_label = QLabel(subtitle, container)
        subtitle_label.setObjectName("ServerSectionSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return container

    def _button(self, text, *, icon_name=None, primary=False, danger=False):
        icon = (
            lucide_icon(icon_name, size=16, color="#FFFFFF" if primary else "#0F5F64")
            if icon_name
            else None
        )
        button = create_pill_button(text, parent=self, icon=icon)
        if not isinstance(button, QPushButton) and hasattr(button, "setFixedHeight"):
            button.setFixedHeight(34)
        else:
            button.setFixedHeight(34)
        if primary:
            button.setObjectName("ServerPrimaryPill")
        elif danger:
            button.setObjectName("ServerDangerPill")
        else:
            button.setObjectName("ServerPillButton")
        return button

    def _build_pairing_tab(self):
        page = self._page()
        layout = page.layout()
        layout.addWidget(
            self._section_header(
                page,
                "Pair a new computer",
                "Trust the current network, then give the other computer the "
                "six-digit code shown here.",
            )
        )

        network_card = QFrame(page)
        network_card.setObjectName("ServerToolCard")
        network_layout = QHBoxLayout(network_card)
        network_layout.setContentsMargins(14, 8, 14, 8)
        network_text = QVBoxLayout()
        self.network_name_label = QLabel("Checking the current network…", network_card)
        self.network_name_label.setObjectName("ServerSectionTitle")
        self.network_name_label.setTextFormat(Qt.PlainText)
        self.network_trust_label = QLabel(
            "New-device discovery is unavailable until this network is trusted.",
            network_card,
        )
        self.network_trust_label.setObjectName("ServerSectionSubtitle")
        self.network_trust_label.setTextFormat(Qt.PlainText)
        self.network_trust_label.setWordWrap(True)
        network_text.addWidget(self.network_name_label)
        network_text.addWidget(self.network_trust_label)
        network_layout.addLayout(network_text, 1)
        self.network_trust_button = self._button(
            "Trust this network", icon_name="shield-check"
        )
        self.network_trust_button.setEnabled(False)
        self.network_trust_button.clicked.connect(self.toggle_current_network_trust)
        network_layout.addWidget(self.network_trust_button)
        layout.addWidget(network_card)

        card = QFrame(page)
        card.setObjectName("PairingCodeCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 12, 18, 12)
        card_layout.setSpacing(4)
        self.pairing_code_label = QLabel("— — — — — —", card)
        self.pairing_code_label.setObjectName("PairingCode")
        self.pairing_code_label.setAlignment(Qt.AlignCenter)
        self.pairing_code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pairing_expiry_label = QLabel("No active pairing code", card)
        self.pairing_expiry_label.setObjectName("PairingExpiry")
        self.pairing_expiry_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.pairing_code_label)
        card_layout.addWidget(self.pairing_expiry_label)
        layout.addWidget(card)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.generate_code_button = self._button(
            "Generate pairing code",
            icon_name="key-round",
            primary=True,
        )
        self.copy_code_button = self._button(
            "Copy advanced setup code", icon_name="copy"
        )
        self.copy_code_button.setEnabled(False)
        self.generate_code_button.clicked.connect(self.generate_pairing_code)
        self.copy_code_button.clicked.connect(self.copy_pairing_code)
        button_row.addWidget(self.generate_code_button)
        button_row.addWidget(self.copy_code_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.pairing_feedback = QLabel("", page)
        self.pairing_feedback.setObjectName("ServerFeedback")
        self.pairing_feedback.setAlignment(Qt.AlignCenter)
        self.pairing_feedback.setWordWrap(True)
        layout.addWidget(self.pairing_feedback)
        layout.addStretch()
        return page

    def _build_status_tab(self):
        page = self._page()
        layout = page.layout()
        header_row = QHBoxLayout()
        header_row.addWidget(
            self._section_header(
                page,
                "Server status",
                "Live health and resource information for the background service.",
            ),
            stretch=1,
        )
        self.refresh_status_button = self._button("Refresh", icon_name="refresh-cw")
        self.refresh_status_button.clicked.connect(self.refresh_status)
        header_row.addWidget(self.refresh_status_button, alignment=Qt.AlignBottom)
        layout.addLayout(header_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.status_cards = {
            "version": _MetricCard("Version"),
            "address": _MetricCard("Server address"),
            "uptime": _MetricCard("Uptime"),
            "cpu": _MetricCard("CPU usage"),
            "ram": _MetricCard("Memory usage"),
            "database": _MetricCard("Database file"),
        }
        for index, card in enumerate(self.status_cards.values()):
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)
        self.status_feedback = QLabel("Checking the service…", page)
        self.status_feedback.setObjectName("ServerFeedback")
        self.status_feedback.setWordWrap(True)
        layout.addWidget(self.status_feedback)
        layout.addStretch()
        return page

    def _build_devices_tab(self):
        page = self._page()
        layout = page.layout()
        header_row = QHBoxLayout()
        header_row.addWidget(
            self._section_header(
                page,
                "Paired devices",
                "Review computers allowed to connect and revoke access when needed.",
            ),
            stretch=1,
        )
        self.refresh_devices_button = self._button("Refresh", icon_name="refresh-cw")
        self.refresh_devices_button.clicked.connect(self.refresh_devices)
        header_row.addWidget(self.refresh_devices_button, alignment=Qt.AlignBottom)
        layout.addLayout(header_row)

        self.devices_table = QTableWidget(0, 4, page)
        self.devices_table.setObjectName("ServerDevicesTable")
        self.devices_table.setHorizontalHeaderLabels(
            ["Computer", "State", "Paired", ""]
        )
        self.devices_table.verticalHeader().hide()
        self.devices_table.setShowGrid(False)
        self.devices_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.devices_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.devices_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.devices_table.setFocusPolicy(Qt.StrongFocus)
        self.devices_table.setAccessibleName("Paired devices")
        self.devices_table.setAccessibleDescription(
            "Computers that are active, pending confirmation, or revoked."
        )
        header = self.devices_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.devices_table, stretch=1)
        self.devices_feedback = QLabel("", page)
        self.devices_feedback.setObjectName("ServerFeedback")
        self.devices_feedback.setWordWrap(True)
        layout.addWidget(self.devices_feedback)
        return page

    def _build_tools_tab(self):
        page = self._page()
        layout = page.layout()
        layout.addWidget(
            self._section_header(
                page,
                "Server tools",
                "Safe maintenance actions. These buttons never accept command-line input.",
            )
        )

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.restart_button = self._tool_card(
            page,
            "Restart API runtime",
            "Request an API restart, then wait until the server reports that it is ready.",
            "rotate-cw",
            self.restart_server,
        )
        self.backup_button = self._tool_card(
            page,
            "Create verified backup",
            "Create and verify a database snapshot.",
            "database-backup",
            self.create_verified_backup,
        )
        self.copy_address_button = self._tool_card(
            page,
            "Copy server address",
            "Copy the LAN address used by client computers.",
            "copy",
            self.copy_server_address,
        )
        self.copy_address_button.setEnabled(False)
        self.open_ca_button = self._tool_card(
            page,
            "Open public certificate folder",
            "Open the fixed folder containing the shareable CA certificate.",
            "folder-open",
            self.open_public_ca_folder,
        )
        self.support_button = self._tool_card(
            page,
            "Copy support summary",
            "Copy a sanitized diagnostic summary with no credentials.",
            "clipboard-copy",
            self.copy_support_summary,
        )
        cards = [
            self.restart_button,
            self.backup_button,
            self.copy_address_button,
            self.open_ca_button,
            self.support_button,
        ]
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)
        self.tools_feedback = QLabel("", page)
        self.tools_feedback.setObjectName("ServerFeedback")
        self.tools_feedback.setWordWrap(True)
        layout.addWidget(self.tools_feedback)
        layout.addStretch()
        return page

    def _build_updates_tab(self):
        page = self._page()
        layout = page.layout()
        layout.addWidget(
            self._section_header(
                page,
                "Server updates",
                "Updates are downloaded from the configured GitHub repository and "
                "cryptographically verified before Windows asks for approval.",
            )
        )
        self.update_version_label = QLabel("Current version: checking…", page)
        self.update_version_label.setObjectName("ServerMetricValue")
        self.update_notes_label = QLabel("", page)
        self.update_notes_label.setObjectName("ServerSectionSubtitle")
        self.update_notes_label.setWordWrap(True)
        self.update_progress = QProgressBar(page)
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.update_progress.setTextVisible(True)
        self.update_progress.hide()
        layout.addWidget(self.update_version_label)
        layout.addWidget(self.update_notes_label)
        layout.addWidget(self.update_progress)

        buttons = QHBoxLayout()
        self.check_update_button = self._button(
            "Check for updates", icon_name="refresh-cw"
        )
        self.download_update_button = self._button(
            "Download update", icon_name="download"
        )
        self.install_update_button = self._button(
            "Update now", icon_name="shield-check", primary=True
        )
        self.download_update_button.setEnabled(False)
        self.install_update_button.setEnabled(False)
        self.check_update_button.clicked.connect(self.check_for_updates)
        self.download_update_button.clicked.connect(self.download_server_update)
        self.install_update_button.clicked.connect(self.install_server_update)
        buttons.addWidget(self.check_update_button)
        buttons.addWidget(self.download_update_button)
        buttons.addStretch()
        buttons.addWidget(self.install_update_button)
        layout.addLayout(buttons)
        self.update_feedback = QLabel("", page)
        self.update_feedback.setObjectName("ServerFeedback")
        self.update_feedback.setWordWrap(True)
        layout.addWidget(self.update_feedback)
        layout.addStretch()
        if not self.update_service.enabled:
            self.check_update_button.setEnabled(False)
            self.update_version_label.setText("Automatic updates are not configured")
            self._set_feedback(
                self.update_feedback,
                "Install a server package containing a trusted release configuration.",
            )
        return page

    def check_for_updates(self):
        if not self.update_service.enabled or self._update_request_pending:
            return
        self._update_request_pending = True
        self.check_update_button.setEnabled(False)
        self.download_update_button.setEnabled(False)
        self._set_feedback(self.update_feedback, "Checking GitHub for server updates…")
        self.request_runner.submit(
            self.update_service.check_for_update,
            self._update_check_finished,
            self._update_operation_failed,
        )

    def _update_check_finished(self, update):
        self._update_request_pending = False
        self.check_update_button.setEnabled(True)
        self._available_update = update
        if update is None:
            self.update_version_label.setText(
                f"Current version {self.update_service.current_version} is up to date"
            )
            self.update_notes_label.clear()
            self.download_update_button.setEnabled(False)
            self._set_feedback(self.update_feedback, "No newer server release is available.")
            return
        self.update_version_label.setText(
            f"Version {update.version} is available"
        )
        self.update_notes_label.setText((update.notes or "No release notes.")[:1200])
        self.download_update_button.setEnabled(True)
        self._set_feedback(
            self.update_feedback,
            "Ready to download and verify the server installer.",
        )

    def download_server_update(self):
        if self._available_update is None or self._update_request_pending:
            return
        self._update_request_pending = True
        self.check_update_button.setEnabled(False)
        self.download_update_button.setEnabled(False)
        self.update_progress.setRange(0, 0)
        self.update_progress.show()
        self._set_feedback(
            self.update_feedback,
            "Downloading and cryptographically verifying the update…",
        )
        self.request_runner.submit(
            lambda: self.update_service.download_update(self._available_update),
            self._update_download_finished,
            self._update_operation_failed,
        )

    def _update_download_finished(self, prepared):
        self._update_request_pending = False
        self.check_update_button.setEnabled(True)
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(100)
        self.install_update_button.setEnabled(True)
        self._set_feedback(
            self.update_feedback,
            f"Version {prepared.version} is verified and ready to install.",
        )

    def _update_operation_failed(self, message):
        self._update_request_pending = False
        self.check_update_button.setEnabled(bool(self.update_service.enabled))
        self.download_update_button.setEnabled(self._available_update is not None)
        self.install_update_button.setEnabled(False)
        self.update_progress.hide()
        self._set_feedback(
            self.update_feedback,
            f"Update failed: {self._safe_error(message)}",
            error=True,
        )

    def install_server_update(self):
        prepared = self.update_service.prepared_update
        if prepared is None:
            return
        answer = QMessageBox.question(
            self,
            "Install server update",
            f"Install Mission Legal Server {prepared.version} now?\n\n"
            "Connected computers will pause briefly. Windows will ask an "
            "administrator to approve the update.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.update_service.apply_prepared_update()
        except Exception as exc:
            self._update_operation_failed(str(exc))
            return
        self._set_feedback(
            self.update_feedback,
            "Windows approved the update. Server Manager will close while Setup "
            "updates and verifies the service.",
        )
        self.update_launched.emit()

    def _tool_card(self, parent, title, subtitle, icon_name, callback):
        button = self._button(title, icon_name=icon_name)
        button.setToolTip(subtitle)
        button.setAccessibleDescription(subtitle)
        button.clicked.connect(callback)
        return button

    def generate_pairing_code(self):
        if self._pairing_request_pending:
            self._set_feedback(
                self.pairing_feedback,
                "A pairing code is already being generated.",
            )
            return
        self._pairing_request_pending = True
        self._pairing_request_serial += 1
        request_serial = self._pairing_request_serial
        self._clear_pairing_code("Generating a new pairing code…")
        self.generate_code_button.setEnabled(False)
        self._set_feedback(
            self.pairing_feedback,
            "Generating a secure one-use code…",
        )
        self._request(
            "create_pairing_code",
            on_success=lambda result, serial=request_serial: self._pairing_code_created(
                result,
                serial,
            ),
            on_error=lambda message, serial=request_serial: self._pairing_generation_failed(
                message,
                serial,
            ),
        )

    def toggle_current_network_trust(self):
        if not self._network_available:
            self._set_feedback(
                self.pairing_feedback,
                "Connect this laptop to a local network first.",
                error=True,
            )
            return
        command = (
            "forget_current_network"
            if self._network_trusted
            else "trust_current_network"
        )
        self.network_trust_button.setEnabled(False)
        self._request(
            command,
            on_success=self._network_trust_changed,
            on_error=self._network_trust_failed,
        )

    def _network_trust_changed(self, result):
        payload = result if isinstance(result, dict) else {}
        self._apply_network_status(payload.get("network"))
        self._set_feedback(
            self.pairing_feedback,
            "This network is trusted for discovery and six-digit pairing."
            if self._network_trusted
            else "This network is no longer trusted. Localhost remains available.",
        )

    def _network_trust_failed(self, message):
        self.network_trust_button.setEnabled(self._network_available)
        self._set_feedback(
            self.pairing_feedback,
            f"Could not change network trust: {self._safe_error(message)}",
            error=True,
        )

    def _apply_network_status(self, value):
        if not isinstance(value, dict):
            # Compatibility with a manager connected to an older local service.
            self._network_available = False
            self._network_trusted = False
            self.network_name_label.setText("Discovery unavailable")
            self.network_trust_label.setText(
                "This server version does not support trusted-LAN discovery. "
                "Use the advanced recovery setup code."
            )
            self.network_trust_button.setEnabled(False)
            self.generate_code_button.setEnabled(
                not self._pairing_request_pending
            )
            return
        self._network_available = bool(value.get("available"))
        self._network_trusted = bool(value.get("trusted"))
        self.network_name_label.setText(
            str(value.get("name") or "No active local network")
        )
        if not self._network_available:
            detail = "Localhost is available, but no LAN is connected."
            button_text = "Trust this network"
        elif self._network_trusted:
            detail = "Trusted — nearby computers can discover this server for pairing."
            button_text = "Remove trust"
        else:
            detail = "Not trusted — localhost works, but new-device discovery is off."
            button_text = "Trust this network"
        self.network_trust_label.setText(detail)
        self.network_trust_button.setText(button_text)
        self.network_trust_button.setEnabled(self._network_available)
        self.generate_code_button.setEnabled(
            not self._pairing_request_pending
        )

    def _pairing_code_created(self, result, request_serial=None):
        if (
            request_serial is not None
            and request_serial != self._pairing_request_serial
        ):
            return
        self._pairing_request_pending = False
        self.generate_code_button.setEnabled(True)
        result = result if isinstance(result, dict) else {}
        code = str(result.get("code", "")).strip()
        setup_code = str(result.get("setup_code", "")).strip()
        if (
            len(code) != 6
            or not code.isdigit()
            or not setup_code.startswith(PAIRING_PACKAGE_PREFIX)
        ):
            self._clear_pairing_code()
            self._set_feedback(
                self.pairing_feedback,
                "The server returned incomplete automatic pairing details.",
                error=True,
            )
            return
        self._current_pairing_code = code
        self._current_setup_code = setup_code
        self.pairing_code_label.setText(" ".join(code))
        self.copy_code_button.setEnabled(True)
        self._pairing_expires_at = self._parse_datetime(result.get("expires_at"))
        if self._pairing_expires_at is None:
            try:
                lifetime = max(0, int(result.get("lifetime_seconds") or 600))
            except (TypeError, ValueError):
                self._clear_pairing_code()
                self._set_feedback(
                    self.pairing_feedback,
                    "The server returned an invalid pairing-code expiry.",
                    error=True,
                )
                return
            self._pairing_expires_at = datetime.fromtimestamp(
                time.time() + lifetime,
                tz=timezone.utc,
            )
        self._set_feedback(
            self.pairing_feedback,
            (
                "Pairing is ready. On the other computer, enter only these six digits."
                if self._network_trusted
                else "Code ready for this laptop. Trust the current network to let "
                "other computers discover the server."
            ),
        )
        self._update_pairing_countdown()

    def _pairing_generation_failed(self, message, request_serial=None):
        if (
            request_serial is not None
            and request_serial != self._pairing_request_serial
        ):
            return
        self._pairing_request_pending = False
        self.generate_code_button.setEnabled(True)
        self._clear_pairing_code()
        self._set_feedback(
            self.pairing_feedback,
            f"Could not generate a pairing code: {self._safe_error(message)}",
            error=True,
        )

    def _clear_pairing_code(self, expiry_text="No active pairing code"):
        self._pairing_expires_at = None
        self._current_pairing_code = ""
        self._current_setup_code = ""
        self.pairing_code_label.setText("— — — — — —")
        self.pairing_expiry_label.setText(expiry_text)
        self.copy_code_button.setEnabled(False)

    def copy_pairing_code(self):
        if not self._current_setup_code:
            return
        if self._copy_text_to_clipboard(self._current_setup_code):
            self._set_feedback(
                self.pairing_feedback,
                "Advanced recovery setup code copied.",
            )
        else:
            self._set_feedback(
                self.pairing_feedback,
                "Windows could not access the clipboard. Please try again.",
                error=True,
            )

    def _update_pairing_countdown(self):
        if self._pairing_expires_at is None:
            return
        remaining = int(
            (self._pairing_expires_at - datetime.now(timezone.utc)).total_seconds()
        )
        if remaining <= 0:
            self._clear_pairing_code("Pairing code expired")
            return
        minutes, seconds = divmod(remaining, 60)
        self.pairing_expiry_label.setText(
            f"Expires in {minutes}:{seconds:02d} • one use"
        )

    def refresh_status(self):
        if self._status_request_pending or self._restart_poll_active:
            return
        self._status_request_pending = True
        self.refresh_status_button.setEnabled(False)
        self._request(
            "get_status",
            on_success=self._status_loaded,
            on_error=self._status_failed,
        )

    def _status_loaded(self, result):
        self._status_request_pending = False
        if self._restart_poll_active:
            # This response was requested before the restart was accepted, so it
            # cannot be used as post-restart readiness evidence.
            self.refresh_status_button.setEnabled(False)
            self._schedule_restart_poll(0)
            return
        self.refresh_status_button.setEnabled(True)
        self._apply_status(result)

    def _apply_status(self, result):
        status = result if isinstance(result, dict) else {}
        self._cached_status = status
        state = self._normalize_server_state(status.get("state"))
        self._set_server_state(state)
        self._apply_network_status(status.get("network"))

        address = self._address_from_status(status)
        if address:
            self._set_server_address(address)
        cpu = status.get("server_process_cpu_percent")
        memory_bytes = status.get("server_process_memory_bytes")

        self.status_cards["version"].set_value(status.get("app_version"))
        self.status_cards["address"].set_value(self._server_address or None)
        self.status_cards["uptime"].set_value(
            self._format_uptime(status.get("uptime_seconds"))
        )
        self.status_cards["cpu"].set_value(
            "—" if cpu is None else f"{float(cpu):.1f}%"
        )
        self.status_cards["ram"].set_value(
            "—" if memory_bytes is None else self._format_bytes(memory_bytes)
        )
        database_present = status.get("database_file_present")
        if not isinstance(database_present, bool):
            database_present = status.get("database_ready")
        self.status_cards["database"].set_value(
            "Present"
            if database_present is True
            else "Missing"
            if database_present is False
            else None
        )
        self.status_feedback.setToolTip("")
        self._set_feedback(
            self.status_feedback,
            f"Service PID {status.get('pid')}"
            if status.get("pid")
            else "Server details updated",
        )
        return state

    def _status_failed(self, message):
        self._status_request_pending = False
        if self._restart_poll_active:
            self.refresh_status_button.setEnabled(False)
            self._schedule_restart_poll(0)
            return
        self.refresh_status_button.setEnabled(True)
        self._apply_status_failure(message)

    def _apply_status_failure(self, message):
        self._set_server_state("unavailable")
        self._network_available = False
        self._network_trusted = False
        self.network_name_label.setText("Network status unavailable")
        self.network_trust_label.setText(
            "Local network controls will return when the service reconnects."
        )
        self.network_trust_button.setEnabled(False)
        self.generate_code_button.setEnabled(False)
        self._clear_live_status_values()
        self._set_feedback(
            self.status_feedback,
            "The manager could not contact the server. It will retry automatically.",
            error=True,
        )
        self.status_feedback.setToolTip(self._safe_error(message))

    def _clear_live_status_values(self):
        for key in ("uptime", "cpu", "ram", "database"):
            self.status_cards[key].set_value(None)

    @staticmethod
    def _normalize_server_state(state):
        normalized = str(state or "unavailable").strip().casefold()
        if normalized in {
            "starting",
            "running",
            "restarting",
            "stopping",
            "unavailable",
        }:
            return normalized
        return "unavailable"

    def _set_server_state(self, state):
        state = self._normalize_server_state(state)
        text = {
            "starting": "Starting…",
            "running": "Running",
            "restarting": "Restarting…",
            "stopping": "Stopping…",
            "unavailable": "Unavailable",
        }[state]
        visual_state = (
            "running"
            if state == "running"
            else "transitional"
            if state in {"starting", "restarting", "stopping"}
            else "error"
        )
        self.header_status.setText(text)
        self.header_status.setProperty("state", visual_state)
        self.header_status.style().unpolish(self.header_status)
        self.header_status.style().polish(self.header_status)
        self.server_state_changed.emit(state)

    @staticmethod
    def _address_from_status(status):
        supplied = str(status.get("server_address") or "").strip()
        if supplied:
            return supplied
        hostname = str(status.get("hostname") or "").strip()
        try:
            port = int(status.get("port"))
        except (TypeError, ValueError):
            return ""
        if not hostname or not 1 <= port <= 65535:
            return ""
        return f"https://{hostname}:{port}"

    def _set_server_address(self, address):
        address = str(address or "").strip()
        if not address:
            return
        was_available = bool(self._server_address)
        self._server_address = address
        self.status_cards["address"].set_value(address)
        self.copy_address_button.setEnabled(True)
        if not was_available:
            self.server_address_availability_changed.emit(True)

    @property
    def server_address_available(self):
        return bool(self._server_address)

    def refresh_devices(self):
        self._devices_request_serial += 1
        request_serial = self._devices_request_serial
        self.refresh_devices_button.setEnabled(False)
        self._set_feedback(self.devices_feedback, "Loading paired devices…")
        self._request(
            "list_devices",
            on_success=lambda result, serial=request_serial: self._devices_loaded(
                result,
                serial,
            ),
            on_error=lambda message, serial=request_serial: self._devices_failed(
                serial,
                message,
            ),
        )

    def _devices_loaded(self, result, request_serial=None):
        if (
            request_serial is not None
            and request_serial != self._devices_request_serial
        ):
            return
        self.refresh_devices_button.setEnabled(True)
        if isinstance(result, dict):
            devices = result.get("devices", [])
        else:
            devices = result
        devices = devices if isinstance(devices, list) else []
        # Dropping all rows first is intentional: QTableWidget otherwise keeps
        # old cell widgets when an active row becomes revoked or rows reorder.
        self.devices_table.setRowCount(0)
        self.devices_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            device = device if isinstance(device, dict) else {}
            name = str(device.get("device_name") or "Unnamed computer")
            state = str(
                device.get("state")
                or (
                    "revoked"
                    if device.get("revoked_at")
                    else "pending"
                    if device.get("pending_confirmation")
                    else "active"
                )
            ).title()
            created = self._format_date(device.get("created_at"))
            self.devices_table.setItem(row, 0, QTableWidgetItem(name))
            self.devices_table.setItem(row, 1, QTableWidgetItem(state))
            self.devices_table.setItem(row, 2, QTableWidgetItem(created))
            if state.casefold() != "revoked":
                revoke = self._button("Revoke", icon_name="shield-off", danger=True)
                revoke.setProperty(
                    "device_id",
                    str(device.get("device_id") or ""),
                )
                revoke.clicked.connect(
                    lambda checked=False, item=dict(device), button=revoke: (
                        self._confirm_and_revoke(item, button)
                    )
                )
                self.devices_table.setCellWidget(row, 3, revoke)
            self.devices_table.setRowHeight(row, 39)
        self._set_feedback(
            self.devices_feedback,
            f"{len(devices)} paired device{'s' if len(devices) != 1 else ''}"
        )

    def _devices_failed(self, request_serial, message):
        if request_serial != self._devices_request_serial:
            return
        self._action_failed(
            self.refresh_devices_button,
            self.devices_feedback,
            message,
        )

    def _confirm_and_revoke(self, device, button=None):
        device_id = str(device.get("device_id") or "")
        device_name = str(device.get("device_name") or "this computer")
        if not device_id or not self.confirm_revoke(device_name):
            return
        if button is not None:
            button.setEnabled(False)
        self._set_feedback(self.devices_feedback, f"Revoking {device_name}…")
        self._request(
            "revoke_device",
            {"device_id": device_id},
            on_success=lambda result: self._device_revoked(device_name, result),
            on_error=lambda message: self._device_revoke_failed(
                device_name,
                device_id,
                message,
            ),
        )

    def _device_revoke_failed(self, device_name, device_id, message):
        for row in range(self.devices_table.rowCount()):
            button = self.devices_table.cellWidget(row, 3)
            if (
                button is not None
                and button.property("device_id") == device_id
            ):
                button.setEnabled(True)
                break
        self._set_feedback(
            self.devices_feedback,
            f"Could not revoke {device_name}: {self._safe_error(message)}",
            error=True,
        )

    def _device_revoked(self, device_name, result):
        _ = result
        self._set_feedback(self.devices_feedback, f"{device_name} was revoked.")
        self.refresh_devices()

    def restart_server(self):
        if self._restart_poll_active or not self.confirm_restart():
            return
        self.restart_button.setEnabled(False)
        self._set_feedback(
            self.tools_feedback,
            "Requesting an API runtime restart…",
        )
        self._request(
            "restart_server",
            on_success=self._restart_request_accepted,
            on_error=lambda message: self._action_failed(
                self.restart_button,
                self.tools_feedback,
                message,
            ),
        )

    def _restart_request_accepted(self, result):
        if not isinstance(result, dict) or result.get("accepted") is not True:
            self._action_failed(
                self.restart_button,
                self.tools_feedback,
                "The server did not accept the restart request.",
            )
            return
        self._restart_poll_active = True
        self._restart_deadline = time.monotonic() + RESTART_VERIFY_TIMEOUT_SECONDS
        self.refresh_status_button.setEnabled(False)
        self._set_server_state("restarting")
        self._set_feedback(
            self.tools_feedback,
            "Restart requested. Waiting for the API to report Running…",
        )
        self._schedule_restart_poll(RESTART_POLL_INTERVAL_MS)

    def _schedule_restart_poll(self, delay_ms=RESTART_POLL_INTERVAL_MS):
        if not self._restart_poll_active:
            return
        self.restart_poll_timer.start(max(0, int(delay_ms)))

    def _poll_restart_status(self):
        if not self._restart_poll_active:
            return
        if time.monotonic() >= self._restart_deadline:
            self._restart_verification_timed_out()
            return
        if self._status_request_pending:
            self._schedule_restart_poll()
            return
        self._status_request_pending = True
        self.refresh_status_button.setEnabled(False)
        self._request(
            "get_status",
            on_success=self._restart_status_loaded,
            on_error=self._restart_status_failed,
        )

    def _restart_status_loaded(self, result):
        self._status_request_pending = False
        state = self._apply_status(result)
        if not self._restart_poll_active:
            return
        if state == "running":
            self._restart_poll_active = False
            self.restart_poll_timer.stop()
            self.restart_button.setEnabled(True)
            self.refresh_status_button.setEnabled(True)
            self._set_feedback(
                self.tools_feedback,
                "API restart verified. The server is running.",
            )
            return
        if time.monotonic() >= self._restart_deadline:
            self._restart_verification_timed_out()
            return
        state_label = self.header_status.text().rstrip("…").casefold()
        self._set_feedback(
            self.tools_feedback,
            f"The API is {state_label}. Waiting for it to report Running…",
        )
        self._schedule_restart_poll()

    def _restart_status_failed(self, message):
        self._status_request_pending = False
        self._apply_status_failure(message)
        if time.monotonic() >= self._restart_deadline:
            self._restart_verification_timed_out()
            return
        self.refresh_status_button.setEnabled(False)
        self._set_feedback(
            self.tools_feedback,
            "The API is temporarily unavailable. Waiting for it to report Running…",
        )
        self._schedule_restart_poll()

    def _restart_verification_timed_out(self):
        self._restart_poll_active = False
        self.restart_poll_timer.stop()
        self.restart_button.setEnabled(True)
        self.refresh_status_button.setEnabled(True)
        self._set_feedback(
            self.tools_feedback,
            "The restart was requested, but the API did not report Running "
            f"within {RESTART_VERIFY_TIMEOUT_SECONDS} seconds.",
            error=True,
        )

    def create_verified_backup(self):
        self.backup_button.setEnabled(False)
        self.tools_feedback.setText("Creating and verifying a database backup…")
        self._request(
            "create_verified_backup",
            on_success=self._backup_created,
            on_error=lambda message: self._action_failed(
                self.backup_button,
                self.tools_feedback,
                message,
            ),
        )

    def _backup_created(self, result):
        self.backup_button.setEnabled(True)
        result = result if isinstance(result, dict) else {}
        filename = str(result.get("filename") or "backup")
        self._set_feedback(
            self.tools_feedback,
            f"Verified backup created: {filename}",
        )

    def copy_server_address(self):
        if not self._server_address:
            self._set_feedback(
                self.tools_feedback,
                "The server address is not available yet.",
                error=True,
            )
            return False
        if not self._copy_text_to_clipboard(self._server_address):
            self._set_feedback(
                self.tools_feedback,
                "Windows could not access the clipboard. Please try again.",
                error=True,
            )
            return False
        self._set_feedback(self.tools_feedback, "Server address copied.")
        return True

    def open_public_ca_folder(self):
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(PUBLIC_CA_FOLDER)))
        self._set_feedback(
            self.tools_feedback,
            "Opened the public certificate folder."
            if opened
            else "Windows could not open the public certificate folder.",
            error=not opened,
        )

    def copy_support_summary(self):
        self.support_button.setEnabled(False)
        self.tools_feedback.setText("Preparing a sanitized support summary…")
        self._request(
            "get_support_summary",
            on_success=self._support_summary_ready,
            on_error=lambda message: self._action_failed(
                self.support_button,
                self.tools_feedback,
                message,
            ),
        )

    def _support_summary_ready(self, result):
        self.support_button.setEnabled(True)
        result = result if isinstance(result, dict) else {}
        safe = {
            "generated_at": result.get("generated_at"),
            "status": self._safe_status_summary(result.get("status")),
            "device_counts": self._safe_device_counts(result.get("device_counts")),
            "latest_backup": self._safe_backup_summary(result.get("latest_backup")),
        }
        copied = self._copy_text_to_clipboard(
            json.dumps(safe, indent=2, sort_keys=True, default=str)
        )
        self._set_feedback(
            self.tools_feedback,
            (
                "Sanitized support summary copied."
                if copied
                else "Windows could not access the clipboard. Please try again."
            ),
            error=not copied,
        )

    @staticmethod
    def _safe_status_summary(value):
        value = value if isinstance(value, dict) else {}
        allowed = (
            "state",
            "service_name",
            "pid",
            "hostname",
            "app_version",
            "api_version",
            "schema_version",
            "started_at",
            "uptime_seconds",
            "host",
            "port",
            "database_file_present",
            "database_ready",
        )
        return {key: value.get(key) for key in allowed if key in value}

    @staticmethod
    def _safe_device_counts(value):
        value = value if isinstance(value, dict) else {}
        return {
            key: value.get(key)
            for key in ("active", "pending", "revoked", "total")
            if key in value
        }

    @staticmethod
    def _safe_backup_summary(value):
        if not isinstance(value, dict):
            return None
        return {
            key: value.get(key)
            for key in (
                "created_at",
                "filename",
                "size_bytes",
                "sha256",
                "mirrored",
            )
            if key in value
        }

    def _tool_succeeded(
        self,
        button,
        message,
        result,
        *,
        refresh_delay=None,
    ):
        _ = result
        button.setEnabled(True)
        self._set_feedback(self.tools_feedback, message)
        if refresh_delay is not None:
            QTimer.singleShot(refresh_delay, self.refresh_status)

    def _action_failed(self, button, label, message):
        button.setEnabled(True)
        self._set_feedback(
            label,
            f"Action failed: {self._safe_error(message)}",
            error=True,
        )

    def _request(self, command, arguments=None, *, on_success, on_error):
        self.request_runner.submit(
            lambda: self.management_client.request(command, arguments),
            on_success,
            on_error,
        )

    def _tab_changed(self, index):
        if self.tabs.widget(index) is self.devices_tab:
            self.refresh_devices()
        elif self.tabs.widget(index) is self.status_tab:
            self.refresh_status()
        elif self.tabs.widget(index) is self.updates_tab and self.update_service.enabled:
            if self._available_update is None:
                self.check_for_updates()

    def show_pairing(self, *, generate=False):
        self.tabs.setCurrentWidget(self.pairing_tab)
        self.show_and_activate()
        if generate:
            self.generate_pairing_code()

    def show_and_activate(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def eventFilter(self, watched, event):
        if (
            watched is self.title_bar.drag_region
            and event.type() == QEvent.MouseButtonDblClick
        ):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def request_exit(self):
        """Allow explicit tray exit to close only this manager process."""

        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent):
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()

    def _default_confirm_revoke(self, device_name):
        return (
            QMessageBox.question(
                self,
                "Revoke device",
                f"Revoke access for {device_name}?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            == QMessageBox.Yes
        )

    def _default_confirm_restart(self):
        return (
            QMessageBox.question(
                self,
                "Restart API runtime",
                "Restart the Mission Legal API runtime now? Connected users may pause "
                "briefly, but the Windows service will remain running.",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            == QMessageBox.Yes
        )

    @staticmethod
    def _set_feedback(label, text, *, error=False):
        label.setText(text)
        label.setProperty("error", bool(error))
        label.style().unpolish(label)
        label.style().polish(label)

    @staticmethod
    def _safe_error(message):
        text = str(message or "Unknown error").replace("\r", " ").replace("\n", " ")
        return text[:240]

    @staticmethod
    def _copy_text_to_clipboard(text):
        """Set and verify clipboard text, tolerating short Windows lock races."""

        value = str(text)
        clipboard = QGuiApplication.clipboard()
        for attempt in range(5):
            clipboard.setText(value)
            if clipboard.text() == value:
                return True
            if attempt < 4:
                time.sleep(0.04)
        return False

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _format_date(value):
        parsed = ServerManagerWindow._parse_datetime(value)
        if parsed is None:
            return "—"
        return parsed.astimezone().strftime("%Y-%m-%d")

    @staticmethod
    def _format_uptime(value):
        try:
            seconds = max(0, int(value))
        except (TypeError, ValueError):
            return "—"
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @staticmethod
    def _format_bytes(value):
        try:
            size = float(value)
        except (TypeError, ValueError):
            return "—"
        for suffix in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or suffix == "TB":
                return f"{size:.0f} {suffix}" if suffix == "B" else f"{size:.1f} {suffix}"
            size /= 1024
        return "—"

    def _apply_local_style(self):
        self.setStyleSheet(
            """
            QWidget#ServerManagerOuter {
                background: transparent;
            }
            QFrame#ServerManagerSurface {
                background-color: #FFFFFF;
                border: 1px solid #DADADF;
                border-radius: 18px;
            }
            QFrame#ServerManagerSurface QFrame#AppTitleBar {
                background-color: #FBFBFC;
                border: none;
                border-bottom: 1px solid #ECECEC;
                border-top-left-radius: 18px;
                border-top-right-radius: 18px;
            }
            QWidget#ServerManagerContent,
            QWidget#ServerManagerPage {
                background-color: #FFFFFF;
            }
            QLabel#ServerManagerTitle {
                color: #27272A;
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }
            QLabel#ServerManagerHeading {
                color: #18181B;
                font-size: 18px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#ServerStateBadge {
                color: #71717A;
                background-color: #F4F4F5;
                border: 1px solid #E4E4E7;
                border-radius: 13px;
                padding: 4px 11px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#ServerStateBadge[state="running"] {
                color: #047857;
                background-color: #ECFDF5;
                border-color: #A7F3D0;
            }
            QLabel#ServerStateBadge[state="transitional"] {
                color: #92400E;
                background-color: #FFFBEB;
                border-color: #FDE68A;
            }
            QLabel#ServerStateBadge[state="error"] {
                color: #B91C1C;
                background-color: #FEF2F2;
                border-color: #FECACA;
            }
            QTabWidget#ServerManagerTabs::pane {
                background-color: #FFFFFF;
                border: 1px solid #ECECEC;
                border-radius: 14px;
                top: 5px;
            }
            QTabWidget#ServerManagerTabs QTabBar {
                background: transparent;
            }
            QTabWidget#ServerManagerTabs QTabBar::tab {
                color: #71717A;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 15px;
                min-height: 30px;
                padding: 0 15px;
                margin-right: 4px;
                font-size: 12px;
                font-weight: 500;
            }
            QTabWidget#ServerManagerTabs QTabBar::tab:selected {
                color: #0F5F64;
                background-color: #EFFCFC;
                border-color: #B8ECEE;
                font-weight: 700;
            }
            QTabWidget#ServerManagerTabs QTabBar::tab:hover:!selected {
                color: #27272A;
                background-color: #F4F4F5;
            }
            QLabel#ServerSectionTitle {
                color: #18181B;
                font-size: 15px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#ServerSectionSubtitle {
                color: #71717A;
                font-size: 11px;
                background: transparent;
            }
            QFrame#PairingCodeCard {
                background-color: #F9F7F4;
                border: 1px solid #E8E2D9;
                border-radius: 22px;
            }
            QLabel#PairingCode {
                color: #0F5F64;
                font-family: "Cascadia Mono", "Consolas", monospace;
                font-size: 32px;
                font-weight: 700;
                letter-spacing: 4px;
                background: transparent;
            }
            QLabel#PairingExpiry,
            QLabel#ServerFeedback {
                color: #71717A;
                font-size: 11px;
                background: transparent;
            }
            QLabel#ServerFeedback[error="true"] {
                color: #B91C1C;
            }
            QPushButton#ServerPillButton,
            QPushButton#ServerPrimaryPill,
            QPushButton#ServerDangerPill {
                border-radius: 17px;
                min-height: 34px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#ServerPillButton {
                color: #0F5F64;
                background-color: #FFFFFF;
                border: 1px solid #9BE3E6;
            }
            QPushButton#ServerPillButton:hover {
                background-color: #EFFCFC;
            }
            QPushButton#ServerPrimaryPill {
                color: #FFFFFF;
                background-color: #0F5F64;
                border: 1px solid #0F5F64;
            }
            QPushButton#ServerPrimaryPill:hover {
                background-color: #0B4F54;
            }
            QPushButton#ServerDangerPill {
                color: #B91C1C;
                background-color: #FFFFFF;
                border: 1px solid #FECACA;
            }
            QPushButton#ServerDangerPill:hover {
                background-color: #FEF2F2;
            }
            QFrame#ServerMetricCard {
                background-color: #FBFBFC;
                border: 1px solid #ECECEC;
                border-radius: 14px;
            }
            QLabel#ServerMetricTitle {
                color: #71717A;
                font-size: 10px;
                background: transparent;
            }
            QLabel#ServerMetricValue {
                color: #18181B;
                font-size: 13px;
                font-weight: 700;
                background: transparent;
            }
            QTableWidget#ServerDevicesTable {
                background-color: #FFFFFF;
                border: 1px solid #ECECEC;
                border-radius: 12px;
                gridline-color: transparent;
            }
            QTableWidget#ServerDevicesTable::item {
                border-bottom: 1px solid #F4F4F5;
                padding: 5px;
            }
            QTableWidget#ServerDevicesTable QHeaderView::section {
                color: #71717A;
                background-color: #FBFBFC;
                border: none;
                border-bottom: 1px solid #ECECEC;
                padding: 6px;
                font-size: 10px;
                font-weight: 600;
            }
            """
        )
