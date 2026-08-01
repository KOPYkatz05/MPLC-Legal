"""Model/view data plumbing for the Active and Archive missionary tables.

The source model keeps each missionary's identity stable while the proxy owns
all presentation ordering and filtering.  Visual styling is intentionally
represented by semantic roles; the model never paints cell backgrounds.
"""

from __future__ import annotations

from datetime import date, datetime
from numbers import Number
from typing import Any, Iterable, Mapping

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)


MISSIONARY_ID_ROLE = Qt.UserRole + 100
SORT_VALUE_ROLE = Qt.UserRole + 101
ROW_COLOR_ROLE = Qt.UserRole + 102
ROW_ACCENT_ROLE = Qt.UserRole + 103
PENDING_ROLE = Qt.UserRole + 104
RECORD_ROLE = Qt.UserRole + 105
COLUMN_KEY_ROLE = Qt.UserRole + 106


_MISSING = object()
_DATE_COLUMN_KEYS = {
    "date_of_birth",
    "arrival_date",
    "release_date",
    "visa_expiration",
    "passport_expiration",
    "residency_expiration",
    "prorroga_expiration",
    "carnet_issue_date",
    "cancelacion_date",
    "interpol_appointment_date",
    "biometric_appointment_date",
    "pickup_appointment_date",
}
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y")


