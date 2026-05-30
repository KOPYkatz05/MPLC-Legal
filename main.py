import sys

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


def main():
    Base.metadata.create_all(
        bind=engine
    )

    app = QApplication(sys.argv)

    window = MainWindow()

    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()