from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QTableView

from ui.delegates.missionary_row_delegate import MissionaryRowDelegate
from ui.foundation.fluent import TableWidget as FluentTableWidget
from ui.models.missionary_table_model import (
    MISSIONARY_ID_ROLE,
    PENDING_ROLE,
    ROW_COLOR_ROLE,
    MissionaryFilterProxyModel,
    MissionaryTableModel,
)
from ui.pages.missionaries_page import MissionariesPage
from ui.widgets.missionary_row_move_animator import MissionaryRowMoveAnimator


def _missionary(
    missionary_id: int,
    name: str,
    *,
    status: str = "ACTIVE",
    arrival_date=None,
    archive_reason: str = "",
    row_color=None,
):
    """Return a complete record for every Missionaries table column getter."""
    return SimpleNamespace(
        id=missionary_id,
        missionary_code=str(missionary_id),
        full_name=name,
        preferred_name="",
        nationality="Peru",
        passport_number=f"P{missionary_id}",
        carnet_number="",
        date_of_birth=None,
        current_stage="INTERPOL",
        tramite_usuario="",
        tramite_contrasena="",
        arrival_date=arrival_date,
        visa_expiration=None,
        passport_expiration=None,
        residency_expiration=None,
        prorroga_expiration=None,
        carnet_issue_date=None,
        cancelacion_date=None,
        interpol_appointment_date=None,
        biometric_appointment_date=None,
        pickup_appointment_date=None,
        notes="",
        status=status,
        archive_reason=archive_reason,
        row_color=row_color,
        row_accent=None,
    )


class _FakeSettingsService:
    def __init__(self):
        self.columns = ["missionary_id", "full_name", "arrival_date"]
        self.widths = {}

    def get_missionaries_default_view(self):
        return "active"

    def get_missionaries_table_columns(self, default):
        _ = default
        return list(self.columns)

    def set_missionaries_table_columns(self, keys):
        self.columns = list(keys)

    def get_missionaries_table_column_widths(self):
        return dict(self.widths)

    def set_missionaries_table_column_widths(self, widths):
        self.widths = dict(widths)


class _FakeMissionaryService:
    ROW_COLORS = {"teal", "blue", "purple", "amber", "green", "red", "gray"}

    def __init__(self, active, archived):
        self.active = list(active)
        self.archived = list(archived)
        self.color_calls = []

    def get_all_missionaries(self):
        return list(self.active)

    def get_archived_missionaries(self):
        return list(self.archived)

    def set_missionary_row_color(self, missionary_id, color):
        self.color_calls.append((missionary_id, color))
        return self._replace_color(missionary_id, color)

    def clear_missionary_row_color(self, missionary_id):
        return self._replace_color(missionary_id, None)

    def _replace_color(self, missionary_id, color):
        for collection in (self.active, self.archived):
            for row, missionary in enumerate(collection):
                if missionary.id == missionary_id:
                    updated = SimpleNamespace(
                        **{**vars(missionary), "row_color": color}
                    )
                    collection[row] = updated
                    return updated
        return None


class _FakeGroupService:
    def list_groups(self):
        return []


@pytest.fixture
def missionaries_page(monkeypatch, qapp):
    from ui.pages import missionaries_page as page_module

    active = [
        _missionary(30, "Alpha Missionary", arrival_date="2026-04-01"),
        _missionary(10, "Zulu Missionary", arrival_date="2026-02-01"),
        _missionary(20, "Middle Missionary", arrival_date="2026-03-01"),
    ]
    archived = [
        _missionary(
            40,
            "Archived Missionary",
            status="ARCHIVED",
            arrival_date="2025-05-01",
            archive_reason="Returned home",
        )
    ]
    service = _FakeMissionaryService(active, archived)

    monkeypatch.setattr(page_module, "MissionaryService", lambda: service)
    monkeypatch.setattr(page_module, "MissionaryGroupService", _FakeGroupService)
    monkeypatch.setattr(
        page_module,
        "ClientViewService",
        lambda: SimpleNamespace(get_missionaries_snapshot=lambda: {}),
    )
    monkeypatch.setattr(page_module, "ExportService", SimpleNamespace)
    monkeypatch.setattr(page_module, "DynamicsRosterClientService", SimpleNamespace)
    monkeypatch.setattr(
        page_module,
        "GroupPackageExportService",
        lambda export_service: SimpleNamespace(export_service=export_service),
    )

    window = SimpleNamespace(
        settings_service=_FakeSettingsService(),
        detail_page=SimpleNamespace(load_missionary=lambda missionary: None),
        stack=SimpleNamespace(setCurrentWidget=lambda widget: None),
    )
    page = MissionariesPage(window)
    qapp.processEvents()

    try:
        yield page, service
    finally:
        page.close()
        qapp.processEvents()


def _proxy_ids(page):
    return [
        page._missionary_proxy.index(row, 0).data(MISSIONARY_ID_ROLE)
        for row in range(page._missionary_proxy.rowCount())
    ]


def _column_index(model, key):
    return next(
        column
        for column in range(model.columnCount())
        if model.column_key(column) == key
    )


def test_page_uses_standard_qtableview_and_shared_model_pipeline(
    missionaries_page,
):
    page, _service = missionaries_page

    assert type(page.table) is QTableView
    assert not isinstance(page.table, FluentTableWidget)
    assert isinstance(page._missionary_model, MissionaryTableModel)
    assert isinstance(page._missionary_proxy, MissionaryFilterProxyModel)
    assert page.table.model() is page._missionary_proxy
    assert page._missionary_proxy.sourceModel() is page._missionary_model
    assert page._missionary_model.rowCount() == 4
    assert set(_proxy_ids(page)) == {10, 20, 30}


