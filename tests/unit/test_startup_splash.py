from PySide6.QtCore import QEasingCurve, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton

from ui.dialogs.startup_splash import LiquidProgressBar, StartupSplash


def test_startup_splash_is_non_interactive_and_animated(qapp):
    splash = StartupSplash()

    assert splash.windowFlags() & Qt.FramelessWindowHint
    assert splash.testAttribute(Qt.WA_TranslucentBackground)
    assert splash.progress.minimum() == 0
    assert splash.progress.maximum() == 100
    splash.advance_to(40)
    assert splash._progress_animation is not None
    assert splash._progress_animation.endValue() == 40
    assert splash._progress_animation.duration() == 560
    assert (
        splash._progress_animation.easingCurve().type()
        == QEasingCurve.Type.InOutSine
    )
    assert not splash.findChildren(QPushButton)
    assert (
        splash.findChild(LiquidProgressBar, "StartupSplashProgress")
        is splash.progress
    )
    splash.dismiss()


def test_startup_splash_can_render_a_checkpoint_before_main_event_loop(qapp):
    splash = StartupSplash()
    splash.show()

    splash.advance_to(40, duration_ms=1, wait=True)
    splash.advance_to(65, duration_ms=1, wait=True)

    assert splash.progress.value() == 65
    assert splash.progress._wave_timer.isActive()
    initial_wave_offset = splash.progress._wave_offset
    QTest.qWait(80)
    assert splash.progress._wave_offset != initial_wave_offset
    splash.dismiss()


def test_startup_splash_loads_mission_legal_icon(qapp):
    splash = StartupSplash()

    labels = splash.findChildren(QLabel)
    assert any(not label.pixmap().isNull() for label in labels)
    splash.dismiss()


def test_startup_splash_dismiss_is_idempotent(qapp):
    splash = StartupSplash()

    splash.dismiss()
    splash.dismiss()

    assert splash._dismissed is True
    assert splash._cursor_overridden is False
