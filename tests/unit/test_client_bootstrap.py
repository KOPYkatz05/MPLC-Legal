import sys
from types import SimpleNamespace

import client_bootstrap


def test_source_run_skips_velopack(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert client_bootstrap.run_client_bootstrap() is False


def test_frozen_run_invokes_velopack_before_app_startup(monkeypatch):
    calls = []

    class FakeApp:
        def set_auto_apply_on_startup(self, enabled):
            calls.append(("auto-apply", enabled))
            return self

        def run(self):
            calls.append(("run",))

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setitem(sys.modules, "velopack", SimpleNamespace(App=FakeApp))
    monkeypatch.delenv("MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP", raising=False)

    assert client_bootstrap.run_client_bootstrap() is True
    assert calls == [("auto-apply", False), ("run",)]


def test_frozen_smoke_can_explicitly_skip_bootstrap(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP", "1")

    assert client_bootstrap.run_client_bootstrap() is False
