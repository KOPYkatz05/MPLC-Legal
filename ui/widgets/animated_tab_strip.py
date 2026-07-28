"""Compact, shared top-page tabs with an animated active indicator."""

import weakref

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QSizePolicy

from services.settings_service import SettingsService


_tab_strips = weakref.WeakSet()
_indicator_thickness = SettingsService().get_tab_indicator_thickness()


def set_tab_indicator_thickness(thickness):
    """Apply the UI preference to every currently visible tab strip."""
    global _indicator_thickness
    _indicator_thickness = max(1, min(6, int(thickness)))
    for strip in list(_tab_strips):
        strip._snap_indicator_to_current_tab()


class AnimatedTabStrip(QFrame):
    """A Missionaries-style tab row whose underline bridges between tabs."""

    def __init__(self, parent=None, *, expanding=False):
        super().__init__(parent)
        self.setObjectName("UnifiedTabStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._buttons = {}
        self._current_key = None
        self._indicator = QFrame(self)
        self._indicator.setObjectName("UnifiedTabIndicator")
        self._indicator.hide()
        self._animation = None
        self._animations_enabled = True
        self._expanding = expanding
        _tab_strips.add(self)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch()

    @property
    def buttons(self):
        return self._buttons

    def add_tab(self, key, label, callback):
        button = QPushButton(label, self)
        button.setObjectName("UnifiedTopTab")
        button.setCheckable(True)
        button.setFixedHeight(30)
        button.setCursor(Qt.PointingHandCursor)
        if self._expanding:
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        def select_tab(checked=False, tab_key=key):
            self.set_active(tab_key)
            callback(tab_key)

        button.clicked.connect(select_tab)
        self._layout.insertWidget(self._layout.count() - 1, button)
        self._buttons[key] = button
        return button

    def set_active(self, key, *, animate=True):
        button = self._buttons.get(key)
        if button is None:
            return
        if key == self._current_key and self._indicator.isVisible():
            return
        previous_key = self._current_key
        previous_geometry = self._indicator.geometry()
        has_indicator = self._indicator.isVisible()
        self._current_key = key
        for tab_key, tab_button in self._buttons.items():
            active = tab_key == key
            tab_button.setChecked(active)
            tab_button.setProperty("active", active)
            tab_button.style().unpolish(tab_button)
            tab_button.style().polish(tab_button)

        QTimer.singleShot(
            0,
            lambda: self._place_indicator(
                key, previous_key, previous_geometry, has_indicator, animate
            ),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_key is not None:
            QTimer.singleShot(0, self._snap_indicator_to_current_tab)

    def _target_geometry(self, key):
        button = self._buttons[key]
        return QRect(
            button.x(),
            self.height() - _indicator_thickness,
            button.width(),
            _indicator_thickness,
        )

    def _snap_indicator_to_current_tab(self):
        if self._animation is not None:
            self._animation.stop()
        if self._current_key in self._buttons:
            self._indicator.setGeometry(self._target_geometry(self._current_key))
            self._indicator.show()

    def _place_indicator(self, key, previous_key, previous_geometry, has_indicator, animate):
        if key not in self._buttons:
            return
        target = self._target_geometry(key)
        if self._animation is not None:
            self._animation.stop()
        if not has_indicator or previous_key is None or not animate or not self._animations_enabled:
            self._indicator.setGeometry(target)
            self._indicator.show()
            return

        start = previous_geometry if previous_geometry.isValid() else self._target_geometry(previous_key)
        if start == target:
            self._indicator.setGeometry(target)
            self._indicator.show()
            return

        bridge_left = min(start.left(), target.left())
        bridge_right = max(start.right(), target.right())
        bridge = QRect(
            bridge_left,
            self.height() - _indicator_thickness,
            bridge_right - bridge_left + 1,
            _indicator_thickness,
        )
        self._indicator.setGeometry(start)
        self._indicator.show()
        grow = QPropertyAnimation(self._indicator, b"geometry")
        grow.setDuration(90)
        grow.setStartValue(start)
        grow.setEndValue(bridge)
        grow.setEasingCurve(QEasingCurve.OutCubic)
        settle = QPropertyAnimation(self._indicator, b"geometry")
        settle.setDuration(130)
        settle.setStartValue(bridge)
        settle.setEndValue(target)
        settle.setEasingCurve(QEasingCurve.OutCubic)
        # The first phase bridges the old and new tabs; the second settles.
        sequence = QSequentialAnimationGroup(self)
        sequence.addAnimation(grow)
        sequence.addAnimation(settle)
        sequence.finished.connect(lambda: self._snap_indicator_to_current_tab())
        self._animation = sequence
        sequence.start()
