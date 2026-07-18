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
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class MaintenanceError(RuntimeError):
    """Raised when an installer safety gate cannot be satisfied."""


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


def create_pre_upgrade_backup(
    database: Path,
    backup_dir: Path,
    from_version: str,
    to_version: str,
    log_file: Path | None = None,
) -> dict:
    """Create and verify a migration-safe SQLite snapshot.

    The service is expected to be stopped by the installer before this command
    runs.  SQLite's backup API is still used instead of a raw file copy so a
    leftover WAL file cannot make the snapshot incomplete.
    """

    database = database.expanduser().resolve()
    backup_dir = backup_dir.expanduser().resolve()
    if not database.is_file():
        _log(log_file, f"No database exists at {database}; backup gate not needed")
        return {"status": "no-database", "database": str(database)}

    _log(log_file, f"Verifying source database {database}")
    verify_database(database)
    source_hash = _sha256(database)
    source_schema = _schema_version(database)

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
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
        "backup_sha256": backup_hash,
        "created_at": timestamp.isoformat(),
        "database": str(database),
        "reason": "installer-pre-upgrade",
        "schema_version": source_schema,
        "size": final_path.stat().st_size,
        "source_file_sha256": source_hash,
    }
    metadata_path = final_path.with_suffix(".json")
    temporary_metadata = metadata_path.with_suffix(".json.writing")
    temporary_metadata.write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    _flush_file(temporary_metadata)
    temporary_metadata.replace(metadata_path)

    # Re-read the durable metadata and hash after all atomic renames.  This
    # makes a zero exit code a meaningful, independently checkable gate.
    recorded = json.loads(metadata_path.read_text(encoding="utf-8"))
    if recorded.get("backup_sha256") != _sha256(final_path):
        raise MaintenanceError("Backup checksum does not match its metadata")
    verify_database(final_path)
    _log(log_file, f"Verified pre-upgrade backup {final_path}")
    return {
        "status": "backed-up",
        "path": str(final_path),
        "metadata_path": str(metadata_path),
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
    backup.add_argument("--log-file", type=Path)
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
