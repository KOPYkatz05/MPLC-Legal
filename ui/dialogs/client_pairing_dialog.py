"""First-run pairing dialog for an installed client computer."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRegularExpression, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.client_pairing_service import default_device_name, pair_client


class _ClientPairingWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, values):
        super().__init__()
        self.values = dict(values)

    @Slot()
    def run(self):
        try:
            result = pair_client(**self.values)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class ClientPairingDialog(QDialog):
    """Collect the public CA certificate and one-use server pairing code."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._pending_result = None
        self._pending_error = ""
        self.pairing_result = None

        self.setWindowTitle("Connect Mission Legal to the Main Computer")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Ask the Mission Legal administrator for the server address, the "
            "public Mission Legal CA certificate, and a six-digit one-use "
            "pairing code. Private keys are never copied to this computer."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
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
        layout.addLayout(form)

        self.status_label = QLabel("Nothing is sent until you choose Connect.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
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
        return self._thread is not None and self._thread.isRunning()

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
    def _start_pairing(self):
        if self.busy:
            return
        values = {
            "server_url": self.server_edit.text(),
            "certificate": self.certificate_edit.text(),
            "pairing_code": self.code_edit.text(),
            "device_name": self.device_edit.text(),
        }
        if not all(str(value).strip() for value in values.values()):
            QMessageBox.warning(
                self,
                "Pairing Information Required",
                "Enter the server address, certificate, pairing code, and "
                "computer name.",
            )
            return

        self._set_busy(True)
        self._pending_result = None
        self._pending_error = ""
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

    @Slot(str)
    def _store_failure(self, detail):
        self._pending_error = str(detail or "Pairing failed.")
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
            self.status_label.setText("This computer was not paired. Check the details and retry.")
            QMessageBox.warning(
                self,
                "Mission Legal Pairing Failed",
                error or "The server did not complete pairing.",
            )
            return

        self.pairing_result = result
        self.status_label.setText("This computer is paired and ready to open Mission Legal.")
        QMessageBox.information(
            self,
            "Mission Legal Is Connected",
            "This computer was paired successfully.",
        )
        self.accept()

    def _set_busy(self, busy):
        enabled = not bool(busy)
        for widget in (
            self.server_edit,
            self.certificate_edit,
            self.code_edit,
            self.device_edit,
            self.browse_button,
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
