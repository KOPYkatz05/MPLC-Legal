from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from services.api_client import ApiCompatibilityError
from ui.foundation import create_button


class ServerWaitDialog(QDialog):
    def __init__(self, api_client, detail="", parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._allow_close = False
        self._required_client_version = None
        self.setWindowTitle("Mission Legal Server Unavailable")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        title = QLabel("Waiting for the main Mission Legal computer")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        retry = create_button("Retry now", "primary")
        retry.clicked.connect(self.retry)
        layout.addWidget(retry)

        self.update_button = create_button("Download required update", "primary")
        self.update_button.clicked.connect(self._download_required_update)
        self.update_button.hide()
        layout.addWidget(self.update_button)

        exit_button = create_button("Exit Mission Legal", "secondary")
        exit_button.clicked.connect(self._exit_application)
        layout.addWidget(exit_button)

        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.retry)
        self.set_detail(detail)

    def set_detail(self, detail):
        self.detail_label.setText(
            "The additional computer will not use a local database. "
            "Start the main computer and Mission Legal Server; this window "
            f"will retry automatically.\n\n{detail}"
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            event.ignore()

    def retry(self):
        try:
            health = self.api_client.health()
            self.api_client.validate_compatibility(health)
            session = self.api_client.session()
            self.api_client.validate_compatibility(session)
        except ApiCompatibilityError as exc:
            self._required_client_version = exc.required_client_version
            if exc.client_update_required:
                self.timer.stop()
                self.setWindowTitle("Mission Legal Update Required")
                self.detail_label.setText(str(exc))
                self.update_button.show()
            else:
                self.update_button.hide()
                title = (
                    "Mission Legal Server Update Required"
                    if exc.reason == ApiCompatibilityError.SERVER_UPDATE_REQUIRED
                    else "Mission Legal Compatibility Error"
                )
                self.setWindowTitle(title)
                self.detail_label.setText(
                    f"{exc}\n\nUpdate or repair Mission Legal Server on the "
                    "main computer. This window will retry automatically."
                )
            return
        except Exception as exc:
            self._required_client_version = None
            self.setWindowTitle("Mission Legal Server Unavailable")
            self.update_button.hide()
            self.timer.start()
            self.set_detail(str(exc))
            return
        self.timer.stop()
        self._allow_close = True
        self.accept()

    def _exit_application(self):
        from PySide6.QtWidgets import QApplication

        self._allow_close = True
        self.reject()
        QApplication.quit()

    def _download_required_update(self):
        from PySide6.QtWidgets import QApplication
        from ui.update_coordinator import offer_required_client_update

        detail = self.detail_label.text()
        self._allow_close = True
        self.accept()
        offer_required_client_update(
            detail,
            self.parentWidget(),
            required_client_version=self._required_client_version,
        )
        QApplication.quit()
