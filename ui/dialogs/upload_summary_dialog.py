from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
)

from PySide6.QtGui import QColor

from ui.foundation import create_button, create_list_widget, setup_dialog_shell
from utils.i18n import tr, field_label


class UploadSummaryDialog(QDialog):
    def __init__(
        self,
        updated_fields,
        missing_docs,
        parent=None,
        has_appointment_update=False,
        uploaded_count=None,
        failed_count=None,
        skipped_count=None,
    ):
        super().__init__(parent)
        self.has_appointment_update = has_appointment_update
        self._go_calendar = False

        self.setWindowTitle(tr("upload_summary_title"))
        self.surface = setup_dialog_shell(
            self,
            surface_width=560,
            surface_min_height=460,
            use_masked_shell=False,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        self.surface.setLayout(layout)

        title = QLabel(tr("upload_summary_title"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        if (
            uploaded_count is not None
            or failed_count is not None
            or skipped_count is not None
        ):
            counts = QLabel(
                "Uploaded: {0}    Failed: {1}    Skipped: {2}".format(
                    uploaded_count if uploaded_count is not None else 0,
                    failed_count if failed_count is not None else 0,
                    skipped_count if skipped_count is not None else 0,
                )
            )
            counts.setObjectName("MutedText")
            layout.addWidget(counts)

        updated_label = QLabel(tr("upload_summary_updated"))
        updated_label.setObjectName("StrongText")
        layout.addWidget(updated_label)

        updated_list = create_list_widget()
        updated_list.setMaximumHeight(120)

        if updated_fields:
            for field in updated_fields:
                item = QListWidgetItem(f"✓ {field_label(field)}")
                item.setForeground(QColor("#059669"))
                updated_list.addItem(item)
        else:
            updated_list.addItem(QListWidgetItem("—"))

        layout.addWidget(updated_list)

        missing_label = QLabel(tr("upload_summary_missing"))
        missing_label.setObjectName("StrongText")
        layout.addWidget(missing_label)

        missing_list = create_list_widget()
        missing_list.setMaximumHeight(160)

        if missing_docs:
            for doc_label in missing_docs:
                missing_list.addItem(doc_label)
        else:
            item = QListWidgetItem(tr("upload_summary_none_missing"))
            item.setForeground(QColor("#059669"))
            missing_list.addItem(item)

        layout.addWidget(missing_list)

        if self.has_appointment_update:
            hint = QLabel(tr("upload_summary_calendar"))
            hint.setObjectName("MutedText")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        buttons = QHBoxLayout()
        self.close_btn = create_button("OK", "primary")
        self.close_btn.setDefault(True)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)

        if has_appointment_update:
            self.calendar_btn = create_button(
                tr("upload_summary_calendar"),
                "secondary",
            )
            buttons.addWidget(self.calendar_btn)
            self.calendar_btn.clicked.connect(self._on_calendar)

        layout.addLayout(buttons)
        self.close_btn.clicked.connect(self.accept)

    def _on_calendar(self):
        self._go_calendar = True
        self.accept()

    def wants_calendar(self):
        return self._go_calendar
