"""First-run pairing dialog for an installed client computer."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRegularExpression, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from services.api_client import ApiCompatibilityError
from services.client_pairing_service import (
    default_device_name,
    discover_pairing_servers,
    pair_client,
    pair_client_from_setup_code,
)
from ui.foundation.fluent import show_message


class _ClientPairingWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, values):
        super().__init__()
        self.values = dict(values)

    @Slot()
    def run(self):
        try:
            setup_code = str(self.values.pop("setup_code", "") or "").strip()
            if setup_code:
                result = pair_client_from_setup_code(
                    setup_code,
                    device_name=self.values.get("device_name"),
                )
            else:
                result = pair_client(**self.values)
        except Exception as exc:
            self.failed.emit(exc)
            return
        self.succeeded.emit(result)


class _ServerDiscoveryWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    @Slot()
    def run(self):
        try:
            servers = self.provider()
        except Exception as exc:
            self.failed.emit(exc)
            return
        self.succeeded.emit(tuple(servers or ()))


class ClientPairingDialog(QDialog):
    """Connect a client with a six-digit code and automatic LAN discovery."""

    def __init__(self, parent=None, *, discovery_provider=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._pending_result = None
        self._pending_error = None
        self._checking_updates = False
        self._discovery_thread = None
        self._discovery_worker = None
        self._discovery_pending_result = None
        self._discovery_pending_error = None
        self._discovery_started = False
        self.discovery_provider = discovery_provider or discover_pairing_servers
        self.pairing_result = None
        self.update_scheduled = False
        self._manual_setup_visible = False

        self.setWindowTitle("Connect Mission Legal to the Main Computer")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "On the main computer, trust the current network and generate a "
            "six-digit pairing code. Mission Legal will find that computer "
            "automatically."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.pairing_form = form
        server_row = QHBoxLayout()
        self.server_combo = QComboBox()
        self.server_combo.setAccessibleName("Discovered Mission Legal server")
        self.server_combo.addItem("Searching for the main computer…", None)
        server_row.addWidget(self.server_combo, 1)
        self.refresh_button = QPushButton("Search again")
        self.refresh_button.clicked.connect(self.refresh_servers)
        server_row.addWidget(self.refresh_button)
        form.addRow("Main computer", server_row)

        self.code_edit = QLineEdit()
        self.code_edit.setMaxLength(6)
        self.code_edit.setPlaceholderText("123456")
        self.code_edit.setAccessibleName("Six-digit pairing code")
        self.code_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,6}"), self)
        )
        form.addRow("Pairing code", self.code_edit)

        self.device_edit = QLineEdit(default_device_name())
        self.device_edit.setMaxLength(100)
        self.device_edit.setAccessibleName("Computer name")
        form.addRow("Computer name", self.device_edit)

        self.advanced_button = QPushButton("Advanced recovery")
        self.advanced_button.clicked.connect(self._toggle_manual_setup)
        form.addRow("", self.advanced_button)

        self.setup_code_edit = QPlainTextEdit()
        self.setup_code_edit.setPlaceholderText(
            "Paste the advanced recovery setup code copied from Server Manager"
        )
        self.setup_code_edit.setAccessibleName("Mission Legal setup code")
        self.setup_code_edit.setFixedHeight(92)
        form.addRow("Recovery setup code", self.setup_code_edit)

        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("https://MAIN-COMPUTER:8765")
        self.server_edit.setAccessibleName("Mission Legal server address")
        form.addRow("Server address", self.server_edit)

        certificate_row = QHBoxLayout()
        self.certificate_edit = QLineEdit()
        self.certificate_edit.setPlaceholderText("Choose mission-legal-ca.pem")
        self.certificate_edit.setAccessibleName("Mission Legal CA certificate")
        certificate_row.addWidget(self.certificate_edit, 1)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_certificate)
        certificate_row.addWidget(self.browse_button)
        form.addRow("CA certificate", certificate_row)
        layout.addLayout(form)
        self._manual_row_indexes = (4, 5, 6)
        for row in self._manual_row_indexes:
            form.setRowVisible(row, False)

        self.status_label = QLabel("Searching for the main computer on this network…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.check_updates_button = QPushButton("Check for updates")
        self.check_updates_button.clicked.connect(self._check_for_updates)
        actions.addWidget(self.check_updates_button)
        actions.addStretch(1)
        self.cancel_button = QPushButton("Exit")
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.cancel_button)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setDefault(True)
        self.connect_button.clicked.connect(self._start_pairing)
        actions.addWidget(self.connect_button)
        layout.addLayout(actions)

    @property
    def busy(self):
        return self._checking_updates or (
            self._thread is not None and self._thread.isRunning()
        ) or (
            self._discovery_thread is not None
            and self._discovery_thread.isRunning()
        )

    def showEvent(self, event):
        super().showEvent(event)
        if not self._discovery_started:
            self.refresh_servers()

    @Slot()
    def refresh_servers(self):
        if self._discovery_thread is not None:
            return
        self._discovery_started = True
        self._discovery_pending_result = None
        self._discovery_pending_error = None
        self.server_combo.clear()
        self.server_combo.addItem("Searching for the main computer…", None)
        self.server_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.status_label.setText(
            "Searching for Mission Legal on this computer and trusted local networks…"
        )

        thread = QThread(self)
        worker = _ServerDiscoveryWorker(self.discovery_provider)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._store_discovered_servers)
        worker.failed.connect(self._store_discovery_failure)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._discovery_finished)
        thread.finished.connect(thread.deleteLater)
        self._discovery_thread = thread
        self._discovery_worker = worker
        thread.start()

    @Slot(object)
    def _store_discovered_servers(self, servers):
        self._discovery_pending_result = tuple(servers or ())
        if self._discovery_thread is not None:
            self._discovery_thread.quit()

    @Slot(object)
    def _store_discovery_failure(self, error):
        self._discovery_pending_error = error
        if self._discovery_thread is not None:
            self._discovery_thread.quit()

    @Slot()
    def _discovery_finished(self):
        servers = self._discovery_pending_result or ()
        error = self._discovery_pending_error
        self._discovery_worker = None
        self._discovery_thread = None
        self.server_combo.clear()
        for server in servers:
            name = str(getattr(server, "name", "") or "").strip()
            address = str(getattr(server, "server_url", "") or "").strip()
            certificate = str(
                getattr(server, "ca_certificate_pem", "") or ""
            ).strip()
            if name and address and certificate:
                self.server_combo.addItem(name, server)
        available = self.server_combo.count() > 0
        if not available:
            self.server_combo.addItem("No trusted Mission Legal server found", None)
        self.server_combo.setEnabled(available)
        self.refresh_button.setEnabled(True)
        if available:
            self.status_label.setText(
                "Server found. Enter the six-digit code shown in Server Manager."
            )
            self.code_edit.setFocus()
        elif error:
            self.status_label.setText(
                f"The server search failed. Try again or use Advanced recovery. {error}"
            )
        else:
            self.status_label.setText(
                "No server was found. Confirm that both computers are on the same "
                "trusted network, then search again."
            )

    @Slot()
    def _browse_certificate(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose the Mission Legal CA Certificate",
            "",
            "Certificate files (*.pem *.crt *.cer);;All files (*)",
        )
        if path:
            self.certificate_edit.setText(path)

    @Slot()
    def _toggle_manual_setup(self):
        self._manual_setup_visible = not self._manual_setup_visible
        for row in self._manual_row_indexes:
            self.pairing_form.setRowVisible(row, self._manual_setup_visible)
        self.advanced_button.setText(
            "Hide advanced recovery"
            if self._manual_setup_visible
            else "Advanced recovery"
        )

    @Slot()
    def _start_pairing(self):
        if self.busy:
            return
        setup_code = (
            self.setup_code_edit.toPlainText().strip()
            if self._manual_setup_visible
            else ""
        )
        if setup_code:
            values = {
                "setup_code": setup_code,
                "device_name": self.device_edit.text(),
            }
            missing = not values["device_name"].strip()
        else:
            discovered = self.server_combo.currentData()
            if discovered is not None:
                server_url = getattr(discovered, "server_url", "")
                certificate = getattr(discovered, "ca_certificate_pem", "")
            else:
                server_url = (
                    self.server_edit.text() if self._manual_setup_visible else ""
                )
                certificate = (
                    self.certificate_edit.text()
                    if self._manual_setup_visible
                    else ""
                )
            values = {
                "server_url": server_url,
                "certificate": certificate,
                "pairing_code": self.code_edit.text(),
                "device_name": self.device_edit.text(),
            }
            missing = not all(str(value).strip() for value in values.values())
        if missing:
            show_message(
                self,
                "Pairing Information Required",
                "Select the discovered main computer, enter all six digits, and "
                "confirm this computer's name. Advanced recovery remains available "
                "when local discovery is blocked.",
                kind="warning",
            )
            return

        self._set_busy(True)
        self._pending_result = None
        self._pending_error = None
        self.status_label.setText(
            "Checking the encrypted connection and pairing this computer..."
        )

        thread = QThread(self)
        worker = _ClientPairingWorker(values)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._store_success)
        worker.failed.connect(self._store_failure)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._pairing_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(object)
    def _store_success(self, result):
        self._pending_result = result
        if self._thread is not None:
            self._thread.quit()

    @Slot(object)
    def _store_failure(self, detail):
        self._pending_error = detail
        if self._thread is not None:
            self._thread.quit()

    @Slot()
    def _pairing_finished(self):
        result = self._pending_result
        error = self._pending_error
        self._worker = None
        self._thread = None
        self._set_busy(False)
        if result is None:
            if (
                isinstance(error, ApiCompatibilityError)
                and error.client_update_required
            ):
                self._offer_required_update(error)
                return
            detail = str(error or "Pairing failed.")
            self.status_label.setText(
                "This computer was not paired. Check the details and retry."
            )
            show_message(
                self,
                "Mission Legal Pairing Failed",
                detail,
                kind="warning",
            )
            return

        self.pairing_result = result
        self.status_label.setText("This computer is paired and ready to open Mission Legal.")
        show_message(
            self,
            "Mission Legal Is Connected",
            "This computer was paired successfully.",
            kind="information",
        )
        self.accept()

    @Slot()
    def _check_for_updates(self):
        if self.busy:
            return

        from ui.update_coordinator import offer_optional_client_update

        self._checking_updates = True
        self._set_busy(True)
        self.status_label.setText(
            "Checking for an optional Mission Legal update..."
        )
        try:
            scheduled = offer_optional_client_update(self)
        except Exception as exc:
            scheduled = False
            show_message(
                self,
                "Mission Legal Update Check Failed",
                f"The update check could not be completed.\n\n{exc}",
                kind="warning",
            )
        finally:
            self._checking_updates = False
            self._set_busy(False)

        if scheduled:
            self._finish_for_update()
        else:
            self.status_label.setText(
                "No update was scheduled. You can continue pairing this computer."
            )

    def _offer_required_update(self, error):
        from ui.update_coordinator import offer_required_client_update

        self._checking_updates = True
        self._set_busy(True)
        self.status_label.setText(
            "This client must be updated before it can pair with the main computer."
        )
        try:
            scheduled = offer_required_client_update(
                str(error),
                self,
                required_client_version=error.required_client_version,
            )
        except Exception as exc:
            scheduled = False
            show_message(
                self,
                "Mission Legal Update Failed",
                f"The required update could not be started.\n\n{exc}",
                kind="warning",
            )
        finally:
            self._checking_updates = False
            self._set_busy(False)

        if scheduled:
            self._finish_for_update()
        else:
            self.status_label.setText(
                "The update is still required. Update Mission Legal before retrying pairing."
            )

    def _finish_for_update(self):
        self.update_scheduled = True
        self.status_label.setText(
            "Closing Mission Legal so the update can be installed..."
        )
        # This exits the first-run dialog. main.py observes update_scheduled and
        # returns without starting the normal Qt event loop, allowing Velopack's
        # external updater to replace the client and restart it cleanly.
        self.accept()

    def _set_busy(self, busy):
        enabled = not bool(busy)
        for widget in (
            self.setup_code_edit,
            self.server_combo,
            self.refresh_button,
            self.server_edit,
            self.certificate_edit,
            self.code_edit,
            self.device_edit,
            self.browse_button,
            self.advanced_button,
            self.check_updates_button,
            self.connect_button,
            self.cancel_button,
        ):
            widget.setEnabled(enabled)

    def reject(self):
        if self.busy:
            self.status_label.setText(
                "Pairing is still in progress. Wait for it to finish before exiting."
            )
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent):
        if self.busy:
            self.status_label.setText(
                "Pairing is still in progress. Wait for it to finish before exiting."
            )
            event.ignore()
            return
        super().closeEvent(event)
