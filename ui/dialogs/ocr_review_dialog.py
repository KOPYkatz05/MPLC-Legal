from datetime import date

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QWidget,
    QFrame,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QPixmap

from ui.foundation import (
    create_button,
    create_date_edit,
    create_line_edit,
    create_scroll_area,
)
from utils.constants import MISSIONARY_DATE_FIELDS
from utils.i18n import tr, field_label


EMPTY_DATE = QDate(1900, 1, 1)
DATE_EDIT_MAX_WIDTH = 180


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
        banner = QLabel(status_text)
        banner.setWordWrap(True)
        banner.setObjectName("OcrStatusBanner")
        banner.setProperty("status", self.ocr_status)
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
                scroll = create_scroll_area()
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
                date_edit = create_date_edit()
                date_edit.setMinimumDate(EMPTY_DATE)
                date_edit.setSpecialValueText("--")
                date_edit.setMaximumWidth(DATE_EDIT_MAX_WIDTH)
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
                edit = create_line_edit()
                edit.setText(raw_value or "")
                self.field_edits[field] = edit
                form.addRow(f"{label}:", edit)

        scroll_form = create_scroll_area()
        scroll_form.setWidget(form_widget)
        body.addWidget(scroll_form, stretch=1)

        root.addLayout(body)

        button_layout = QHBoxLayout()
        self.skip_btn = create_button(tr("ocr_skip"), "secondary")
        self.save_btn = create_button(tr("ocr_save"), "primary")
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
