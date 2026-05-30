import sys

from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

from database.db import (
    Base,
    engine,
)

# IMPORTANT:
# Import models BEFORE create_all()

from database.models.missionary import (
    Missionary,
)

from database.models.workflow import (
    WorkflowStage,
)

from database.models.document import (
    Document,
)


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
    Base.metadata.create_all(
        bind=engine
    )

    app = QApplication(sys.argv)

    load_stylesheet(app)

    window = MainWindow()

    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
