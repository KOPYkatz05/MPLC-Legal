from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from utils.i18n import tr, field_label


APPOINTMENT_FIELDS = {
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
}


class UploadSummaryDialog(QDialog):
    def __init__(
        self,
        updated_fields,
        missing_docs,
        parent=None,
        has_appointment_update=False,
    ):
        super().__init__(parent)
        self.has_appointment_update = has_appointment_update
        self._go_calendar = False

        self.setWindowTitle(tr("upload_summary_title"))
        self.setModal(True)
        self.resize(480, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        updated_label = QLabel(tr("upload_summary_updated"))
        updated_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(updated_label)

        updated_list = QListWidget()
        updated_list.setMaximumHeight(120)

        if updated_fields:
            for field in updated_fields:
                item = QListWidgetItem(
                    f"✓ {field_label(field)}"
                )
                item.setForeground(QColor("#059669"))
                updated_list.addItem(item)
        else:
            item = QListWidgetItem("—")
            updated_list.addItem(item)

        layout.addWidget(updated_list)

        missing_label = QLabel(tr("upload_summary_missing"))
        missing_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(missing_label)

        missing_list = QListWidget()
        missing_list.setMaximumHeight(140)

        if missing_docs:
            for doc_key in missing_docs:
                missing_list.addItem(doc_key)
        else:
            item = QListWidgetItem(
                tr("upload_summary_none_missing")
            )
            item.setForeground(QColor("#059669"))
            missing_list.addItem(item)

        layout.addWidget(missing_list)

        buttons = QHBoxLayout()
        self.close_btn = QPushButton("OK")
        self.close_btn.setDefault(True)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)

        if has_appointment_update:
            self.calendar_btn = QPushButton(
                tr("upload_summary_calendar")
            )
            buttons.addWidget(self.calendar_btn)
            self.calendar_btn.clicked.connect(
                self._on_calendar
            )

        layout.addLayout(buttons)
        self.close_btn.clicked.connect(self.accept)

    def _on_calendar(self):
        self._go_calendar = True
        self.accept()

    def wants_calendar(self):
        return self._go_calendar
