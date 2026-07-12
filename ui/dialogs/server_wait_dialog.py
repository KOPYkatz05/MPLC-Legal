from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from ui.foundation import create_button


class ServerWaitDialog(QDialog):
    def __init__(self, api_client, detail="", parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._allow_close = False
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
            self.api_client.health()
            self.api_client.session()
        except Exception as exc:
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
