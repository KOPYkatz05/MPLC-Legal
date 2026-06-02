from datetime import date

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QDateEdit,
    QScrollArea,
    QWidget,
    QFrame,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QPixmap

from utils.constants import MISSIONARY_DATE_FIELDS
from utils.i18n import tr, field_label


EMPTY_DATE = QDate(1900, 1, 1)


class OCRReviewDialog(QDialog):
    def __init__(
        self,
        ocr_fields,
        parsed_data,
        parent=None,
        ocr_status="skipped",
        image_path=None,
    ):
        super().__init__(parent)

        self.ocr_fields = ocr_fields
        self.parsed_data = parsed_data or {}
        self.ocr_status = ocr_status
        self.image_path = image_path
        self.field_edits = {}
        self.date_edits = {}

        self.setWindowTitle(tr("ocr_review_title"))
        self.setModal(True)
        self.resize(900, 520)

        self.setup_ui()

    def setup_ui(self):
        root = QVBoxLayout()
        self.setLayout(root)

        status_key = f"ocr_status_{self.ocr_status}"
        status_text = tr(status_key)
        colors = {
            "success": "#059669",
            "partial": "#D97706",
            "failed": "#DC2626",
            "skipped": "#71717A",
        }
        color = colors.get(self.ocr_status, "#71717A")

        banner = QLabel(status_text)
        banner.setWordWrap(True)
        banner.setStyleSheet(
            f"background-color: #F4F4F5; color: {color}; "
            f"padding: 10px; border-radius: 6px; font-weight: 600;"
        )
        root.addWidget(banner)

        info = QLabel(tr("ocr_review_instructions"))
        info.setWordWrap(True)
        root.addWidget(info)

        body = QHBoxLayout()

        if self.image_path:
            preview_frame = QFrame()
            preview_layout = QVBoxLayout()
            preview_frame.setLayout(preview_layout)
            preview_frame.setFixedWidth(380)

            pix = QPixmap(str(self.image_path))
            if not pix.isNull():
                scaled = pix.scaled(
                    360, 460,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                img_label = QLabel()
                img_label.setPixmap(scaled)
                img_label.setAlignment(Qt.AlignCenter)
                scroll = QScrollArea()
                scroll.setWidget(img_label)
                scroll.setWidgetResizable(True)
                preview_layout.addWidget(scroll)
            else:
                preview_layout.addWidget(
                    QLabel("(Preview unavailable)")
                )

            body.addWidget(preview_frame)

        form_widget = QWidget()
        form = QFormLayout()
        form_widget.setLayout(form)

        for field in self.ocr_fields:
            label = field_label(field)
            raw_value = self.parsed_data.get(field, "")

            if field in MISSIONARY_DATE_FIELDS or field == "date_of_birth":
                date_edit = QDateEdit()
                date_edit.setCalendarPopup(True)
                date_edit.setMinimumDate(EMPTY_DATE)
                date_edit.setSpecialValueText("--")
                parsed = self._to_date(raw_value)
                if parsed:
                    date_edit.setDate(
                        QDate(
                            parsed.year,
                            parsed.month,
                            parsed.day,
                        )
                    )
                else:
                    date_edit.setDate(EMPTY_DATE)
                    date_edit.setSpecialValueText("—")
                self.date_edits[field] = date_edit
                form.addRow(f"{label}:", date_edit)
            else:
                if raw_value and not isinstance(raw_value, str):
                    raw_value = str(raw_value)
                edit = QLineEdit(raw_value or "")
                self.field_edits[field] = edit
                form.addRow(f"{label}:", edit)

        scroll_form = QScrollArea()
        scroll_form.setWidget(form_widget)
        scroll_form.setWidgetResizable(True)
        body.addWidget(scroll_form, stretch=1)

        root.addLayout(body)

        button_layout = QHBoxLayout()
        self.skip_btn = QPushButton(tr("ocr_skip"))
        self.save_btn = QPushButton(tr("ocr_save"))
        self.save_btn.setDefault(True)
        button_layout.addStretch()
        button_layout.addWidget(self.skip_btn)
        button_layout.addWidget(self.save_btn)
        root.addLayout(button_layout)

        self.skip_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self.accept)

    def _to_date(self, value):
        if isinstance(value, date):
            return value
        if not value:
            return None
        from services.upload_pipeline import parse_date_value
        return parse_date_value(str(value))

    def get_data(self):
        result = {}
        for field, edit in self.field_edits.items():
            result[field] = edit.text().strip()
        for field, date_edit in self.date_edits.items():
            qd = date_edit.date()
            if qd.isValid() and qd != EMPTY_DATE:
                result[field] = qd.toString("yyyy-MM-dd")
        return result
