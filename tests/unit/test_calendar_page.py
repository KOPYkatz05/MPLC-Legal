from datetime import date, timedelta
from types import SimpleNamespace

from ui.pages import calendar_page
from ui.pages.calendar_page import (
    AppointmentItem,
    CALENDAR_MODE_MONTH,
    CALENDAR_MODE_WEEK,
    TAB_CALENDAR,
    TAB_HISTORY,
    CalendarPage,
    appointment_bucket,
    month_grid_dates,
    visible_range_for_mode,
    week_start_for,
)


def _appointment(
    *,
    full_name="Jane Missionary",
    appointment_type="Interpol",
    days_offset=0,
    today=None,
):
    today = today or date(2026, 6, 9)
    appt_date = today + timedelta(days=days_offset)
    bucket = appointment_bucket(appt_date, today)
    return AppointmentItem(
        missionary_id=1,
        full_name=full_name,
        current_stage="INTERPOL",
        date=appt_date,
        type=appointment_type,
        color="#7C3AED",
        field="interpol_appointment_date",
        days_offset=days_offset,
        bucket=bucket,
        appointment_id=99,
    )


def _select_combo_value(combo, value):
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo value not found: {value}")


def _build_page(monkeypatch, qapp, appointments):
    _ = qapp
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_appointments",
        lambda self: list(appointments),
    )
    main_window = SimpleNamespace()
    return CalendarPage(main_window)


def test_appointment_bucket_names_relative_dates():
    today = date(2026, 6, 9)

    assert appointment_bucket(today - timedelta(days=1), today) == "overdue"
    assert appointment_bucket(today, today) == "today"
    assert appointment_bucket(today + timedelta(days=7), today) == "next_7"
    assert appointment_bucket(today + timedelta(days=8), today) == "later"


def test_week_start_for_uses_monday():
    assert week_start_for(date(2026, 6, 9)) == date(2026, 6, 8)
    assert week_start_for(date(2026, 6, 14)) == date(2026, 6, 8)
    assert week_start_for(date(2026, 6, 15)) == date(2026, 6, 15)


def test_month_grid_dates_cover_complete_monday_sunday_weeks():
    grid = month_grid_dates(2026, 6)

    assert grid[0] == date(2026, 6, 1)
    assert grid[-1] == date(2026, 7, 5)
    assert len(grid) == 35
    assert grid[0].weekday() == 0
    assert grid[-1].weekday() == 6


def test_visible_range_for_mode_returns_week_or_month_dates():
    anchor = date(2026, 6, 9)

    assert visible_range_for_mode(CALENDAR_MODE_WEEK, anchor) == [
        date(2026, 6, 8) + timedelta(days=offset)
        for offset in range(7)
    ]
    assert visible_range_for_mode(CALENDAR_MODE_MONTH, anchor)[0] == date(
        2026,
        6,
        1,
    )


