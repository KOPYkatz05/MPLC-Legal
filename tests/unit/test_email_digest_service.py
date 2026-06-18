from datetime import date

from services.email_digest_service import EmailDigestService


class FakeSettings:
    def __init__(self, settings, password="secret", language="en"):
        self.settings = dict(settings)
        self.password = password
        self.language = language
        self.last_sent = None

    def get_daily_digest_settings(self):
        return dict(self.settings)

    def get_daily_digest_password(self):
        return self.password

    def get_language(self):
        return self.language

    def set_daily_digest_last_sent_date(self, value):
        self.last_sent = value


class FakeDigest:
    def build_digest(self, **kwargs):
        return {
            "subject": "Mission Legal - Today's Digest",
            "text": "Today\n- Work",
        }


def _settings(**overrides):
    values = {
        "email_enabled": True,
        "recipient_email": "secretary@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_tls": "starttls",
        "sender_email": "office@example.com",
        "smtp_username": "office@example.com",
        "include_overdue": True,
        "detail_level": "balanced",
        "last_sent_date": "",
    }
    values.update(overrides)
    return values


def test_email_digest_skips_missing_settings():
    service = EmailDigestService(
        FakeSettings(_settings(recipient_email="")),
        FakeDigest(),
    )

    result = service.send_daily_digest()

    assert result["sent"] is False
    assert result["reason"] == "missing_settings"
    assert "recipient_email" in result["missing"]


def test_email_digest_skips_duplicate_same_day():
    service = EmailDigestService(
        FakeSettings(_settings(last_sent_date=date.today().isoformat())),
        FakeDigest(),
    )

    result = service.send_daily_digest()

    assert result == {
        "sent": False,
        "reason": "already_sent",
    }


def test_email_digest_sends_and_marks_date(monkeypatch):
    sent = []

    def fake_send(settings, password, digest):
        sent.append((settings, password, digest))

    monkeypatch.setattr(EmailDigestService, "send_message", staticmethod(fake_send))
    settings = FakeSettings(_settings())
    service = EmailDigestService(settings, FakeDigest())

    result = service.send_daily_digest()

    assert result["sent"] is True
    assert sent[0][0]["recipient_email"] == "secretary@example.com"
    assert sent[0][1] == "secret"
    assert sent[0][2]["subject"] == "Mission Legal - Today's Digest"
    assert settings.last_sent == date.today().isoformat()
