import json

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
)

from utils.i18n import tr


class OcrDataViewDialog(QDialog):
    def __init__(
        self,
        ocr_raw_data,
        ocr_confirmed_data,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("extracted_data_title"))
        self.resize(520, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        if not ocr_raw_data and not ocr_confirmed_data:
            layout.addWidget(QLabel(tr("extracted_data_none")))
        else:
            if ocr_raw_data:
                layout.addWidget(QLabel("Raw (OCR parsed):"))
                raw_edit = QTextEdit()
                raw_edit.setReadOnly(True)
                raw_edit.setPlainText(
                    self._format_json(ocr_raw_data)
                )
                layout.addWidget(raw_edit)

            if ocr_confirmed_data:
                layout.addWidget(QLabel("Confirmed (saved):"))
                conf_edit = QTextEdit()
                conf_edit.setReadOnly(True)
                conf_edit.setPlainText(
                    self._format_json(ocr_confirmed_data)
                )
                layout.addWidget(conf_edit)

        close_btn = QPushButton("OK")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _format_json(self, data_str):
        if not data_str:
            return ""
        try:
            obj = json.loads(data_str)
            return json.dumps(obj, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return str(data_str)
