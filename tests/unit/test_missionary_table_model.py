from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import Qt

from ui.models.missionary_table_model import (
    COLUMN_KEY_ROLE,
    MISSIONARY_ID_ROLE,
    PAINT_DATA_ROLE,
    PENDING_ROLE,
    RECORD_ROLE,
    ROW_ACCENT_ROLE,
    ROW_COLOR_ROLE,
    SORT_VALUE_ROLE,
    MissionaryFilterProxyModel,
    MissionaryTableModel,
)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    getter: object


NAME = Column("full_name", "Full Name", lambda record: record.full_name)
ARRIVAL = Column(
    "arrival_date",
    "Arrival Date",
    lambda record: record.arrival_date.strftime("%d/%m/%Y")
    if record.arrival_date
    else "",
)


def _record(record_id, name, **values):
    defaults = {
        "missionary_code": str(record_id),
        "preferred_name": "",
        "status": "ACTIVE",
        "current_stage": "INTERPOL",
        "nationality": "Peru",
        "arrival_date": None,
        "row_color": None,
    }
    defaults.update(values)
    return SimpleNamespace(id=record_id, full_name=name, **defaults)


def test_model_exposes_semantic_roles_and_typed_sort_values(qapp):
    record = _record(
        7,
        "Ada Example",
        arrival_date=date(2026, 2, 5),
        row_color="teal",
    )
    model = MissionaryTableModel([NAME, ARRIVAL])
    model.set_records([record])

    name_index = model.index(0, 0)
    date_index = model.index(0, 1)

    assert name_index.data(Qt.DisplayRole) == "Ada Example"
    assert name_index.data(Qt.EditRole) == "Ada Example"
    assert name_index.data(MISSIONARY_ID_ROLE) == 7
    assert name_index.data(ROW_COLOR_ROLE) == "teal"
    # The delegate resolves a semantic row colour to its default accent.  This
    # role is reserved for an explicit per-record accent override.
    assert name_index.data(ROW_ACCENT_ROLE) is None
    assert name_index.data(PENDING_ROLE) is False
    assert name_index.data(RECORD_ROLE) is record
    assert name_index.data(COLUMN_KEY_ROLE) == "full_name"
    assert name_index.data(PAINT_DATA_ROLE) == (
        "Ada Example",
        7,
        "teal",
        None,
        False,
    )
    assert date_index.data(SORT_VALUE_ROLE) == date(2026, 2, 5)
    assert model.headerData(1, Qt.Horizontal) == "Arrival Date"
    assert model.column_key(1) == "arrival_date"


def test_update_record_targets_one_row_and_preserves_id_lookup(qapp):
    first = _record(1, "Before")
    second = _record(2, "Untouched")
    model = MissionaryTableModel([NAME, ARRIVAL])
    model.set_records([first, second])
    changes = []
    model.dataChanged.connect(
        lambda top_left, bottom_right, roles: changes.append(
            (top_left.row(), bottom_right.row(), bottom_right.column(), roles)
        )
    )

    updated = _record(1, "After", row_color="blue")

    assert model.update_record(updated) is True
    assert model.update_record(_record(99, "Missing")) is False
    assert model.record_by_id(1) is updated
    assert model.record_for_source_row(1) is second
    assert model.source_row_for_id(1) == 0
    assert model.source_row_for_id(99) == -1
    assert model.index_for_id(1, 1).isValid()
    assert changes == [(0, 0, 1, changes[0][3])]
    assert Qt.DisplayRole in changes[0][3]
    assert SORT_VALUE_ROLE in changes[0][3]

    model.set_pending(1, True)
    assert model.index_for_id(1).data(PENDING_ROLE) is True
    assert changes[-1][0:3] == (0, 0, 1)
    assert changes[-1][3] == [PENDING_ROLE, PAINT_DATA_ROLE]


