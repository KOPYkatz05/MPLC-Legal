import sys
import argparse

from pathlib import Path
from utils.pycache_cleanup import cleanup_pycache


def load_stylesheet(app):
    theme_path = (
        Path(__file__).parent
        / "assets"
        / "styles"
        / "theme.qss"
    )

    if theme_path.exists():
        with open(theme_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Mission Legal App"
        )
    )

    parser.add_argument(
        "--clean-pycache",
        action="store_true",
        help=(
            "Remove stale __pycache__ folders and exit."
        ),
    )

    parser.add_argument(
        "--pycache-root",
        default=".",
        help=(
            "Root directory to scan when using "
            "--clean-pycache."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show which __pycache__ folders would be removed "
            "without deleting them."
        ),
    )

    args = parser.parse_args()

    if args.clean_pycache:
        removed = cleanup_pycache(
            args.pycache_root,
            dry_run=args.dry_run,
        )

        action = "Would remove" if args.dry_run else "Removed"

        print(
            f"{action} {len(removed)} stale __pycache__ "
            f"folder(s)."
        )

        return

    from PySide6.QtWidgets import QApplication

    # IMPORTANT:
    # Import models BEFORE init_db()
    from database.models.missionary import Missionary  # noqa: F401
    from database.models.workflow import WorkflowStage  # noqa: F401
    from database.models.document import Document  # noqa: F401
    from database.models.stage_history import StageHistory  # noqa: F401

    from ui.main_window import MainWindow

    from database.db import init_db

    init_db()

    app = QApplication(sys.argv)

    load_stylesheet(app)

    from utils.window_diagnostics import install_window_diagnostics

    install_window_diagnostics(app)

    window = MainWindow()

    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
