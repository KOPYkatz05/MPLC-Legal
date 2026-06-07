import json

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QWidget,
)

from PySide6.QtCore import Qt

from ui.foundation import (
    DialogFooter,
    PageHeader,
    create_button,
    create_text_edit,
    setup_dialog_shell,
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

        self.surface = setup_dialog_shell(
            self,
            surface_width=560,
            surface_min_height=420,
            use_masked_shell=False,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.surface.setLayout(layout)

        header = PageHeader(
            tr("extracted_data_title"),
            "Compare parsed OCR data with the values saved on the record.",
        )
        layout.addWidget(header)

        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(12)
        body.setLayout(body_layout)

        if not ocr_raw_data and not ocr_confirmed_data:
            empty_label = QLabel(tr("extracted_data_none"))
            empty_label.setObjectName("MutedText")
            empty_label.setWordWrap(True)
            body_layout.addWidget(empty_label)
        else:
            if ocr_raw_data:
                raw_label = QLabel("Raw (OCR parsed):")
                raw_label.setObjectName("StrongText")
                body_layout.addWidget(raw_label)
                raw_edit = create_text_edit()
                raw_edit.setObjectName("NotesEditor")
                raw_edit.setReadOnly(True)
                raw_edit.setPlainText(
                    self._format_json(ocr_raw_data)
                )
                body_layout.addWidget(raw_edit)

            if ocr_confirmed_data:
                confirmed_label = QLabel("Confirmed (saved):")
                confirmed_label.setObjectName("StrongText")
                body_layout.addWidget(confirmed_label)
                conf_edit = create_text_edit()
                conf_edit.setObjectName("NotesEditor")
                conf_edit.setReadOnly(True)
                conf_edit.setPlainText(
                    self._format_json(ocr_confirmed_data)
                )
                body_layout.addWidget(conf_edit)

        layout.addWidget(body, stretch=1)

        close_btn = create_button("OK", "primary")
        close_btn.clicked.connect(self.accept)

        footer = DialogFooter()
        footer.add_action(close_btn)
        layout.addWidget(footer)

    def _format_json(self, data_str):
        if not data_str:
            return ""
        try:
            obj = json.loads(data_str)
            return json.dumps(obj, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return str(data_str)
