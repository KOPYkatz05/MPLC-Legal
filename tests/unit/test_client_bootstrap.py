import sys
from types import SimpleNamespace

import client_bootstrap


def test_source_run_skips_velopack(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert client_bootstrap.run_client_bootstrap() is False


def test_frozen_run_invokes_velopack_before_app_startup(monkeypatch):
    calls = []
    refreshes = []

    class FakeApp:
        def set_auto_apply_on_startup(self, enabled):
            calls.append(("auto-apply", enabled))
            return self

        def on_after_install_fast_callback(self, callback):
            calls.append(("after-install", callback))
            return self

        def on_after_update_fast_callback(self, callback):
            calls.append(("after-update", callback))
            return self

        def on_restarted(self, callback):
            calls.append(("restarted", callback))
            return self

        def on_first_run(self, callback):
            calls.append(("first-run", callback))
            return self

        def run(self):
            calls.append(("run",))

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "app_identity.refresh_windows_shell_icon_cache",
        lambda: refreshes.append(True),
    )
    monkeypatch.setitem(sys.modules, "velopack", SimpleNamespace(App=FakeApp))
    monkeypatch.delenv("MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP", raising=False)

    assert client_bootstrap.run_client_bootstrap() is True
    assert [call[0] for call in calls] == [
        "auto-apply",
        "after-install",
        "after-update",
        "restarted",
        "first-run",
        "run",
    ]
    calls[2][1]("0.3.2")
    assert refreshes == [True]


def test_frozen_smoke_can_explicitly_skip_bootstrap(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP", "1")

    assert client_bootstrap.run_client_bootstrap() is False