def _record_value(record: object, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _record_id(record: object) -> Any:
    return _record_value(record, "id", None)


def _column_value(column: object, record: object) -> Any:
    getter = getattr(column, "getter", None)
    if not callable(getter):
        raise TypeError("Missionary table columns must provide a callable getter")
    return getter(record)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def _normalized_sort_value(column: object, record: object, display: Any) -> Any:
    key = str(getattr(column, "key", ""))
    raw = _record_value(record, key, _MISSING)
    value = display if raw is _MISSING else raw

    if value is None:
        return None

    if key in _DATE_COLUMN_KEYS or key.endswith("_date"):
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value
    if isinstance(value, Number):
        return value

    text = str(value).strip()
    return text.casefold() if text else None


def _last_name_first(full_name: Any) -> str:
    parts = str(full_name or "").strip().split()
    if len(parts) <= 1:
        return " ".join(parts)

    surname_count = 2 if len(parts) >= 4 else 1
    surname = " ".join(parts[-surname_count:])
    given_names = " ".join(parts[:-surname_count])
    return f"{surname}, {given_names}" if given_names else surname


def _search_text(record: object, columns: Iterable[object]) -> str:
    record_id = _record_id(record)
    missionary_code = _record_value(record, "missionary_code", "")
    full_name = _record_value(record, "full_name", "")
    preferred_name = _record_value(record, "preferred_name", "")
    values = [
        record_id,
        missionary_code,
        full_name,
        preferred_name,
        preferred_name or _last_name_first(full_name),
    ]

    # Including configured display values makes future/custom columns searchable
    # without rebuilding a second field registry in the proxy.
    for column in columns:
        try:
            values.append(_column_value(column, record))
        except (AttributeError, TypeError, ValueError):
            continue

    return " ".join(
        str(value).strip()
        for value in values
        if value is not None and str(value).strip()
    ).casefold()


def _is_empty_sort_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _comparison_key(value: Any) -> tuple[int, Any]:
    if isinstance(value, datetime):
        return 0, value.isoformat()
    if isinstance(value, date):
        return 0, value.isoformat()
    if isinstance(value, bool):
        return 1, int(value)
    if isinstance(value, Number):
        return 1, value
    return 2, str(value).casefold()


def _stable_id_key(value: Any) -> tuple[int, Any]:
    if isinstance(value, Number) and not isinstance(value, bool):
        return 0, value
    return 1, str(value or "").casefold()


class MissionaryTableModel(QAbstractTableModel):
    """Table model with stable missionary identity and targeted row updates."""

    def __init__(self, columns: Iterable[object] = (), parent=None):
        super().__init__(parent)
        self._columns = list(columns)
        self._records: list[object] = []
        self._row_by_id: dict[Any, int] = {}
        self._search_by_id: dict[Any, str] = {}
        self._pending_ids: set[Any] = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        column_number = index.column()
        if not (0 <= row < len(self._records)):
            return None
        if not (0 <= column_number < len(self._columns)):
            return None

        record = self._records[row]
        column = self._columns[column_number]

        if role in (Qt.DisplayRole, Qt.EditRole):
            return _column_value(column, record)
        if role == MISSIONARY_ID_ROLE:
            return _record_id(record)
        if role == SORT_VALUE_ROLE:
            display = _column_value(column, record)
            return _normalized_sort_value(column, record, display)
        if role == ROW_COLOR_ROLE:
            return _record_value(record, "row_color", None)
        if role == ROW_ACCENT_ROLE:
            return _record_value(record, "row_accent", None)
        if role == PENDING_ROLE:
            return _record_id(record) in self._pending_ids
        if role == RECORD_ROLE:
            return record
        if role == COLUMN_KEY_ROLE:
            return str(getattr(column, "key", ""))
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._columns):
            return str(getattr(self._columns[section], "label", ""))
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def set_columns(self, columns: Iterable[object]) -> None:
        columns = list(columns)
        for column in columns:
            if not hasattr(column, "key") or not hasattr(column, "label"):
                raise TypeError("Missionary table columns need key and label fields")
            if not callable(getattr(column, "getter", None)):
                raise TypeError("Missionary table columns need a callable getter")

        self.beginResetModel()
        self._columns = columns
        self._rebuild_search_cache()
        self.endResetModel()

    def set_records(self, records: Iterable[object]) -> None:
        records = list(records)
        row_by_id: dict[Any, int] = {}
        for row, record in enumerate(records):
            missionary_id = _record_id(record)
            if missionary_id is None:
                raise ValueError("Every missionary table record must have an id")
            if missionary_id in row_by_id:
                raise ValueError(
                    f"Duplicate missionary id in table records: {missionary_id!r}"
                )
            row_by_id[missionary_id] = row

        # Background snapshots normally contain new record objects even when
        # the visible population has not changed. Keep indexes and selection
        # stable in that common case; a model reset is only needed when the
        # source row identities or their source ordering actually change.
        if list(row_by_id) == list(self._row_by_id):
            changed_rows = [
                row
                for row, (current, replacement) in enumerate(
                    zip(self._records, records)
                )
                if current is not replacement and current != replacement
            ]
            self._records = records
            self._row_by_id = row_by_id
            self._pending_ids.intersection_update(row_by_id)
            self._rebuild_search_cache()
            self._emit_changed_row_ranges(changed_rows)
            return

        self.beginResetModel()
        self._records = records
        self._row_by_id = row_by_id
        self._pending_ids.intersection_update(row_by_id)
        self._rebuild_search_cache()
        self.endResetModel()

    def update_record(self, updated: object) -> bool:
        missionary_id = _record_id(updated)
        row = self._row_by_id.get(missionary_id, -1)
        if row < 0:
            return False

        self._records[row] = updated
        self._search_by_id[missionary_id] = _search_text(updated, self._columns)
        if self._columns:
            self.dataChanged.emit(
                self.index(row, 0),
                self.index(row, len(self._columns) - 1),
                [
                    Qt.DisplayRole,
                    Qt.EditRole,
                    SORT_VALUE_ROLE,
                    ROW_COLOR_ROLE,
                    ROW_ACCENT_ROLE,
                    RECORD_ROLE,
                ],
            )
        return True

    def upsert_record(self, record: object) -> bool:
        """Update an existing row or append a new one.

        Returns ``True`` when a new source row was inserted and ``False`` when
        the existing row was updated.  New rows are appended to the stable
        source order; the proxy is responsible for their visible position.
        """
        missionary_id = _record_id(record)
        if missionary_id is None:
            raise ValueError("Every missionary table record must have an id")
        if missionary_id in self._row_by_id:
            self.update_record(record)
            return False

        row = len(self._records)
        self.beginInsertRows(QModelIndex(), row, row)
        self._records.append(record)
        self._row_by_id[missionary_id] = row
        self._search_by_id[missionary_id] = _search_text(record, self._columns)
        self.endInsertRows()
        return True

    def remove_record(self, missionary_id: Any) -> object | None:
        """Remove one missionary with structural model signals."""
        row = self._row_by_id.get(missionary_id, -1)
        if row < 0:
            return None

        self.beginRemoveRows(QModelIndex(), row, row)
        removed = self._records.pop(row)
        self._row_by_id.pop(missionary_id, None)
        self._search_by_id.pop(missionary_id, None)
        self._pending_ids.discard(missionary_id)
        for changed_row in range(row, len(self._records)):
            self._row_by_id[_record_id(self._records[changed_row])] = changed_row
        self.endRemoveRows()
        return removed

    def set_pending(self, missionary_id: Any, pending: bool) -> None:
        row = self._row_by_id.get(missionary_id, -1)
        if row < 0:
            return

        was_pending = missionary_id in self._pending_ids
        if pending:
            self._pending_ids.add(missionary_id)
        else:
            self._pending_ids.discard(missionary_id)
        if pending == was_pending or not self._columns:
            return

        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, len(self._columns) - 1),
            [PENDING_ROLE],
        )

    def record_for_source_row(self, row: int) -> object | None:
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def record_by_id(self, missionary_id: Any) -> object | None:
        return self.record_for_source_row(self.source_row_for_id(missionary_id))

    def source_row_for_id(self, missionary_id: Any) -> int:
        return self._row_by_id.get(missionary_id, -1)

    def index_for_id(self, missionary_id: Any, column: int = 0) -> QModelIndex:
        row = self.source_row_for_id(missionary_id)
        if row < 0 or not 0 <= column < len(self._columns):
            return QModelIndex()
        return self.index(row, column)

    def records(self) -> list[object]:
        return list(self._records)

    def column_key(self, column: int) -> str | None:
        if not 0 <= column < len(self._columns):
            return None
        return str(getattr(self._columns[column], "key", ""))

    def search_text_for_source_row(self, row: int) -> str:
        record = self.record_for_source_row(row)
        if record is None:
            return ""
        return self._search_by_id.get(_record_id(record), "")

    def _rebuild_search_cache(self) -> None:
        self._search_by_id = {
            _record_id(record): _search_text(record, self._columns)
            for record in self._records
        }

    def _emit_changed_row_ranges(self, rows: Iterable[int]) -> None:
        rows = sorted(set(rows))
        if not rows or not self._columns:
            return

        roles = [
            Qt.DisplayRole,
            Qt.EditRole,
            SORT_VALUE_ROLE,
            ROW_COLOR_ROLE,
            ROW_ACCENT_ROLE,
            RECORD_ROLE,
        ]
        range_start = previous = rows[0]
        for row in rows[1:]:
            if row == previous + 1:
                previous = row
                continue
            self.dataChanged.emit(
                self.index(range_start, 0),
                self.index(previous, len(self._columns) - 1),
                roles,
            )
            range_start = previous = row
        self.dataChanged.emit(
            self.index(range_start, 0),
            self.index(previous, len(self._columns) - 1),
            roles,
        )


