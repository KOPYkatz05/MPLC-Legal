import sys
from types import SimpleNamespace

import pytest

import main as main_module
from services.scheduler_service import SchedulerService


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


def test_packaged_client_refuses_local_daily_digest(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["MissionLegal.exe", "--send-daily-digest"])
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("MISSION_LEGAL_ALLOW_LOCAL_DATABASE", raising=False)

    assert main_module.main() == 2
    assert "server package" in capsys.readouterr().out


def test_remote_client_cannot_install_local_digest_task(monkeypatch):
    monkeypatch.setenv("MISSION_LEGAL_REMOTE_CLIENT", "1")

    with pytest.raises(RuntimeError, match="main Mission Legal server"):
        SchedulerService().install_daily_digest_task("10:00")