def test_active_and_archive_share_pipeline_and_archive_reason_column(
    missionaries_page,
    qapp,
):
    page, _service = missionaries_page
    table = page.table
    source_model = page._missionary_model
    proxy_model = page._missionary_proxy
    delegate = table.itemDelegate()
    animator = page._row_move_animator

    assert isinstance(delegate, MissionaryRowDelegate)
    assert isinstance(animator, MissionaryRowMoveAnimator)
    assert animator._view is table

    page._select_tab("archive")
    qapp.processEvents()

    assert page.table is table
    assert page._missionary_model is source_model
    assert page._missionary_proxy is proxy_model
    assert page.table.itemDelegate() is delegate
    assert page._row_move_animator is animator
    assert _proxy_ids(page) == [40]

    archive_reason_column = _column_index(source_model, "archive_reason")
    assert source_model.headerData(
        archive_reason_column,
        Qt.Horizontal,
        Qt.DisplayRole,
    ) == "Archive Reason"
    assert proxy_model.index(0, archive_reason_column).data(Qt.DisplayRole) == (
        "Returned home"
    )

    page._select_tab("active")
    qapp.processEvents()

    assert page.table is table
    assert page.table.itemDelegate() is delegate
    assert page._row_move_animator is animator
    assert set(_proxy_ids(page)) == {10, 20, 30}


def test_color_update_targets_one_source_row_without_model_rebuild(
    missionaries_page,
    monkeypatch,
):
    page, _service = missionaries_page
    source_model = page._missionary_model
    expected_source_row = source_model.source_row_for_id(20)
    update_calls = []
    changed_ranges = []
    reset_count = []
    full_filter_calls = []

    original_update_record = source_model.update_record

    def record_update(updated):
        update_calls.append(updated.id)
        return original_update_record(updated)

    monkeypatch.setattr(source_model, "update_record", record_update)
    monkeypatch.setattr(
        page,
        "_apply_filters",
        lambda: full_filter_calls.append(True),
    )
    source_model.dataChanged.connect(
        lambda top_left, bottom_right, roles: changed_ranges.append(
            (top_left.row(), bottom_right.row(), list(roles))
        )
    )
    source_model.modelReset.connect(lambda: reset_count.append(True))

    page._set_missionary_row_color(20, "purple")

    assert update_calls == [20]
    assert full_filter_calls == []
    assert reset_count == []
    assert len(changed_ranges) == 1
    assert changed_ranges[0][0:2] == (
        expected_source_row,
        expected_source_row,
    )
    assert ROW_COLOR_ROLE in changed_ranges[0][2]
    assert source_model.record_by_id(20).row_color == "purple"


def test_real_page_path_queues_color_save_without_blocking_ui(
    missionaries_page,
    monkeypatch,
):
    from ui.pages import missionaries_page as page_module

    page, service = missionaries_page

    class DeferredLoader:
        def __init__(self, parent=None):
            self.parent = parent
            self.operation = None
            self.on_success = None
            self.on_error = None

        def request(self, operation, *, on_success=None, on_error=None):
            self.operation = operation
            self.on_success = on_success
            self.on_error = on_error
            return 1

        def complete(self):
            try:
                result = self.operation()
            except Exception as exc:
                self.on_error(exc)
            else:
                self.on_success(result)

    monkeypatch.setattr(page_module, "LatestRequestLoader", DeferredLoader)
    page._background_loads_enabled = True

    page._set_missionary_row_color(20, "green")

    loader = page._row_color_mutation_loaders[20]
    source_index = page._missionary_model.index_for_id(20)
    assert service.color_calls == []
    assert source_index.data(PENDING_ROLE) is True
    assert page._missionary_model.record_by_id(20).row_color is None

    loader.complete()

    assert service.color_calls == [(20, "green")]
    assert source_index.data(PENDING_ROLE) is False
    assert page._missionary_model.record_by_id(20).row_color == "green"
    assert 20 not in page._row_color_mutation_loaders


def test_selected_ids_survive_proxy_sort_and_remain_deterministic(
    missionaries_page,
    qapp,
):
    page, _service = missionaries_page
    selection_model = page.table.selectionModel()

    for missionary_id in (30, 10):
        selection_model.select(
            page._missionary_proxy.index_for_id(missionary_id, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )

    assert page._selected_missionary_ids() == [10, 30]

    full_name_column = _column_index(page._missionary_model, "full_name")
    page.table.sortByColumn(full_name_column, Qt.DescendingOrder)
    qapp.processEvents()

    assert _proxy_ids(page) == [10, 20, 30]
    assert page._selected_missionary_ids() == [10, 30]

    page.table.sortByColumn(full_name_column, Qt.AscendingOrder)
    qapp.processEvents()

    assert _proxy_ids(page) == [30, 20, 10]
    assert page._selected_missionary_ids() == [10, 30]


def test_refresh_reorder_animation_wraps_active_and_archive_snapshots(
    missionaries_page,
    monkeypatch,
    qapp,
):
    page, service = missionaries_page
    animation_events = []
    monkeypatch.setattr(
        page._row_move_animator,
        "capture_before",
        lambda: animation_events.append("before"),
    )
    monkeypatch.setattr(
        page._row_move_animator,
        "animate_after",
        lambda duration=200: animation_events.append("after"),
    )

    snapshot = {
        "active": service.active,
        "archived": service.archived,
        "groups": [],
    }
    page._apply_missionaries_snapshot(snapshot)
    assert animation_events == ["before", "after"]

    animation_events.clear()
    page._select_tab("archive")
    qapp.processEvents()
    page._apply_missionaries_snapshot(snapshot)
    assert animation_events == ["before", "after"]
