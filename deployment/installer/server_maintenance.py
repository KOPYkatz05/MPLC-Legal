"""Offline maintenance commands carried by the Windows server installer.

This module intentionally uses only the Python standard library so it can be
frozen as a small, self-contained executable.  It does not import application
startup code and therefore cannot trigger a schema migration while taking the
pre-upgrade backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class MaintenanceError(RuntimeError):
    """Raised when an installer safety gate cannot be satisfied."""


RECEIPT_FORMAT = 1
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _log(log_file: Path | None, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"{timestamp} {message}"
    print(line)
    if log_file is None:
        return
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        # Setup has its own mandatory log.  A secondary log failure must not
        # hide the result of the database safety operation.
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def verify_database(path: Path) -> None:
    """Run SQLite's full integrity check without creating a missing database."""

    path = path.resolve()
    if not path.is_file():
        raise MaintenanceError(f"Database does not exist: {path}")
    try:
        with closing(_read_only_connection(path)) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        raise MaintenanceError(f"Could not inspect database integrity: {exc}") from exc
    details = [str(row[0]) for row in rows if row]
    if details != ["ok"]:
        summary = "; ".join(details[:10]) or "no integrity result"
        raise MaintenanceError(f"Database integrity check failed: {summary}")


def _schema_version(path: Path) -> str | None:
    try:
        with closing(_read_only_connection(path)) as connection:
            row = connection.execute(
                "SELECT value FROM app_metadata WHERE key = 'schema_version'"
            ).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


