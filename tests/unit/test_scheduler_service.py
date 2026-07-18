from types import SimpleNamespace

import pytest

from services import scheduler_service as module


def test_packaged_scheduler_targets_executable_without_main_py(monkeypatch):
    captured = {}
    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", r"C:\Program Files\Mission Legal\MissionLegal.exe")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        fake_run,
    )

    module.SchedulerService().install_daily_digest_task("10:00")

    task_command = captured["command"][captured["command"].index("/TR") + 1]
    assert task_command == '"C:\\Program Files\\Mission Legal\\MissionLegal.exe" --send-daily-digest'


def test_remote_client_cannot_install_local_digest_task(monkeypatch):
    monkeypatch.setenv("MISSION_LEGAL_REMOTE_CLIENT", "1")

    with pytest.raises(RuntimeError, match="main Mission Legal server"):
        module.SchedulerService().install_daily_digest_task("10:00")
