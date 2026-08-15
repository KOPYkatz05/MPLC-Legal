import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import socket
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from database.runtime import get_app_data_dir, get_database_path
from version import APP_VERSION


BACKUP_ROOT_ENV = "MISSION_LEGAL_BACKUP_DIR"


def _replace_with_retry(source, destination):
    source = Path(source)
    destination = Path(destination)
    for attempt in range(5):
        try:
            source.replace(destination)
            return destination
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


class DatabaseBackupError(RuntimeError):
    pass


class DatabaseBackupService:
    def __init__(self, database_path=None, local_backup_dir=None, mirror_dir=None):
        self.database_path = Path(database_path or get_database_path()).resolve()
        self.local_backup_dir = Path(
            local_backup_dir or (get_app_data_dir() / "Backups")
        ).resolve()
        configured_mirror = mirror_dir or os.environ.get(BACKUP_ROOT_ENV)
        if not configured_mirror:
            try:
                from server.configuration import load_server_configuration

                configured_mirror = load_server_configuration().get(
                    "onedrive_backup_dir"
                )
            except Exception:
                configured_mirror = None
        self.mirror_dir = (
            Path(configured_mirror).expanduser().resolve()
            if configured_mirror
            else None
        )

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def verify(path):
        try:
            with closing(sqlite3.connect(str(path))) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise DatabaseBackupError(f"Could not verify database backup: {exc}") from exc
        if not result or result[0] != "ok":
            detail = result[0] if result else "no integrity result"
            raise DatabaseBackupError(f"Database integrity check failed: {detail}")
        return True

    @staticmethod
    def schema_version(path):
        try:
            with closing(sqlite3.connect(str(path))) as connection:
                row = connection.execute(
                    "SELECT value FROM app_metadata WHERE key = 'schema_version'"
                ).fetchone()
        except sqlite3.Error:
            return 0
        try:
            return int(row[0]) if row else 0
        except (TypeError, ValueError):
            return 0

    @classmethod
    def transfer_database(cls, source_path, destination_path, overwrite=False):
        source_path = Path(source_path).resolve()
        destination_path = Path(destination_path).resolve()
        if not source_path.is_file():
            raise DatabaseBackupError(f"Source database does not exist: {source_path}")
        if destination_path.exists() and not overwrite:
            raise DatabaseBackupError(
                f"Destination database already exists: {destination_path}"
            )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temp_handle = tempfile.NamedTemporaryFile(
            prefix=f".{destination_path.stem}_transfer_",
            suffix=".tmp",
            dir=destination_path.parent,
            delete=False,
        )
        temporary = Path(temp_handle.name)
        temp_handle.close()
        try:
            with closing(sqlite3.connect(str(source_path))) as source:
                with closing(sqlite3.connect(str(temporary))) as destination:
                    source.backup(destination)
            cls.verify(temporary)
            _replace_with_retry(temporary, destination_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return destination_path

    @classmethod
    def restore_snapshot(cls, snapshot_path, destination_path):
        snapshot_path = Path(snapshot_path).resolve()
        destination_path = Path(destination_path).resolve()
        cls.verify(snapshot_path)
        metadata_path = snapshot_path.with_suffix(".json")
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise DatabaseBackupError("Backup metadata is unreadable") from exc
            expected = metadata.get("sha256")
            if expected and not hmac.compare_digest(
                expected, cls._sha256(snapshot_path)
            ):
                raise DatabaseBackupError("Backup checksum does not match metadata")

        if destination_path.exists():
            safety = cls(
                database_path=destination_path,
                local_backup_dir=destination_path.parent / "Backups",
            )
            safety.create_snapshot(reason="pre-restore", mirror=False)
        restored = cls.transfer_database(
            snapshot_path, destination_path, overwrite=True
        )
        cls.verify(restored)
        return restored

    def create_snapshot(self, reason="scheduled", mirror=True):
        if not self.database_path.exists():
            raise DatabaseBackupError(f"Database does not exist: {self.database_path}")

        self.local_backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc)
        stem = f"mission-legal_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}"
        final_path = self.local_backup_dir / f"{stem}.db"

        temp_handle = tempfile.NamedTemporaryFile(
            prefix=f".{stem}_",
            suffix=".tmp",
            dir=self.local_backup_dir,
            delete=False,
        )
        temp_path = Path(temp_handle.name)
        temp_handle.close()
        try:
            with closing(sqlite3.connect(str(self.database_path))) as source:
                with closing(sqlite3.connect(str(temp_path))) as destination:
                    source.backup(destination)
            self.verify(temp_path)
            _replace_with_retry(temp_path, final_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        metadata = {
            "app_version": APP_VERSION,
            "created_at": timestamp.isoformat(),
            "database": self.database_path.name,
            "hostname": socket.gethostname(),
            "reason": reason,
            # Record the schema actually contained in this snapshot. This is
            # especially important for the mandatory pre-migration backup.
            "schema_version": self.schema_version(final_path),
            "sha256": self._sha256(final_path),
            "size": final_path.stat().st_size,
        }
        metadata_path = final_path.with_suffix(".json")
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        mirrored_path = None
        if mirror and self.mirror_dir:
            mirrored_path = self._mirror(final_path, metadata_path)
        return {
            "path": final_path,
            "metadata_path": metadata_path,
            "mirrored_path": mirrored_path,
            "metadata": metadata,
        }

    def _mirror(self, database_backup, metadata_path):
        self.mirror_dir.mkdir(parents=True, exist_ok=True)
        destination = self.mirror_dir / database_backup.name
        temp_destination = destination.with_suffix(".db.uploading")
        shutil.copy2(database_backup, temp_destination)
        self.verify(temp_destination)
        _replace_with_retry(temp_destination, destination)
        shutil.copy2(metadata_path, destination.with_suffix(".json"))
        return destination

    def prune(self, keep=48, mirror_keep=30):
        backups = sorted(
            self.local_backup_dir.glob("mission-legal_*.db"),
            # Snapshot names carry a sortable UTC timestamp and remain stable
            # when OneDrive or copy operations rewrite filesystem mtimes.
            key=lambda path: path.name,
            reverse=True,
        )
        removed = []
        for backup in backups[max(0, keep):]:
            backup.unlink(missing_ok=True)
            backup.with_suffix(".json").unlink(missing_ok=True)
            removed.append(backup)
        if self.mirror_dir and self.mirror_dir.exists():
            mirrored = sorted(
                self.mirror_dir.glob("mission-legal_*.db"),
                key=lambda path: path.name,
                reverse=True,
            )
            for backup in mirrored[max(0, mirror_keep):]:
                backup.unlink(missing_ok=True)
                backup.with_suffix(".json").unlink(missing_ok=True)
        return removed
