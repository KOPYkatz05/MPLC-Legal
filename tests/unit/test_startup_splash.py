from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton

from ui.dialogs.startup_splash import StartupSplash


def test_startup_splash_is_non_interactive_and_animated(qapp):
    splash = StartupSplash()

    assert splash.windowFlags() & Qt.FramelessWindowHint
    assert splash.testAttribute(Qt.WA_TranslucentBackground)
    assert splash.progress.minimum() == 0
    assert splash.progress.maximum() == 100
    splash.advance_to(40)
    assert splash._progress_animation is not None
    assert splash._progress_animation.endValue() == 40
    assert not splash.findChildren(QPushButton)
    assert splash.findChild(QProgressBar, "StartupSplashProgress") is splash.progress
    splash.dismiss()


def test_startup_splash_loads_server_manager_logo(qapp):
    splash = StartupSplash()

    labels = splash.findChildren(QLabel)
    assert any(not label.pixmap().isNull() for label in labels)
    splash.dismiss()
