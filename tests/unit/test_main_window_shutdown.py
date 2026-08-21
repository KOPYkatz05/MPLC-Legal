from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from ui.main_window import MainWindow


def test_main_window_close_schedules_application_quit(qapp, monkeypatch):
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    scheduled = []

    monkeypatch.setattr(
        "ui.main_window.QTimer.singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert len(scheduled) == 1
    assert scheduled[0][0] == 0
    assert scheduled[0][1] == qapp.quit

