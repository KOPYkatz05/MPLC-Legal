import argparse
from pathlib import Path

from database.runtime import get_database_path
from services.database_backup_service import DatabaseBackupService


def main():
    parser = argparse.ArgumentParser(
        description="Restore a verified Mission Legal SQLite snapshot"
    )
    parser.add_argument("snapshot")
    parser.add_argument("--destination")
    args = parser.parse_args()

    snapshot = Path(args.snapshot).expanduser().resolve()
    destination = (
        Path(args.destination).expanduser().resolve()
        if args.destination
        else get_database_path()
    )
    restored = DatabaseBackupService.restore_snapshot(snapshot, destination)
    print(f"Restored verified database: {restored}")


if __name__ == "__main__":
    main()
