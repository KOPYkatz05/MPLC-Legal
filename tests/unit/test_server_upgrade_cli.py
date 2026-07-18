from pathlib import Path

import server_main


def test_backup_before_upgrade_succeeds_without_existing_database(
    monkeypatch, tmp_path, capsys
):
    missing = tmp_path / "app.db"
    monkeypatch.setattr(
        "database.runtime.get_database_path",
        lambda: missing,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["server_main.py", "--backup-before-upgrade"],
    )

    assert server_main.main() == 0
    assert "no upgrade snapshot is required" in capsys.readouterr().out.lower()


def test_backup_before_upgrade_creates_and_verifies_snapshot(
    monkeypatch, tmp_path, capsys
):
    database = tmp_path / "app.db"
    database.write_bytes(b"existing")
    snapshot = tmp_path / "Backups" / "snapshot.db"
    calls = []

    class FakeBackupService:
        def create_snapshot(self, reason, mirror):
            calls.append((reason, mirror))
            snapshot.parent.mkdir(parents=True)
            snapshot.write_bytes(b"verified")
            return {"path": snapshot}

        @staticmethod
        def verify(path):
            calls.append(("verify", Path(path)))
            return True

    monkeypatch.setattr(
        "database.runtime.get_database_path",
        lambda: database,
    )
    monkeypatch.setattr(
        "services.database_backup_service.DatabaseBackupService",
        FakeBackupService,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["server_main.py", "--backup-before-upgrade"],
    )

    assert server_main.main() == 0
    assert calls == [("pre-upgrade", False), ("verify", snapshot)]
    assert str(snapshot) in capsys.readouterr().out