class MissionaryFilterProxyModel(QSortFilterProxyModel):
    """Shared Active/Archive filtering and typed, stable sorting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view_mode = "active"
        self._search_text = ""
        self._stage_filter: str | None = None
        self._nationality_filter: str | None = None
        self._group_member_ids: set[Any] | None = None
        self.setDynamicSortFilter(True)
        self.setSortRole(SORT_VALUE_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def set_view_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().casefold()
        if normalized not in {"active", "archive"}:
            raise ValueError("Missionary view mode must be 'active' or 'archive'")
        self._set_filter_value("_view_mode", normalized)

    def set_search_text(self, text: Any) -> None:
        normalized = " ".join(str(text or "").casefold().split())
        self._set_filter_value("_search_text", normalized)

    def set_stage_filter(self, stage: Any) -> None:
        normalized = str(stage).strip().casefold() if stage else None
        self._set_filter_value("_stage_filter", normalized)

    def set_nationality_filter(self, nationality: Any) -> None:
        normalized = (
            str(nationality).strip().casefold() if nationality else None
        )
        self._set_filter_value("_nationality_filter", normalized)

    def set_group_member_ids(self, ids_or_none: Iterable[Any] | None) -> None:
        normalized = None if ids_or_none is None else set(ids_or_none)
        self._set_filter_value("_group_member_ids", normalized)

    def filterAcceptsRow(self, source_row, source_parent):
        source_model = self.sourceModel()
        if source_model is None:
            return False

        index = source_model.index(source_row, 0, source_parent)
        record = index.data(RECORD_ROLE)
        if record is None:
            return False

        status = str(_record_value(record, "status", "ACTIVE") or "ACTIVE")
        is_archived = status.strip().casefold() == "archived"
        if self._view_mode == "archive":
            if not is_archived:
                return False
        elif is_archived:
            return False

        if self._search_text:
            if isinstance(source_model, MissionaryTableModel):
                searchable = source_model.search_text_for_source_row(source_row)
            else:
                searchable = _search_text(record, ())
            if self._search_text not in searchable:
                return False

        if self._stage_filter:
            stage = str(_record_value(record, "current_stage", "") or "")
            if stage.strip().casefold() != self._stage_filter:
                return False

        if self._nationality_filter:
            nationality = str(_record_value(record, "nationality", "") or "")
            if nationality.strip().casefold() != self._nationality_filter:
                return False

        if self._group_member_ids is not None:
            if _record_id(record) not in self._group_member_ids:
                return False

        return True

    def lessThan(self, left, right):
        left_value = left.data(SORT_VALUE_ROLE)
        right_value = right.data(SORT_VALUE_ROLE)
        left_empty = _is_empty_sort_value(left_value)
        right_empty = _is_empty_sort_value(right_value)

        if left_empty != right_empty:
            if self.sortOrder() == Qt.DescendingOrder:
                return left_empty
            return right_empty

        if not left_empty:
            left_key = _comparison_key(left_value)
            right_key = _comparison_key(right_value)
            if left_key != right_key:
                return left_key < right_key

        left_id = left.data(MISSIONARY_ID_ROLE)
        right_id = right.data(MISSIONARY_ID_ROLE)
        return _stable_id_key(left_id) < _stable_id_key(right_id)

    def records_in_view(self) -> list[object]:
        records = []
        for row in range(self.rowCount()):
            index = self.index(row, 0)
            record = index.data(RECORD_ROLE)
            if record is not None:
                records.append(record)
        return records

    def index_for_id(self, missionary_id: Any, column: int = 0) -> QModelIndex:
        source_model = self.sourceModel()
        if not isinstance(source_model, MissionaryTableModel):
            return QModelIndex()
        return self.mapFromSource(source_model.index_for_id(missionary_id, column))

    def record_by_id(self, missionary_id: Any) -> object | None:
        source_model = self.sourceModel()
        if isinstance(source_model, MissionaryTableModel):
            return source_model.record_by_id(missionary_id)
        return None

    def _set_filter_value(self, attribute: str, value: Any) -> None:
        if getattr(self, attribute) == value:
            return

        begin_change = getattr(self, "beginFilterChange", None)
        end_change = getattr(self, "endFilterChange", None)
        if callable(begin_change) and callable(end_change):
            begin_change()
            setattr(self, attribute, value)
            end_change(QSortFilterProxyModel.Direction.Rows)
            return

        setattr(self, attribute, value)
        self.invalidateFilter()
