import asyncio

import pytest

import database.migrations.runner as migration_runner
import server.app as app_module


class _ExistingDatabasePath:
    @staticmethod
    def exists():
        return True


class _DisposableEngine:
    def __init__(self, events):
        self.events = events

    def dispose(self):
        self.events.append("dispose")


def _run_lifespan(app):
    async def run():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run())


def _app():
    return app_module.create_app(
        device_store=object(),
        pairing_store=object(),
        manage_lifecycle=True,
        network_trust_provider=lambda: True,
    )


def _patch_common(monkeypatch, events):
    monkeypatch.setattr(
        app_module,
        "get_database_path",
        lambda: _ExistingDatabasePath(),
    )
    monkeypatch.setattr(app_module, "engine", _DisposableEngine(events))
    monkeypatch.setattr(app_module, "_daily_backup_if_due", lambda: None)


def test_required_migration_creates_local_backup_before_init(monkeypatch):
    events = []
    _patch_common(monkeypatch, events)
    monkeypatch.setattr(
        migration_runner,
        "migration_required",
        lambda _engine: True,
    )

    def backup(reason, mirror=None):
        events.append(("backup", reason, mirror))
        return {"path": "verified.db"}

    monkeypatch.setattr(app_module, "_backup", backup)
    monkeypatch.setattr(app_module, "init_db", lambda: events.append("init"))

    _run_lifespan(_app())

    assert events[:2] == [
        ("backup", "pre-migration", False),
        "init",
    ]


def test_failed_required_backup_prevents_database_initialization(monkeypatch):
    events = []
    _patch_common(monkeypatch, events)
    monkeypatch.setattr(
        migration_runner,
        "migration_required",
        lambda _engine: True,
    )

    def backup(reason, mirror=None):
        events.append(("backup", reason, mirror))
        raise OSError("backup unavailable")

    monkeypatch.setattr(app_module, "_backup", backup)
    monkeypatch.setattr(app_module, "init_db", lambda: events.append("init"))

    with pytest.raises(OSError, match="backup unavailable"):
        _run_lifespan(_app())

    assert events == [("backup", "pre-migration", False)]


def test_current_database_does_not_take_pre_migration_backup(monkeypatch):
    events = []
    _patch_common(monkeypatch, events)
    monkeypatch.setattr(
        migration_runner,
        "migration_required",
        lambda _engine: False,
    )
    monkeypatch.setattr(
        app_module,
        "_backup",
        lambda reason, mirror=None: events.append(("backup", reason, mirror)),
    )
    monkeypatch.setattr(app_module, "init_db", lambda: events.append("init"))

    _run_lifespan(_app())

    assert "init" in events
    assert ("backup", "pre-migration", False) not in events
    assert ("backup", "server-shutdown", None) in events

