"""FLIP-style row movement animation for a model-backed ``QTableView``."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QTableView

from ui.delegates.missionary_row_delegate import ANIMATION_HIDDEN_IDS_ATTRIBUTE
from ui.models.missionary_table_model import MISSIONARY_ID_ROLE


@dataclass(frozen=True)
class RowMove:
    """A stable row identity moving between two viewport rectangles."""

    missionary_id: Hashable
    start_rect: QRect
    end_rect: QRect


@dataclass(frozen=True)
class _CapturedRow:
    rect: QRect
    pixmap: QPixmap


def calculate_row_moves(
    before: Mapping[Hashable, QRect],
    after: Mapping[Hashable, QRect],
    *,
    minimum_move: int = 2,
) -> list[RowMove]:
    """Return vertical movements shared by two geometry snapshots.

    The helper is deliberately independent of widgets so ordering logic can be
    unit tested without asserting on rendered pixels.
    """

    threshold = max(1, int(minimum_move))
    moves = []
    for missionary_id, start_rect in before.items():
        end_rect = after.get(missionary_id)
        if end_rect is None:
            continue
        if abs(start_rect.top() - end_rect.top()) < threshold:
            continue
        moves.append(
            RowMove(
                missionary_id,
                QRect(start_rect),
                QRect(end_rect),
            )
        )
    moves.sort(key=lambda move: (move.start_rect.top(), str(move.missionary_id)))
    return moves


class MissionaryRowMoveAnimator(QObject):
    """Animate visible missionary rows after a synchronous model mutation.

    ``capture_before()`` records the visible rows and ``animate_after()`` starts
    a short overlay animation after the source/proxy model has settled.  For a
    convenient one-call form use ``animate_update(callback)``.

    Filtering, tab changes, initial loads, and colour-only changes should not be
    wrapped: those transitions either replace the visible set or do not change
    a row's sort position.
    """

    def __init__(
        self,
        view: QTableView,
        parent: QObject | None = None,
        *,
        max_overlays: int = 24,
        minimum_move: int = 2,
    ):
        if not isinstance(view, QTableView):
            raise TypeError("view must be a QTableView")
        super().__init__(parent if parent is not None else view)
        self._view = view
        self._max_overlays = max(1, int(max_overlays))
        self._minimum_move = max(1, int(minimum_move))
        self._animations_enabled = True
        self._before: dict[Hashable, _CapturedRow] = {}
        self._group: QParallelAnimationGroup | None = None
        self._overlays: list[QLabel] = []
        self._suppressed_rects: list[QRect] = []

    @property
    def animations_enabled(self) -> bool:
        return self._animations_enabled

    @animations_enabled.setter
    def animations_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if self._animations_enabled == enabled:
            return
        self._animations_enabled = enabled
        if not enabled:
            self.cancel()

    @property
    def is_animating(self) -> bool:
        return self._group is not None

    def capture_before(self) -> int:
        """Capture fully visible rows immediately before a model update."""

        self.cancel()
        if not self._can_animate():
            return 0

        viewport = self._view.viewport()
        captured: dict[Hashable, _CapturedRow] = {}
        for missionary_id, rect in self._visible_row_rects().items():
            pixmap = viewport.grab(rect)
            if pixmap.isNull():
                continue
            captured[missionary_id] = _CapturedRow(QRect(rect), pixmap)
        self._before = captured
        return len(captured)

    def animate_after(self, duration: int = 200) -> bool:
        """Animate rows from the last capture to their current positions."""

        before = self._before
        self._before = {}
        if not before or not self._can_animate() or int(duration) <= 0:
            return False

        # Sorting through QSortFilterProxyModel is synchronous, but forcing a
        # view layout here makes visualRect/rowViewportPosition authoritative.
        self._view.doItemsLayout()
        after = self._visible_row_rects()
        moves = calculate_row_moves(
            {key: value.rect for key, value in before.items()},
            after,
            minimum_move=self._minimum_move,
        )
        if not moves or len(moves) > self._max_overlays:
            return False

        viewport = self._view.viewport()
        hidden_ids = frozenset(move.missionary_id for move in moves)
        setattr(self._view, ANIMATION_HIDDEN_IDS_ATTRIBUTE, hidden_ids)
        self._suppressed_rects = [QRect(move.end_rect) for move in moves]
        for rect in self._suppressed_rects:
            viewport.repaint(rect)

        group = QParallelAnimationGroup(self)
        overlays: list[QLabel] = []
        for move in moves:
            captured = before[move.missionary_id]
            overlay = QLabel(viewport)
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            overlay.setAttribute(Qt.WA_NoSystemBackground, True)
            overlay.setScaledContents(captured.rect.size() != move.end_rect.size())
            overlay.setPixmap(captured.pixmap)
            overlay.setGeometry(captured.rect)
            overlay.show()
            overlay.raise_()
            overlays.append(overlay)

            animation = QPropertyAnimation(overlay, b"geometry", group)
            animation.setStartValue(captured.rect)
            animation.setEndValue(move.end_rect)
            animation.setDuration(max(1, int(duration)))
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(animation)

        self._overlays = overlays
        self._group = group
        group.finished.connect(self._finish_animation)
        group.start(QAbstractAnimation.KeepWhenStopped)
        return True

    def animate_update(
        self,
        mutation: Callable[..., Any],
        *args,
        duration: int = 200,
        **kwargs,
    ) -> Any:
        """Capture, run a synchronous mutation, and start the transition.

        The callback's return value is returned.  Exceptions propagate after
        discarding the pending snapshot, so a failed mutation never leaves
        animation state behind.
        """

        self.capture_before()
        try:
            result = mutation(*args, **kwargs)
        except Exception:
            self._before = {}
            raise
        self.animate_after(duration=duration)
        return result

    def cancel(self):
        """Cancel a capture or running transition and restore normal paint."""

        self._before = {}
        group = self._group
        self._group = None
        if group is not None:
            group.stop()
        self._cleanup_overlays(group)

    def _finish_animation(self):
        group = self._group
        self._group = None
        self._cleanup_overlays(group)

    def _cleanup_overlays(self, group):
        for overlay in self._overlays:
            overlay.hide()
            overlay.deleteLater()
        self._overlays = []

        if group is not None:
            group.deleteLater()

        if hasattr(self._view, ANIMATION_HIDDEN_IDS_ATTRIBUTE):
            setattr(self._view, ANIMATION_HIDDEN_IDS_ATTRIBUTE, frozenset())

        viewport = self._view.viewport()
        for rect in self._suppressed_rects:
            viewport.update(rect)
        self._suppressed_rects = []

    def _can_animate(self) -> bool:
        return (
            self._animations_enabled
            and self._view.isVisible()
            and self._view.viewport().isVisible()
            and self._view.model() is not None
            and self._view.model().rowCount() > 0
        )

    def _visible_row_rects(self) -> dict[Hashable, QRect]:
        view = self._view
        viewport = view.viewport()
        model = view.model()
        if model is None or viewport.width() <= 0 or viewport.height() <= 0:
            return {}

        first_row = view.rowAt(0)
        if first_row < 0:
            first_index = view.indexAt(QPoint(1, 1))
            first_row = first_index.row() if first_index.isValid() else -1
        if first_row < 0:
            return {}

        viewport_rect = viewport.rect()
        result: dict[Hashable, QRect] = {}
        row_count = model.rowCount()
        for row in range(first_row, row_count):
            if view.isRowHidden(row):
                continue
            top = view.rowViewportPosition(row)
            height = view.rowHeight(row)
            if top >= viewport_rect.bottom() + 1:
                break
            rect = QRect(0, top, viewport_rect.width(), height)
            # Clipped snapshots resize poorly while moving.  Boundary rows are
            # intentionally skipped; all fully visible affected rows animate.
            if not viewport_rect.contains(rect):
                continue
            index = model.index(row, 0)
            missionary_id = index.data(MISSIONARY_ID_ROLE)
            if missionary_id is None or missionary_id in result:
                continue
            result[missionary_id] = rect
        return result


__all__ = [
    "MissionaryRowMoveAnimator",
    "RowMove",
    "calculate_row_moves",
]
