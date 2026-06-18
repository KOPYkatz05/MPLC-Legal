import smtplib
from datetime import date
from email.message import EmailMessage

from services.daily_digest_service import DailyDigestService
from services.settings_service import SettingsService
from utils.logger import logger


class EmailDigestService:
    def __init__(self, settings_service=None, digest_service=None):
        self.settings_service = settings_service or SettingsService()
        self.digest_service = digest_service or DailyDigestService()

    def send_daily_digest(self, *, force=False):
        settings = self.settings_service.get_daily_digest_settings()
        today = date.today().isoformat()

        if not settings.get("email_enabled") and not force:
            logger.info("Daily digest email is disabled.")
            return {
                "sent": False,
                "reason": "disabled",
            }

        if not force and settings.get("last_sent_date") == today:
            logger.info("Daily digest email already sent today.")
            return {
                "sent": False,
                "reason": "already_sent",
            }

        missing = self._missing_settings(settings)
        password = self.settings_service.get_daily_digest_password()
        if settings.get("smtp_username") and not password:
            missing.append("smtp_password")

        if missing:
            logger.warning(
                "Daily digest email settings incomplete: %s",
                ", ".join(missing),
            )
            return {
                "sent": False,
                "reason": "missing_settings",
                "missing": missing,
            }

        digest = self.digest_service.build_digest(
            include_overdue=settings.get("include_overdue", True),
            detail_level=settings.get("detail_level", "balanced"),
            language=self.settings_service.get_language(),
        )
        self.send_message(settings, password, digest)
        self.settings_service.set_daily_digest_last_sent_date(today)
        logger.info("Daily digest email sent.")
        return {
            "sent": True,
            "reason": "sent",
            "digest": digest,
        }

    def send_test_email(self):
        settings = self.settings_service.get_daily_digest_settings()
        missing = self._missing_settings(settings)
        password = self.settings_service.get_daily_digest_password()
        if settings.get("smtp_username") and not password:
            missing.append("smtp_password")
        if missing:
            return {
                "sent": False,
                "reason": "missing_settings",
                "missing": missing,
            }

        digest = self.digest_service.build_digest(
            include_overdue=settings.get("include_overdue", True),
            detail_level=settings.get("detail_level", "balanced"),
            language=self.settings_service.get_language(),
        )
        self.send_message(settings, password, digest)
        return {
            "sent": True,
            "reason": "sent",
            "digest": digest,
        }

    @staticmethod
    def send_message(settings, password, digest):
        message = EmailMessage()
        message["Subject"] = digest["subject"]
        message["From"] = settings["sender_email"]
        message["To"] = settings["recipient_email"]
        message.set_content(digest["text"])

        host = settings["smtp_host"]
        port = int(settings.get("smtp_port") or 587)
        tls_mode = settings.get("smtp_tls", "starttls")

        if tls_mode == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)

        try:
            if tls_mode == "starttls":
                server.starttls()
            username = settings.get("smtp_username")
            if username:
                server.login(username, password)
            server.send_message(message)
        finally:
            server.quit()

    @staticmethod
    def _missing_settings(settings):
        required = [
            "recipient_email",
            "smtp_host",
            "smtp_port",
            "sender_email",
        ]
        return [
            key
            for key in required
            if not str(settings.get(key, "")).strip()
        ]
