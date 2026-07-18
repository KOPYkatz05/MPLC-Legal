import json
import sqlite3
from contextlib import closing

import pytest

from services.database_backup_service import (
    DatabaseBackupError,
    DatabaseBackupService,
)


def _create_database(path, value="original"):
    with closing(sqlite3.connect(str(path))) as connection:
        connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
        connection.execute("INSERT INTO records (value) VALUES (?)", (value,))
        connection.commit()


def test_snapshot_is_verified_and_mirrored(tmp_path):
    database = tmp_path / "app.db"
    local_backups = tmp_path / "local"
    mirror = tmp_path / "onedrive"
    _create_database(database)

    result = DatabaseBackupService(
        database_path=database,
        local_backup_dir=local_backups,
        mirror_dir=mirror,
    ).create_snapshot(reason="test")

    assert result["path"].exists()
    assert result["mirrored_path"].exists()
    assert result["metadata"]["reason"] == "test"
    assert result["metadata"]["app_version"]
    assert result["metadata"]["schema_version"] == 1
    assert result["metadata"]["sha256"]
    assert json.loads(result["metadata_path"].read_text(encoding="utf-8"))[
        "size"
    ] == result["path"].stat().st_size
    with closing(sqlite3.connect(str(result["mirrored_path"]))) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "original"


def test_snapshot_rejects_missing_database(tmp_path):
    service = DatabaseBackupService(
        database_path=tmp_path / "missing.db",
        local_backup_dir=tmp_path / "backups",
    )

    with pytest.raises(DatabaseBackupError, match="does not exist"):
        service.create_snapshot()


def test_prune_keeps_newest_snapshots(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    service = DatabaseBackupService(
        database_path=tmp_path / "app.db",
        local_backup_dir=backup_dir,
    )
    backups = []
    for index in range(4):
        backup = backup_dir / f"mission-legal_2026010{index}T000000Z.db"
        backup.write_bytes(b"backup")
        backup.with_suffix(".json").write_text("{}", encoding="utf-8")
        backups.append(backup)

    removed = service.prune(keep=2)

    assert set(removed) == set(backups[:2])
    assert all(not path.exists() for path in backups[:2])
    assert all(path.exists() for path in backups[2:])


def test_transfer_database_uses_consistent_sqlite_backup(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "program-data" / "app.db"
    _create_database(source, value="transferred")

    result = DatabaseBackupService.transfer_database(source, destination)

    assert result == destination.resolve()
    DatabaseBackupService.verify(destination)
    with closing(sqlite3.connect(str(destination))) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "transferred"


def test_transfer_refuses_to_replace_existing_database(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    _create_database(source)
    _create_database(destination, value="keep")

    with pytest.raises(DatabaseBackupError, match="already exists"):
        DatabaseBackupService.transfer_database(source, destination)


def test_restore_verifies_snapshot_and_preserves_pre_restore_copy(tmp_path):
    live = tmp_path / "app.db"
    source = tmp_path / "source.db"
    backups = tmp_path / "source-backups"
    _create_database(live, value="old-live")
    _create_database(source, value="new-live")
    snapshot = DatabaseBackupService(
        database_path=source,
        local_backup_dir=backups,
    ).create_snapshot(reason="restore-test", mirror=False)["path"]

    DatabaseBackupService.restore_snapshot(snapshot, live)

    with closing(sqlite3.connect(str(live))) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "new-live"
    safety_copies = list((tmp_path / "Backups").glob("mission-legal_*.db"))
    assert len(safety_copies) == 1
    with closing(sqlite3.connect(str(safety_copies[0]))) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "old-live"


def test_restore_rejects_checksum_mismatch(tmp_path):
    source = tmp_path / "source.db"
    _create_database(source)
    result = DatabaseBackupService(
        database_path=source,
        local_backup_dir=tmp_path / "backups",
    ).create_snapshot(mirror=False)
    metadata = json.loads(result["metadata_path"].read_text(encoding="utf-8"))
    metadata["sha256"] = "0" * 64
    result["metadata_path"].write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(DatabaseBackupError, match="checksum"):
        DatabaseBackupService.restore_snapshot(result["path"], tmp_path / "live.db")