def test_same_population_snapshot_updates_without_model_reset(qapp):
    model = MissionaryTableModel([NAME, ARRIVAL])
    model.set_records([_record(1, "Before"), _record(2, "Stable")])
    resets = []
    changes = []
    model.modelReset.connect(lambda: resets.append(True))
    model.dataChanged.connect(
        lambda top_left, bottom_right, _roles: changes.append(
            (top_left.row(), bottom_right.row())
        )
    )

    model.set_records([_record(1, "After"), _record(2, "Stable")])

    assert resets == []
    assert changes == [(0, 0)]
    assert model.record_by_id(1).full_name == "After"

    model.set_records([_record(2, "Stable"), _record(1, "After")])
    assert resets == [True]


def test_upsert_and_remove_use_structural_row_signals(qapp):
    first = _record(1, "First")
    inserted = _record(2, "Inserted")
    model = MissionaryTableModel([NAME])
    model.set_records([first])
    inserted_rows = []
    removed_rows = []
    model.rowsInserted.connect(
        lambda parent, first_row, last_row: inserted_rows.append(
            (parent.isValid(), first_row, last_row)
        )
    )
    model.rowsRemoved.connect(
        lambda parent, first_row, last_row: removed_rows.append(
            (parent.isValid(), first_row, last_row)
        )
    )

    assert model.upsert_record(inserted) is True
    assert inserted_rows == [(False, 1, 1)]
    assert model.record_by_id(2) is inserted

    updated = _record(2, "Updated")
    assert model.upsert_record(updated) is False
    assert inserted_rows == [(False, 1, 1)]
    assert model.record_by_id(2) is updated

    assert model.remove_record(1) is first
    assert removed_rows == [(False, 0, 0)]
    assert model.source_row_for_id(2) == 0
    assert model.remove_record(99) is None


def test_proxy_filters_search_stage_nationality_and_group(qapp):
    model = MissionaryTableModel([NAME])
    model.set_records(
        [
            _record(
                1,
                "Maria Fernanda Lopez Garcia",
                preferred_name="Garcia Lopez, Maria Fernanda",
            ),
            _record(
                2,
                "Other Missionary",
                current_stage="CARNET",
                nationality="Bolivia",
            ),
            _record(3, "Archived Match", status="ARCHIVED"),
        ]
    )
    proxy = MissionaryFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_search_text("garcia lopez")
    assert [record.id for record in proxy.records_in_view()] == [1]

    proxy.set_search_text("")
    proxy.set_stage_filter("carnet")
    proxy.set_nationality_filter("BOLIVIA")
    assert [record.id for record in proxy.records_in_view()] == [2]

    proxy.set_stage_filter(None)
    proxy.set_nationality_filter(None)
    proxy.set_group_member_ids({1})
    assert [record.id for record in proxy.records_in_view()] == [1]

    proxy.set_group_member_ids(set())
    assert proxy.rowCount() == 0


def test_proxy_switches_between_active_and_archive_records(qapp):
    active = _record(1, "Active")
    archived = _record(2, "Archived", status="ARCHIVED")
    model = MissionaryTableModel([NAME])
    model.set_records([active, archived])
    proxy = MissionaryFilterProxyModel()
    proxy.setSourceModel(model)

    assert proxy.records_in_view() == [active]

    proxy.set_view_mode("archive")
    assert proxy.records_in_view() == [archived]
    assert proxy.index_for_id(2).isValid()
    assert not proxy.index_for_id(1).isValid()


def test_proxy_sorts_dates_stably_and_keeps_empty_dates_last(qapp):
    records = [
        _record(3, "Undated", arrival_date=None),
        _record(2, "Same Date Second", arrival_date=date(2026, 1, 5)),
        _record(1, "Same Date First", arrival_date=date(2026, 1, 5)),
        _record(4, "Later", arrival_date=date(2026, 2, 1)),
    ]
    model = MissionaryTableModel([ARRIVAL])
    model.set_records(records)
    proxy = MissionaryFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.sort(0, Qt.AscendingOrder)
    assert [record.id for record in proxy.records_in_view()] == [1, 2, 4, 3]

    proxy.sort(0, Qt.DescendingOrder)
    assert [record.id for record in proxy.records_in_view()] == [4, 2, 1, 3]