def test_history_filters_by_search_type_and_status(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Gunner Hamblin Power", days_offset=-2),
        _appointment(
            full_name="Mia Maryanne Walker",
            appointment_type="Biometric",
            days_offset=0,
        ),
        _appointment(
            full_name="Jayna Suzanne Koyle",
            appointment_type="Pickup",
            days_offset=5,
        ),
        _appointment(
            full_name="Lucille Victoria Skidmore",
            appointment_type="Pickup",
            days_offset=12,
        ),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        filtered = page._apply_history_filters(appointments)
        assert [item.full_name for item in filtered] == [
            "Gunner Hamblin Power",
            "Mia Maryanne Walker",
            "Jayna Suzanne Koyle",
            "Lucille Victoria Skidmore",
        ]

        page.history_search_edit.setText("jayna")
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == ["Jayna Suzanne Koyle"]

        page.history_search_edit.clear()
        _select_combo_value(page.history_type_combo, "Pickup")
        _select_combo_value(page.history_status_combo, "upcoming")
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == [
            "Jayna Suzanne Koyle",
            "Lucille Victoria Skidmore",
        ]
    finally:
        page.close()


def test_calendar_filters_affect_visible_chips(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Visible Interpol", days_offset=1),
        _appointment(
            full_name="Visible Pickup",
            appointment_type="Pickup",
            days_offset=2,
        ),
        _appointment(full_name="Outside Week", days_offset=10),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._anchor_date = date(2026, 6, 9)
        visible_dates = set(
            visible_range_for_mode(CALENDAR_MODE_WEEK, page._anchor_date)
        )
        filtered = [
            item
            for item in page._apply_calendar_filters(appointments)
            if item.date in visible_dates
        ]
        assert [item.full_name for item in filtered] == [
            "Visible Interpol",
            "Visible Pickup",
        ]

        page._calendar_type_filter = "Pickup"
        filtered = [
            item
            for item in page._apply_calendar_filters(appointments)
            if item.date in visible_dates
        ]
        assert [item.full_name for item in filtered] == ["Visible Pickup"]
    finally:
        page.close()


def test_overflow_jump_filters_history_to_exact_date(monkeypatch, qapp):
    target = date(2026, 6, 11)
    appointments = [
        _appointment(full_name="Target One", days_offset=2),
        _appointment(full_name="Other Day", days_offset=3),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._show_history_for_date(target)

        assert page._history_exact_date == target
        assert page.tab_stack.currentIndex() == page.history_index
        assert page._selected_tab == TAB_HISTORY
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == ["Target One"]
    finally:
        page.close()


def test_needs_attention_includes_overdue_and_today(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Past Person", days_offset=-3),
        _appointment(full_name="Today Person", days_offset=0),
        _appointment(full_name="Future Person", days_offset=3),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        _select_combo_value(page.history_status_combo, "needs_attention")

        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == [
            "Past Person",
            "Today Person",
        ]
    finally:
        page.close()


def test_calendar_page_smoke_defaults_to_calendar_week(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Smoke Test", days_offset=-1),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        assert page._count_label.text() == "1 scheduled appointments"
        assert len(page._appointments) == 1
        assert page._calendar_mode == CALENDAR_MODE_WEEK
        assert page.tab_stack.currentIndex() == page.calendar_index
        assert page._selected_tab == TAB_CALENDAR
    finally:
        page.close()


def test_calendar_toolbar_is_grouped_with_calendar_body(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Overdue Person", days_offset=-10),
        _appointment(full_name="Visible Person", days_offset=1),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        toolbar = page.findChild(calendar_page.QFrame, "CalendarToolbar")
        grid = page.findChild(calendar_page.QFrame, "CalendarGridCard")
        overdue_strip = page.findChild(calendar_page.QFrame, "CalendarOverdueStrip")

        assert toolbar is not None
        assert grid is not None
        assert overdue_strip is not None
        assert toolbar.parentWidget() is grid.parentWidget()

        parent_layout = toolbar.parentWidget().layout()
        assert parent_layout.indexOf(overdue_strip) < parent_layout.indexOf(toolbar)
        assert parent_layout.indexOf(toolbar) < parent_layout.indexOf(grid)
    finally:
        page.close()


def test_history_uses_focus_card_for_single_missionary_search(monkeypatch, qapp):
    appointments = [
        _appointment(
            full_name="Addelyn Sylvia Holt",
            appointment_type="Interpol",
            days_offset=-63,
        ),
        _appointment(
            full_name="Addelyn Sylvia Holt",
            appointment_type="Biometric",
            days_offset=4,
        ),
        _appointment(full_name="Someone Else", days_offset=2),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._select_tab(TAB_HISTORY)
        page.history_search_edit.setText("Holt")

        focus_card = page.history_layout.itemAt(0).widget()
        focus_list = focus_card.findChild(
            calendar_page.QWidget,
            "CalendarHistoryFocusList",
        )
        stale_day_card = focus_card.findChild(
            calendar_page.QWidget,
            "CalendarDayCard",
        )
        assert focus_card is not None
        assert focus_card.objectName() == "CalendarHistoryFocusCard"
        assert focus_list is not None
        assert focus_card.viewLayout.count() == 1
        assert focus_list.layout().count() == 3
        assert stale_day_card is None
    finally:
        page.close()


def test_history_rows_include_complete_and_missed_actions(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Addelyn Sylvia Holt", days_offset=-1),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._select_tab(TAB_HISTORY)
        page.history_search_edit.setText("Holt")

        assert (
            page.findChild(
                calendar_page.QWidget,
                "CalendarCompleteAppointmentButton",
            )
            is not None
        )
        assert (
            page.findChild(
                calendar_page.QWidget,
                "CalendarMissedAppointmentButton",
            )
            is not None
        )
    finally:
        page.close()
from datetime import date, timedelta
from types import SimpleNamespace

from ui.pages import calendar_page
from ui.pages.calendar_page import (
    AppointmentItem,
    CALENDAR_MODE_MONTH,
    CALENDAR_MODE_WEEK,
    TAB_CALENDAR,
    TAB_HISTORY,
    CalendarPage,
    appointment_bucket,
    month_grid_dates,
    visible_range_for_mode,
    week_start_for,
)


def _appointment(
    *,
    full_name="Jane Missionary",
    appointment_type="Interpol",
    days_offset=0,
    today=None,
):
    today = today or date(2026, 6, 9)
    appt_date = today + timedelta(days=days_offset)
    bucket = appointment_bucket(appt_date, today)
    return AppointmentItem(
        missionary_id=1,
        full_name=full_name,
        current_stage="INTERPOL",
        date=appt_date,
        type=appointment_type,
        color="#7C3AED",
        field="interpol_appointment_date",
        days_offset=days_offset,
        bucket=bucket,
    )


def _select_combo_value(combo, value):
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo value not found: {value}")


def _build_page(monkeypatch, qapp, appointments):
    _ = qapp
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_appointments",
        lambda self: list(appointments),
    )
    main_window = SimpleNamespace()
    return CalendarPage(main_window)


def test_appointment_bucket_names_relative_dates():
    today = date(2026, 6, 9)

    assert appointment_bucket(today - timedelta(days=1), today) == "overdue"
    assert appointment_bucket(today, today) == "today"
    assert appointment_bucket(today + timedelta(days=7), today) == "next_7"
    assert appointment_bucket(today + timedelta(days=8), today) == "later"


def test_week_start_for_uses_monday():
    assert week_start_for(date(2026, 6, 9)) == date(2026, 6, 8)
    assert week_start_for(date(2026, 6, 14)) == date(2026, 6, 8)
    assert week_start_for(date(2026, 6, 15)) == date(2026, 6, 15)


def test_month_grid_dates_cover_complete_monday_sunday_weeks():
    grid = month_grid_dates(2026, 6)

    assert grid[0] == date(2026, 6, 1)
    assert grid[-1] == date(2026, 7, 5)
    assert len(grid) == 35
    assert grid[0].weekday() == 0
    assert grid[-1].weekday() == 6


def test_visible_range_for_mode_returns_week_or_month_dates():
    anchor = date(2026, 6, 9)

    assert visible_range_for_mode(CALENDAR_MODE_WEEK, anchor) == [
        date(2026, 6, 8) + timedelta(days=offset)
        for offset in range(7)
    ]
    assert visible_range_for_mode(CALENDAR_MODE_MONTH, anchor)[0] == date(
        2026,
        6,
        1,
    )


def test_history_filters_by_search_type_and_status(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Gunner Hamblin Power", days_offset=-2),
        _appointment(
            full_name="Mia Maryanne Walker",
            appointment_type="Biometric",
            days_offset=0,
        ),
        _appointment(
            full_name="Jayna Suzanne Koyle",
            appointment_type="Pickup",
            days_offset=5,
        ),
        _appointment(
            full_name="Lucille Victoria Skidmore",
            appointment_type="Pickup",
            days_offset=12,
        ),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        filtered = page._apply_history_filters(appointments)
        assert [item.full_name for item in filtered] == [
            "Gunner Hamblin Power",
            "Mia Maryanne Walker",
            "Jayna Suzanne Koyle",
            "Lucille Victoria Skidmore",
        ]

        page.history_search_edit.setText("jayna")
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == ["Jayna Suzanne Koyle"]

        page.history_search_edit.clear()
        _select_combo_value(page.history_type_combo, "Pickup")
        _select_combo_value(page.history_status_combo, "upcoming")
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == [
            "Jayna Suzanne Koyle",
            "Lucille Victoria Skidmore",
        ]
    finally:
        page.close()


def test_calendar_filters_affect_visible_chips(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Visible Interpol", days_offset=1),
        _appointment(
            full_name="Visible Pickup",
            appointment_type="Pickup",
            days_offset=2,
        ),
        _appointment(full_name="Outside Week", days_offset=10),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._anchor_date = date(2026, 6, 9)
        visible_dates = set(
            visible_range_for_mode(CALENDAR_MODE_WEEK, page._anchor_date)
        )
        filtered = [
            item
            for item in page._apply_calendar_filters(appointments)
            if item.date in visible_dates
        ]
        assert [item.full_name for item in filtered] == [
            "Visible Interpol",
            "Visible Pickup",
        ]

        page._calendar_type_filter = "Pickup"
        filtered = [
            item
            for item in page._apply_calendar_filters(appointments)
            if item.date in visible_dates
        ]
        assert [item.full_name for item in filtered] == ["Visible Pickup"]
    finally:
        page.close()


def test_overflow_jump_filters_history_to_exact_date(monkeypatch, qapp):
    target = date(2026, 6, 11)
    appointments = [
        _appointment(full_name="Target One", days_offset=2),
        _appointment(full_name="Other Day", days_offset=3),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._show_history_for_date(target)

        assert page._history_exact_date == target
        assert page.tab_stack.currentIndex() == page.history_index
        assert page._selected_tab == TAB_HISTORY
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == ["Target One"]
    finally:
        page.close()


def test_needs_attention_includes_overdue_and_today(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Past Person", days_offset=-3),
        _appointment(full_name="Today Person", days_offset=0),
        _appointment(full_name="Future Person", days_offset=3),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        _select_combo_value(page.history_status_combo, "needs_attention")

        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == [
            "Past Person",
            "Today Person",
        ]
    finally:
        page.close()


def test_calendar_page_smoke_defaults_to_calendar_week(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Smoke Test", days_offset=-1),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        assert page._count_label.text() == "1 scheduled appointments"
        assert len(page._appointments) == 1
        assert page._calendar_mode == CALENDAR_MODE_WEEK
        assert page.tab_stack.currentIndex() == page.calendar_index
        assert page._selected_tab == TAB_CALENDAR
    finally:
        page.close()
