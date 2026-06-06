"""
Temporary helper for updating missionary_code in the current database.

Delete this file after the one-time database cleanup is finished.
This never changes the internal Missionary.id primary key.
"""

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db import SessionLocal, init_db
from database.models.missionary import Missionary


def _clean_code(value):
    code = (value or "").strip()

    if not code:
        raise ValueError("Missionary ID is required.")

    if not code.isdigit():
        raise ValueError(
            f"Missionary ID must contain numbers only: {value}"
        )

    return code


def list_missionary_ids():
    init_db()

    session = SessionLocal()

    try:
        missionaries = (
            session.query(Missionary)
            .order_by(Missionary.id)
            .all()
        )

        rows = []

        for missionary in missionaries:
            rows.append(
                {
                    "internal_id": missionary.id,
                    "missionary_code": (
                        missionary.missionary_code
                        or str(missionary.id)
                    ),
                    "full_name": missionary.full_name or "",
                    "status": missionary.status or "",
                }
            )

        return rows

    finally:
        session.close()


def temporary_update_missionary_ids(
    updates,
    dry_run=False,
):
    """
    updates is a dict of internal Missionary.id -> new missionary_code.
    """
    init_db()

    session = SessionLocal()

    try:
        changes = []

        cleaned_updates = {
            int(internal_id): _clean_code(code)
            for internal_id, code in updates.items()
        }

        if len(set(cleaned_updates.values())) != len(
            cleaned_updates
        ):
            raise ValueError(
                "Duplicate missionary IDs in requested updates."
            )

        for internal_id, new_code in cleaned_updates.items():
            missionary = (
                session.query(Missionary)
                .filter_by(id=internal_id)
                .first()
            )

            if not missionary:
                raise ValueError(
                    f"Internal missionary ID not found: {internal_id}"
                )

            duplicate = (
                session.query(Missionary)
                .filter(
                    Missionary.missionary_code == new_code,
                    Missionary.id != internal_id,
                )
                .first()
            )

            if duplicate:
                raise ValueError(
                    f"Missionary ID {new_code} is already used by "
                    f"internal ID {duplicate.id} "
                    f"({duplicate.full_name})."
                )

            old_code = (
                missionary.missionary_code
                or str(missionary.id)
            )

            if old_code == new_code:
                continue

            changes.append(
                {
                    "internal_id": missionary.id,
                    "full_name": missionary.full_name or "",
                    "old_code": old_code,
                    "new_code": new_code,
                }
            )

            missionary.missionary_code = new_code

        if dry_run:
            session.rollback()
        else:
            session.commit()

        return changes

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def _print_rows(rows):
    print("internal_id | missionary_id | status | full_name")
    print("------------+---------------+--------+----------")

    for row in rows:
        print(
            f"{row['internal_id']:>11} | "
            f"{row['missionary_code']:<13} | "
            f"{row['status']:<6} | "
            f"{row['full_name']}"
        )


def _print_changes(changes, dry_run):
    action = "Would update" if dry_run else "Updated"

    if not changes:
        print("No changes needed.")
        return

    for change in changes:
        print(
            f"{action} internal ID {change['internal_id']} "
            f"({change['full_name']}): "
            f"{change['old_code']} -> {change['new_code']}"
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Temporary utility for editing user-facing "
            "missionary IDs."
        )
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List current internal IDs and missionary IDs.",
    )

    parser.add_argument(
        "--set",
        action="append",
        nargs=2,
        metavar=("INTERNAL_ID", "MISSIONARY_ID"),
        default=[],
        help=(
            "Set one missionary ID. Can be used multiple times. "
            "Example: --set 12 0012"
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show updates without saving.",
    )

    args = parser.parse_args()

    if args.list or not args.set:
        _print_rows(list_missionary_ids())

    if args.set:
        changes = temporary_update_missionary_ids(
            dict(args.set),
            dry_run=args.dry_run,
        )

        _print_changes(changes, args.dry_run)


if __name__ == "__main__":
    main()
