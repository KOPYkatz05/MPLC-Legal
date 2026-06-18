import sys
from types import SimpleNamespace

import main as main_module


def test_send_daily_digest_cli_does_not_launch_gui(monkeypatch, capsys):
    called = []

    class FakeEmailDigestService:
        def send_daily_digest(self):
            called.append("send")
            return {
                "sent": True,
                "reason": "sent",
            }

    monkeypatch.setattr(sys, "argv", ["main.py", "--send-daily-digest"])
    monkeypatch.setitem(
        sys.modules,
        "services.email_digest_service",
        SimpleNamespace(EmailDigestService=FakeEmailDigestService),
    )
    import database.db as db_module

    monkeypatch.setattr(db_module, "init_db", lambda: called.append("init"))

    main_module.main()

    assert called == ["init", "send"]
    assert "Daily digest email sent." in capsys.readouterr().out
