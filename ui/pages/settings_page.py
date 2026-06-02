from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QFileDialog,
    QMessageBox,
)

from ui.foundation import (
    PageHeader,
    create_button,
    create_combo_box,
    divider,
)
from services.settings_service import SettingsService
from utils.i18n import tr


class SettingsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.setObjectName("SettingsPage")
        self.main_window = main_window
        self.settings_service = (
            main_window.settings_service
            if main_window
            else SettingsService()
        )
        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        self.header = PageHeader(
            tr("settings_title"),
            tr("settings_language_hint"),
        )
        outer.addWidget(self.header)

        outer.addWidget(divider())

        content = QVBoxLayout()
        content.setContentsMargins(32, 24, 32, 24)
        content.setSpacing(16)

        self.lang_label = QLabel(tr("settings_language"))
        content.addWidget(self.lang_label)

        self.hint_label = QLabel(tr("settings_language_hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #71717A;")
        content.addWidget(self.hint_label)

        self.lang_combo = create_combo_box()
        self.lang_combo.addItem(tr("lang_english"), "en")
        self.lang_combo.addItem(tr("lang_spanish"), "es")

        current = self.settings_service.get_language()
        idx = self.lang_combo.findData(current)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        content.addWidget(self.lang_combo)

        self.storage_label = QLabel(tr("settings_storage_root"))
        content.addWidget(self.storage_label)

        self.storage_hint_label = QLabel(tr("settings_storage_root_hint"))
        self.storage_hint_label.setWordWrap(True)
        self.storage_hint_label.setStyleSheet("color: #71717A;")
        content.addWidget(self.storage_hint_label)

        storage_row = QHBoxLayout()
        storage_row.setSpacing(8)

        self.storage_input = QLineEdit()
        self.storage_input.setText(
            self.settings_service.get_storage_root()
        )
        storage_row.addWidget(self.storage_input)

        self.browse_btn = create_button(
            tr("settings_browse"),
            "secondary",
        )
        self.browse_btn.clicked.connect(self._browse_storage_root)
        storage_row.addWidget(self.browse_btn)

        content.addLayout(storage_row)

        self.save_btn = create_button("Save", "primary")
        self.save_btn.clicked.connect(self._save)
        content.addWidget(self.save_btn)

        content.addStretch()
        outer.addLayout(content)

    def _save(self):
        lang = self.lang_combo.currentData()
        self.settings_service.set_language(lang)
        self.settings_service.set_storage_root(
            self.storage_input.text().strip()
        )
        if self.main_window:
            self.main_window.retranslate_ui()
        QMessageBox.information(
            self,
            tr("settings_title"),
            tr("settings_saved"),
        )

    def _browse_storage_root(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("settings_storage_root"),
            self.storage_input.text(),
        )
        if folder:
            self.storage_input.setText(folder)

    def retranslate_ui(self):
        self.header.set_title(tr("settings_title"))
        self.header.set_subtitle(tr("settings_language_hint"))
        self.lang_label.setText(tr("settings_language"))
        self.hint_label.setText(tr("settings_language_hint"))
        self.storage_label.setText(tr("settings_storage_root"))
        self.storage_hint_label.setText(tr("settings_storage_root_hint"))
        self.browse_btn.setText(tr("settings_browse"))
        current = self.lang_combo.currentData()
        self.lang_combo.clear()
        self.lang_combo.addItem(tr("lang_english"), "en")
        self.lang_combo.addItem(tr("lang_spanish"), "es")
        idx = self.lang_combo.findData(current)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
