import json

from PySide6.QtCore import QSettings

from config import APP, ORG, get_storage_root, set_storage_root
from utils.i18n import get_i18n


MISSIONARIES_TABLE_COLUMNS_KEY = "missionaries_table_columns"
MISSIONARIES_TABLE_COLUMN_WIDTHS_KEY = (
    "missionaries_table_column_widths"
)


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

    def get_missionaries_table_columns(self, default_columns):
        saved = self._settings.value(
            MISSIONARIES_TABLE_COLUMNS_KEY,
            None,
        )

        if isinstance(saved, list):
            return [str(column) for column in saved]

        if isinstance(saved, str):
            return [
                column.strip()
                for column in saved.split(",")
                if column.strip()
            ]

        return list(default_columns)

    def set_missionaries_table_columns(self, columns):
        self._settings.setValue(
            MISSIONARIES_TABLE_COLUMNS_KEY,
            ",".join(columns),
        )

    def reset_missionaries_table_columns(self):
        self._settings.remove(
            MISSIONARIES_TABLE_COLUMNS_KEY
        )

    def get_missionaries_table_column_widths(self):
        saved = self._settings.value(
            MISSIONARIES_TABLE_COLUMN_WIDTHS_KEY,
            None,
        )

        if isinstance(saved, dict):
            return {
                str(key): int(value)
                for key, value in saved.items()
                if str(key) and str(value).isdigit()
            }

        if not isinstance(saved, str) or not saved.strip():
            return {}

        try:
            parsed = json.loads(saved)
        except (TypeError, ValueError):
            return {}

        if not isinstance(parsed, dict):
            return {}

        widths = {}

        for key, value in parsed.items():
            try:
                width = int(value)
            except (TypeError, ValueError):
                continue

            if width > 0:
                widths[str(key)] = width

        return widths

    def set_missionaries_table_column_widths(self, widths):
        self._settings.setValue(
            MISSIONARIES_TABLE_COLUMN_WIDTHS_KEY,
            json.dumps(widths),
        )

    def reset_missionaries_table_column_widths(self):
        self._settings.remove(
            MISSIONARIES_TABLE_COLUMN_WIDTHS_KEY
        )
