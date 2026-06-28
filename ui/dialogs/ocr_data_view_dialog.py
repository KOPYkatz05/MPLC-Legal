import json

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QFrame,
    QWidget,
)

from PySide6.QtCore import Qt

from ui.foundation import (
    DialogFooter,
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

        header = QFrame()
        header.setObjectName("OcrDataDialogHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(18, 16, 18, 12)
        header_layout.setSpacing(4)
        header.setLayout(header_layout)

        title = QLabel(tr("extracted_data_title"))
        title.setObjectName("OcrDataDialogTitle")
        subtitle = QLabel(
            "Compare parsed OCR data with the values saved on the record."
        )
        subtitle.setObjectName("OcrDataDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        body = QWidget()
        body.setObjectName("OcrDataDialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(18, 16, 18, 16)
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
                raw_edit.setObjectName("OcrDataTextEditor")
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
                conf_edit.setObjectName("OcrDataTextEditor")
                conf_edit.setReadOnly(True)
                conf_edit.setPlainText(
                    self._format_json(ocr_confirmed_data)
                )
                body_layout.addWidget(conf_edit)

        layout.addWidget(body, stretch=1)

        close_btn = create_button("OK", "primary")
        close_btn.clicked.connect(self.accept)

        footer = DialogFooter()
        footer.setObjectName("OcrDataDialogFooter")
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