def _safe_version(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return normalized.strip("-._") or "unknown"


def _flush_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _is_reparse_point(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(details, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_attribute)


def _assert_no_reparse_ancestors(path: Path) -> None:
    current = _absolute_path(path)
    while True:
        if os.path.lexists(current) and _is_reparse_point(current):
            raise MaintenanceError(
                f"Installer maintenance path contains a reparse point: {current}"
            )
        parent = current.parent
        if parent == current:
            break
        current = parent


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.fspath(_absolute_path(path)))


def _paths_equal(left: Path, right: Path) -> bool:
    return _normalized_path(left) == _normalized_path(right)


def _require_regular_file(path: Path, description: str) -> None:
    if not os.path.lexists(path):
        raise MaintenanceError(f"{description} is missing: {path}")
    if _is_reparse_point(path) or not path.is_file():
        raise MaintenanceError(f"{description} is not a regular file: {path}")


def _write_json_atomic(path: Path, payload: dict, *, replace: bool) -> None:
    path = _absolute_path(path)
    _assert_no_reparse_ancestors(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(path.parent)
    if not replace and os.path.lexists(path):
        raise MaintenanceError(f"Installer receipt already exists: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.writing")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        _flush_file(temporary)
        if not replace and os.path.lexists(path):
            raise MaintenanceError(f"Installer receipt already exists: {path}")
        os.replace(temporary, path)
        _flush_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json_object(path: Path, description: str) -> dict:
    _require_regular_file(path, description)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaintenanceError(f"{description} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise MaintenanceError(f"{description} must contain a JSON object")
    return value


def _require_sha256(value: object, description: str) -> str:
    normalized = str(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise MaintenanceError(f"{description} is not a valid SHA-256 digest")
    return normalized


def _direct_backup_child(backup_dir: Path, value: object, description: str) -> Path:
    path = _absolute_path(Path(str(value)))
    if not _paths_equal(path.parent, backup_dir):
        raise MaintenanceError(f"{description} is outside the installer backup directory")
    _assert_no_reparse_ancestors(path)
    return path


def _remove_sqlite_sidecars(database: Path) -> None:
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        sidecar = Path(f"{database}{suffix}")
        if not os.path.lexists(sidecar):
            continue
        if _is_reparse_point(sidecar) or not sidecar.is_file():
            raise MaintenanceError(
                f"SQLite sidecar is not a regular file and was not removed: {sidecar}"
            )
        sidecar.unlink()


def _record_restore(
    receipt_path: Path, receipt: dict, status: str, **evidence: object
) -> None:
    updated = dict(receipt)
    updated["restore_status"] = status
    updated["restored_at"] = datetime.now(timezone.utc).isoformat()
    updated.update(evidence)
    _write_json_atomic(receipt_path, updated, replace=True)


def create_pre_upgrade_backup(
    database: Path,
    backup_dir: Path,
    from_version: str,
    to_version: str,
    receipt_path: Path,
    log_file: Path | None = None,
) -> dict:
    """Create and verify a migration-safe SQLite snapshot.

    The service is expected to be stopped by the installer before this command
    runs.  SQLite's backup API is still used instead of a raw file copy so a
    leftover WAL file cannot make the snapshot incomplete.
    """

    database = _absolute_path(database)
    backup_dir = _absolute_path(backup_dir)
    receipt_path = _absolute_path(receipt_path)
    _assert_no_reparse_ancestors(database)
    _assert_no_reparse_ancestors(backup_dir)
    _assert_no_reparse_ancestors(receipt_path)
    if not _paths_equal(receipt_path.parent, backup_dir):
        raise MaintenanceError(
            "Installer receipt must be a direct child of the backup directory"
        )
    if os.path.lexists(receipt_path):
        raise MaintenanceError(f"Installer receipt already exists: {receipt_path}")

    timestamp = datetime.now(timezone.utc)
    attempt_id = uuid.uuid4().hex
    if os.path.lexists(database) and not database.is_file():
        raise MaintenanceError(
            f"Authoritative database path is not a regular file: {database}"
        )
    if not os.path.lexists(database):
        receipt = {
            "app_version_from": from_version,
            "app_version_to": to_version,
            "attempt_id": attempt_id,
            "backup_dir": str(backup_dir),
            "created_at": timestamp.isoformat(),
            "database": str(database),
            "format": RECEIPT_FORMAT,
            "receipt_path": str(receipt_path),
            "status": "no-database",
        }
        _write_json_atomic(receipt_path, receipt, replace=False)
        _log(log_file, f"No database exists at {database}; backup gate not needed")
        return dict(receipt)

    _require_regular_file(database, "Authoritative database")

    _log(log_file, f"Verifying source database {database}")
    verify_database(database)
    source_hash = _sha256(database)
    source_schema = _schema_version(database)

    backup_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        "mission-legal_pre-upgrade_"
        f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_"
        f"{_safe_version(from_version)}_to_{_safe_version(to_version)}"
    )
    final_path = backup_dir / f"{stem}.db"

    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{stem}_",
        suffix=".copying",
        dir=backup_dir,
        delete=False,
    )
    temporary = Path(temporary_handle.name)
    temporary_handle.close()
    try:
        with closing(_read_only_connection(database)) as source:
            with closing(sqlite3.connect(str(temporary))) as destination:
                source.backup(destination, pages=256, sleep=0.05)
                destination.commit()
        verify_database(temporary)
        _flush_file(temporary)
        temporary.replace(final_path)
        verify_database(final_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    backup_hash = _sha256(final_path)
    metadata = {
        "app_version_from": from_version,
        "app_version_to": to_version,
        "attempt_id": attempt_id,
        "backup_sha256": backup_hash,
        "created_at": timestamp.isoformat(),
        "database": str(database),
        "reason": "installer-pre-upgrade",
        "schema_version": source_schema,
        "size": final_path.stat().st_size,
        "source_file_sha256": source_hash,
    }
    metadata_path = final_path.with_suffix(".json")
    _write_json_atomic(metadata_path, metadata, replace=False)

    # Re-read the durable metadata and hash after all atomic renames.  This
    # makes a zero exit code a meaningful, independently checkable gate.
    recorded = json.loads(metadata_path.read_text(encoding="utf-8"))
    if recorded.get("backup_sha256") != _sha256(final_path):
        raise MaintenanceError("Backup checksum does not match its metadata")
    verify_database(final_path)
    receipt = {
        "app_version_from": from_version,
        "app_version_to": to_version,
        "attempt_id": attempt_id,
        "backup_dir": str(backup_dir),
        "backup_path": str(final_path),
        "backup_sha256": backup_hash,
        "created_at": timestamp.isoformat(),
        "database": str(database),
        "format": RECEIPT_FORMAT,
        "metadata_path": str(metadata_path),
        "metadata_sha256": _sha256(metadata_path),
        "receipt_path": str(receipt_path),
        "snapshot_size": final_path.stat().st_size,
        "source_file_sha256": source_hash,
        "status": "backed-up",
    }
    _write_json_atomic(receipt_path, receipt, replace=False)
    _log(log_file, f"Verified pre-upgrade backup {final_path}")
    return dict(receipt, path=str(final_path), sha256=backup_hash)


def restore_pre_upgrade_backup(
    database: Path,
    backup_dir: Path,
    receipt_path: Path,
    from_version: str,
    to_version: str,
    log_file: Path | None = None,
) -> dict:
    """Restore the exact snapshot named by one installer attempt receipt.

    The caller must stop the service before invoking this command.  Every
    receipt, path, hash, metadata, and SQLite integrity check completes before
    the live database is replaced.  The verified backup is never deleted.
    """

    database = _absolute_path(database)
    backup_dir = _absolute_path(backup_dir)
    receipt_path = _absolute_path(receipt_path)
    for path in (database, backup_dir, receipt_path):
        _assert_no_reparse_ancestors(path)
    if not _paths_equal(receipt_path.parent, backup_dir):
        raise MaintenanceError(
            "Installer receipt must be a direct child of the backup directory"
        )

    receipt = _read_json_object(receipt_path, "Installer backup receipt")
    if receipt.get("format") != RECEIPT_FORMAT:
        raise MaintenanceError("Installer backup receipt format is not supported")
    if not re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("attempt_id", ""))):
        raise MaintenanceError("Installer backup receipt has an invalid attempt ID")
    expected_values = {
        "app_version_from": from_version,
        "app_version_to": to_version,
        "database": str(database),
        "backup_dir": str(backup_dir),
        "receipt_path": str(receipt_path),
    }
    for key, expected in expected_values.items():
        actual = receipt.get(key)
        if key.endswith("_path") or key in {"database", "backup_dir"}:
            matches = actual is not None and _paths_equal(Path(str(actual)), Path(expected))
        else:
            matches = actual == expected
        if not matches:
            raise MaintenanceError(
                f"Installer backup receipt {key} does not match this upgrade attempt"
            )

    status = receipt.get("status")
    if status == "no-database":
        if os.path.lexists(database):
            if _is_reparse_point(database) or not database.is_file():
                raise MaintenanceError(
                    f"Candidate database is not a regular file and was not removed: {database}"
                )
        _remove_sqlite_sidecars(database)
        if os.path.lexists(database):
            database.unlink()
        _remove_sqlite_sidecars(database)
        if os.path.lexists(database):
            raise MaintenanceError("Candidate database still exists after no-database rollback")
        _record_restore(
            receipt_path,
            receipt,
            "restored-no-database",
            restored_database_absent=True,
            sqlite_sidecars_cleared=True,
        )
        _log(log_file, f"Restored pre-upgrade no-database state at {database}")
        return {"status": "restored-no-database", "database": str(database)}
    if status != "backed-up":
        raise MaintenanceError("Installer backup receipt has an invalid backup status")

    backup = _direct_backup_child(
        backup_dir, receipt.get("backup_path"), "Receipt backup path"
    )
    metadata_path = _direct_backup_child(
        backup_dir, receipt.get("metadata_path"), "Receipt metadata path"
    )
    if backup.suffix.lower() != ".db" or metadata_path != backup.with_suffix(".json"):
        raise MaintenanceError("Receipt backup and metadata paths do not form a valid pair")
    _require_regular_file(backup, "Pre-upgrade backup")
    _require_regular_file(metadata_path, "Pre-upgrade backup metadata")

    backup_hash = _require_sha256(receipt.get("backup_sha256"), "Receipt backup hash")
    metadata_hash = _require_sha256(
        receipt.get("metadata_sha256"), "Receipt metadata hash"
    )
    source_hash = _require_sha256(
        receipt.get("source_file_sha256"), "Receipt source database hash"
    )
    if _sha256(backup) != backup_hash:
        raise MaintenanceError("Pre-upgrade backup does not match the receipt SHA-256")
    if _sha256(metadata_path) != metadata_hash:
        raise MaintenanceError("Pre-upgrade metadata does not match the receipt SHA-256")
    if backup.stat().st_size != int(receipt.get("snapshot_size", -1)):
        raise MaintenanceError("Pre-upgrade backup size does not match the receipt")

    metadata = _read_json_object(metadata_path, "Pre-upgrade backup metadata")
    metadata_expectations = {
        "app_version_from": from_version,
        "app_version_to": to_version,
        "attempt_id": receipt["attempt_id"],
        "backup_sha256": backup_hash,
        "database": str(database),
        "reason": "installer-pre-upgrade",
        "size": backup.stat().st_size,
        "source_file_sha256": source_hash,
    }
    for key, expected in metadata_expectations.items():
        if metadata.get(key) != expected:
            raise MaintenanceError(
                f"Pre-upgrade backup metadata {key} does not match the receipt"
            )
    verify_database(backup)

    database.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(database.parent)
    if os.path.lexists(database) and (
        _is_reparse_point(database) or not database.is_file()
    ):
        raise MaintenanceError(
            f"Candidate database is not a regular file and was not replaced: {database}"
        )
    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{database.name}.",
        suffix=".installer-restoring",
        dir=database.parent,
        delete=False,
    )
    temporary = Path(temporary_handle.name)
    temporary_handle.close()
    try:
        shutil.copyfile(backup, temporary)
        _flush_file(temporary)
        if _sha256(temporary) != backup_hash:
            raise MaintenanceError("Restored temporary database failed SHA-256 verification")
        verify_database(temporary)
        _remove_sqlite_sidecars(database)
        os.replace(temporary, database)
        _flush_file(database)
        _remove_sqlite_sidecars(database)
        if _sha256(database) != backup_hash:
            raise MaintenanceError("Live database does not match the verified snapshot")
        verify_database(database)
    finally:
        temporary.unlink(missing_ok=True)

    _record_restore(
        receipt_path,
        receipt,
        "restored",
        restored_database_sha256=backup_hash,
        restored_snapshot_path=str(backup),
        sqlite_sidecars_cleared=True,
    )
    _log(log_file, f"Restored verified pre-upgrade database snapshot {backup}")
    return {
        "status": "restored",
        "database": str(database),
        "path": str(backup),
        "sha256": backup_hash,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mission Legal server installer maintenance utility"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser(
        "pre-upgrade-backup",
        help="verify and snapshot the authoritative database before an upgrade",
    )
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--backup-dir", type=Path, required=True)
    backup.add_argument("--from-version", default="unknown")
    backup.add_argument("--to-version", required=True)
    backup.add_argument("--receipt", type=Path, required=True)
    backup.add_argument("--log-file", type=Path)
    restore = subparsers.add_parser(
        "restore-pre-upgrade-backup",
        help="restore the exact database snapshot named by an installer receipt",
    )
    restore.add_argument("--database", type=Path, required=True)
    restore.add_argument("--backup-dir", type=Path, required=True)
    restore.add_argument("--receipt", type=Path, required=True)
    restore.add_argument("--from-version", default="unknown")
    restore.add_argument("--to-version", required=True)
    restore.add_argument("--log-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "pre-upgrade-backup":
            result = create_pre_upgrade_backup(
                args.database,
                args.backup_dir,
                args.from_version,
                args.to_version,
                args.receipt,
                args.log_file,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "restore-pre-upgrade-backup":
            result = restore_pre_upgrade_backup(
                args.database,
                args.backup_dir,
                args.receipt,
                args.from_version,
                args.to_version,
                args.log_file,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
    except Exception as exc:
        _log(getattr(args, "log_file", None), f"Maintenance gate failed: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
