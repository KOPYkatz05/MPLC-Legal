from PySide6.QtCore import QRect
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem, QTableView

from ui.delegates.missionary_row_delegate import (
    ANIMATION_HIDDEN_IDS_ATTRIBUTE,
    MissionaryRowDelegate,
)
from ui.models.missionary_table_model import (
    MISSIONARY_ID_ROLE,
    ROW_ACCENT_ROLE,
    ROW_COLOR_ROLE,
)
from ui.widgets.missionary_row_move_animator import (
    MissionaryRowMoveAnimator,
    calculate_row_moves,
)


def test_calculate_row_moves_uses_stable_ids_and_ignores_unchanged_rows():
    before = {
        10: QRect(0, 0, 500, 40),
        20: QRect(0, 40, 500, 40),
        30: QRect(0, 80, 500, 40),
    }
    after = {
        20: QRect(0, 0, 500, 40),
        10: QRect(0, 40, 500, 40),
        30: QRect(0, 80, 500, 40),
    }

    moves = calculate_row_moves(before, after)

    assert [move.missionary_id for move in moves] == [10, 20]
    assert [(move.start_rect.top(), move.end_rect.top()) for move in moves] == [
        (0, 40),
        (40, 0),
    ]


def test_calculate_row_moves_ignores_entering_leaving_and_tiny_movements():
    before = {
        "leaving": QRect(0, 0, 500, 40),
        "steady": QRect(0, 40, 500, 40),
    }
    after = {
        "steady": QRect(0, 41, 500, 40),
        "entering": QRect(0, 80, 500, 40),
    }

    assert calculate_row_moves(before, after, minimum_move=2) == []


def test_delegate_maps_a_semantic_accent_returned_by_the_model(qapp):
    view = QTableView()
    model = QStandardItemModel(1, 1)
    item = QStandardItem("Example")
    item.setData("blue", ROW_COLOR_ROLE)
    item.setData("blue", ROW_ACCENT_ROLE)
    model.setItem(0, 0, item)
    view.setModel(model)
    delegate = MissionaryRowDelegate(view)

    option = QStyleOptionViewItem()
    option.initFrom(view.viewport())
    fill, accent = delegate._row_colors(model.index(0, 0), option)

    assert fill.name().upper() == "#EFF6FF"
    assert accent.name().upper() == "#2563EB"


def test_animator_disabled_and_cancelled_states_are_clean(qapp):
    view = QTableView()
    model = QStandardItemModel()
    for missionary_id in (10, 20, 30):
        item = QStandardItem(str(missionary_id))
        item.setData(missionary_id, MISSIONARY_ID_ROLE)
        model.appendRow(item)
    view.setModel(model)
    view.verticalHeader().setDefaultSectionSize(40)
    view.resize(480, 240)
    view.show()
    qapp.processEvents()

    animator = MissionaryRowMoveAnimator(view)
    animator.animations_enabled = False
    assert animator.capture_before() == 0
    assert animator.is_animating is False

    animator.animations_enabled = True
    assert animator.capture_before() == 3
    first_row = model.takeRow(0)
    model.appendRow(first_row)
    qapp.processEvents()

    assert animator.animate_after(duration=1000) is True
    assert animator.is_animating is True
    assert getattr(view, ANIMATION_HIDDEN_IDS_ATTRIBUTE)

    animator.cancel()
    qapp.processEvents()
    assert animator.is_animating is False
    assert getattr(view, ANIMATION_HIDDEN_IDS_ATTRIBUTE) == frozenset()
    view.close()
