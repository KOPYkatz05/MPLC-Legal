from PySide6.QtCore import QSettings

from config import APP, ORG, get_storage_root, set_storage_root
from utils.i18n import get_i18n


class SettingsService:
    def __init__(self):
        self._settings = QSettings(ORG, APP)
        self._i18n = get_i18n()
        saved = self._settings.value("language", "en")
        if saved in ("en", "es"):
            self._i18n.set_language(saved)

    def get_language(self):
        return self._i18n.get_language()

    def set_language(self, lang):
        if lang not in ("en", "es"):
            return
        self._settings.setValue("language", lang)
        self._i18n.set_language(lang)

    def language_changed(self):
        return self._i18n.language_changed

    def get_storage_root(self):
        return str(get_storage_root())

    def set_storage_root(self, path):
        if not path:
            return None
        return str(set_storage_root(path))
