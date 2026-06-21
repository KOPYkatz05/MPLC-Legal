import json
from datetime import date, datetime, timedelta

from PySide6.QtCore import QSettings

from config import APP, ORG, get_storage_root, set_storage_root
from utils.i18n import get_i18n


MISSIONARIES_TABLE_COLUMNS_KEY = "missionaries_table_columns"
MISSIONARIES_TABLE_COLUMN_WIDTHS_KEY = (
    "missionaries_table_column_widths"
)
DIGEST_PASSWORD_SERVICE = "MissionLegalDailyDigest"
DIGEST_PASSWORD_USERNAME = "smtp_password"
DIGEST_DEFAULT_TIME = "10:00"
DIGEST_DEFAULT_DETAIL_LEVEL = "balanced"
TRANSFER_DATE_KEY = "transfer_management/next_transfer_wednesday"
TRANSFER_CYCLE_DAYS = 42


def _bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_value(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def is_wednesday(value):
    parsed = _parse_iso_date(value)
    return parsed is not None and parsed.weekday() == 2


def transfer_dates_from_anchor(anchor, *, today=None, count=8):
    anchor = _parse_iso_date(anchor)
    if anchor is None:
        return []

    today = today or date.today()
    while anchor < today:
        anchor = anchor + timedelta(days=TRANSFER_CYCLE_DAYS)

    return [
        anchor + timedelta(days=TRANSFER_CYCLE_DAYS * offset)
        for offset in range(count)
    ]


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:
        return None


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

    def get_next_transfer_wednesday(self):
        return _parse_iso_date(
            self._settings.value(TRANSFER_DATE_KEY, "")
        )

    def set_next_transfer_wednesday(self, value):
        parsed = _parse_iso_date(value)
        if parsed is None:
            self._settings.remove(TRANSFER_DATE_KEY)
            return None
        if not is_wednesday(parsed):
            raise ValueError("Transfer date must be a Wednesday.")
        self._settings.setValue(TRANSFER_DATE_KEY, parsed.isoformat())
        return parsed

    def get_upcoming_transfer_wednesdays(self, *, today=None, count=8):
        return transfer_dates_from_anchor(
            self.get_next_transfer_wednesday(),
            today=today,
            count=count,
        )

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

    def get_daily_digest_settings(self):
        return {
            "email_enabled": _bool_value(
                self._settings.value("daily_digest/email_enabled", False)
            ),
            "recipient_email": str(
                self._settings.value("daily_digest/recipient_email", "") or ""
            ),
            "digest_time": str(
                self._settings.value(
                    "daily_digest/digest_time",
                    DIGEST_DEFAULT_TIME,
                )
                or DIGEST_DEFAULT_TIME
            ),
            "include_overdue": _bool_value(
                self._settings.value("daily_digest/include_overdue", True),
                True,
            ),
            "detail_level": str(
                self._settings.value(
                    "daily_digest/detail_level",
                    DIGEST_DEFAULT_DETAIL_LEVEL,
                )
                or DIGEST_DEFAULT_DETAIL_LEVEL
            ),
            "smtp_host": str(
                self._settings.value("daily_digest/smtp_host", "") or ""
            ),
            "smtp_port": _int_value(
                self._settings.value("daily_digest/smtp_port", 587),
                587,
            ),
            "smtp_tls": str(
                self._settings.value("daily_digest/smtp_tls", "starttls")
                or "starttls"
            ),
            "sender_email": str(
                self._settings.value("daily_digest/sender_email", "") or ""
            ),
            "smtp_username": str(
                self._settings.value("daily_digest/smtp_username", "") or ""
            ),
            "last_sent_date": str(
                self._settings.value("daily_digest/last_sent_date", "") or ""
            ),
        }

    def set_daily_digest_settings(self, values):
        self._settings.setValue(
            "daily_digest/email_enabled",
            bool(values.get("email_enabled", False)),
        )
        self._settings.setValue(
            "daily_digest/recipient_email",
            values.get("recipient_email", ""),
        )
        self._settings.setValue(
            "daily_digest/digest_time",
            values.get("digest_time", DIGEST_DEFAULT_TIME),
        )
        self._settings.setValue(
            "daily_digest/include_overdue",
            bool(values.get("include_overdue", True)),
        )
        self._settings.setValue(
            "daily_digest/detail_level",
            values.get("detail_level", DIGEST_DEFAULT_DETAIL_LEVEL),
        )
        self._settings.setValue(
            "daily_digest/smtp_host",
            values.get("smtp_host", ""),
        )
        self._settings.setValue(
            "daily_digest/smtp_port",
            _int_value(values.get("smtp_port"), 587),
        )
        self._settings.setValue(
            "daily_digest/smtp_tls",
            values.get("smtp_tls", "starttls"),
        )
        self._settings.setValue(
            "daily_digest/sender_email",
            values.get("sender_email", ""),
        )
        self._settings.setValue(
            "daily_digest/smtp_username",
            values.get("smtp_username", ""),
        )

    def get_daily_digest_password(self):
        keyring = _keyring()
        if keyring is None:
            return ""
        try:
            return (
                keyring.get_password(
                    DIGEST_PASSWORD_SERVICE,
                    DIGEST_PASSWORD_USERNAME,
                )
                or ""
            )
        except Exception:
            return ""

    def set_daily_digest_password(self, password):
        keyring = _keyring()
        if keyring is None:
            return False
        try:
            if password:
                keyring.set_password(
                    DIGEST_PASSWORD_SERVICE,
                    DIGEST_PASSWORD_USERNAME,
                    password,
                )
            else:
                try:
                    keyring.delete_password(
                        DIGEST_PASSWORD_SERVICE,
                        DIGEST_PASSWORD_USERNAME,
                    )
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def set_daily_digest_last_sent_date(self, value):
        self._settings.setValue("daily_digest/last_sent_date", value or "")
