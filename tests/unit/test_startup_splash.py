from PySide6.QtCore import QEasingCurve, QRectF, Qt
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
    initial_back_wave_offset = splash.progress._back_wave_offset
    initial_fast_wave_offset = splash.progress._fast_wave_offset
    QTest.qWait(80)
    assert splash.progress._wave_offset != initial_wave_offset
    assert splash.progress._back_wave_offset != initial_back_wave_offset
    assert splash.progress._fast_wave_offset != initial_fast_wave_offset
    assert splash.progress._wave_offset != splash.progress._back_wave_offset
    assert splash.progress._fast_wave_offset > splash.progress._wave_offset
    splash.dismiss()


def test_startup_splash_wave_remains_visible_at_full_progress(qapp):
    splash = StartupSplash()
    splash.progress.setValue(100)
    splash.show()
    qapp.processEvents()
    first_frame = splash.progress.grab().toImage()

    QTest.qWait(80)
    second_frame = splash.progress.grab().toImage()

    assert first_frame != second_frame
    splash.dismiss()


def test_startup_splash_floaties_drift_while_progress_is_stationary(qapp):
    splash = StartupSplash()
    splash.progress.setValue(65)
    splash.show()
    initial_positions = [
        (floaty.x, floaty.y) for floaty in splash.progress._floaties
    ]

    QTest.qWait(80)

    current_positions = [
        (floaty.x, floaty.y) for floaty in splash.progress._floaties
    ]
    assert current_positions != initial_positions
    splash.dismiss()


def test_startup_splash_floaties_are_not_dragged_by_progress(qapp):
    splash = StartupSplash()
    track = QRectF(0, 0, 600, 28)
    floaty = splash.progress._floaties[0]
    center_before = splash.progress._floaty_center(track, floaty)

    splash.progress.setValue(80)
    center_after = splash.progress._floaty_center(track, floaty)

    assert center_after == center_before
    splash.dismiss()


def test_startup_splash_keeps_liquid_moving_until_fade_finishes(qapp):
    splash = StartupSplash()
    splash.progress.setValue(100)
    splash.show()
    initial_wave_offset = splash.progress._wave_offset
    initial_floaty_positions = [
        (floaty.x, floaty.y) for floaty in splash.progress._floaties
    ]

    splash.fade_out(duration_ms=80, wait=True)

    assert splash.progress._wave_offset != initial_wave_offset
    assert [
        (floaty.x, floaty.y) for floaty in splash.progress._floaties
    ] != initial_floaty_positions
    assert splash._dismissed is True
    assert not splash.progress._wave_timer.isActive()


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
