from datetime import date, timedelta
from types import SimpleNamespace

from ui.pages import calendar_page
from ui.pages.calendar_page import (
    AppointmentItem,
    CALENDAR_MODE_MONTH,
    CALENDAR_MODE_WEEK,
    TAB_CALENDAR,
    TAB_HISTORY,
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
    APPOINTMENT_STATUS_SCHEDULED,
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
    status=APPOINTMENT_STATUS_SCHEDULED,
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
        status=status,
        appointment_id=99,
    )


def _select_combo_value(combo, value):
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo value not found: {value}")


def _build_page(monkeypatch, qapp, appointments, tasks=None):
    _ = qapp
    tasks = tasks or []
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_appointments",
        lambda self: list(appointments),
    )
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_history_appointments",
        lambda self: list(appointments),
    )
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_tasks",
        lambda self: list(tasks),
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


def test_visible_range_for_mode_returns_month_dates():
    anchor = date(2026, 6, 9)

    assert visible_range_for_mode(CALENDAR_MODE_WEEK, anchor)[0] == date(
        2026,
        6,
        1,
    )
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
            status=APPOINTMENT_STATUS_MISSED,
        ),
        _appointment(
            full_name="Lucille Victoria Skidmore",
            appointment_type="Pickup",
            days_offset=12,
        ),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        _select_combo_value(page.history_sort_combo, "asc")
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
        _select_combo_value(page.history_status_combo, APPOINTMENT_STATUS_MISSED)
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == [
            "Jayna Suzanne Koyle",
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
        _appointment(full_name="Visible Later", days_offset=10),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._anchor_date = date(2026, 6, 9)
        visible_dates = set(
            visible_range_for_mode(CALENDAR_MODE_MONTH, page._anchor_date)
        )
        filtered = [
            item
            for item in page._apply_calendar_filters(appointments)
            if item.date in visible_dates
        ]
        assert [item.full_name for item in filtered] == [
            "Visible Interpol",
            "Visible Pickup",
            "Visible Later",
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


def test_history_status_filter_can_show_missed_only(monkeypatch, qapp):
    appointments = [
        _appointment(
            full_name="Missed Person",
            days_offset=-3,
            status=APPOINTMENT_STATUS_MISSED,
        ),
        _appointment(
            full_name="Completed Person",
            days_offset=-1,
            status=APPOINTMENT_STATUS_COMPLETED,
        ),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        _select_combo_value(page.history_status_combo, APPOINTMENT_STATUS_MISSED)

        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == ["Missed Person"]
    finally:
        page.close()


def test_calendar_page_smoke_defaults_to_calendar_month(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Smoke Test", days_offset=-1),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        assert page._count_label.text() == "1 scheduled appointments"
        assert len(page._appointments) == 1
        assert page._calendar_mode == CALENDAR_MODE_MONTH
        assert page.findChild(calendar_page.QWidget, "CalendarModeSegment") is None
        assert page.tab_stack.currentIndex() == page.calendar_index
        assert page._selected_tab == TAB_CALENDAR
    finally:
        page.close()


def _task(
    *,
    title="Prepare cita packet",
    due_date=date(2026, 6, 10),
    work_date=date(2026, 6, 10),
    status="OPEN",
):
    return {
        "id": 11,
        "title": title,
        "description": "",
        "status": status,
        "priority": "NORMAL",
        "due_date": due_date,
        "work_date": work_date,
        "project_id": None,
        "project_title": "",
        "missionary_id": None,
        "missionary_name": "",
        "appointment_field": None,
    }


def test_calendar_shows_tasks_planned_on_work_date(monkeypatch, qapp):
    task = _task(
        due_date=date(2026, 6, 20),
        work_date=date(2026, 6, 10),
    )
    page = _build_page(monkeypatch, qapp, [], tasks=[task])

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        task_button = page.findChild(
            calendar_page.QWidget,
            "CalendarTaskChipButton",
        )
        assert task_button is not None
        assert "Task -" in task_button.text()
    finally:
        page.close()


def test_calendar_drop_updates_work_date_only(monkeypatch, qapp):
    page = _build_page(monkeypatch, qapp, [], tasks=[_task()])
    calls = []

    class FakeSecretaryWorkService:
        def update_task(self, task_id, **updates):
            calls.append((task_id, updates))

    class FakeDropEvent:
        def __init__(self):
            self.accepted = False
            self.ignored = False
            self.mime = calendar_page.QMimeData()
            self.mime.setData(calendar_page.TASK_DRAG_MIME, b"11")

        def mimeData(self):
            return self.mime

        def acceptProposedAction(self):
            self.accepted = True

        def ignore(self):
            self.ignored = True

    monkeypatch.setattr(
        calendar_page,
        "SecretaryWorkService",
        FakeSecretaryWorkService,
    )
    monkeypatch.setattr(page, "load_data", lambda: None)
    monkeypatch.setattr(page, "_refresh_office_work_page", lambda: None)

    try:
        event = FakeDropEvent()
        page._task_drop_event(event, date(2026, 6, 15))

        assert event.accepted is True
        assert event.ignored is False
        assert calls == [(11, {"work_date": date(2026, 6, 15)})]
    finally:
        page.close()


def test_calendar_complete_task_marks_done_and_refreshes(monkeypatch, qapp):
    page = _build_page(monkeypatch, qapp, [], tasks=[_task()])
    calls = []
    refreshes = []

    class FakeSecretaryWorkService:
        def complete_task(self, task_id):
            calls.append(task_id)

    monkeypatch.setattr(
        calendar_page,
        "SecretaryWorkService",
        FakeSecretaryWorkService,
    )
    monkeypatch.setattr(page, "load_data", lambda: refreshes.append("calendar"))
    monkeypatch.setattr(
        page,
        "_refresh_office_work_page",
        lambda: refreshes.append("office"),
    )

    try:
        page._complete_task(11)

        assert calls == [11]
        assert refreshes == ["calendar", "office"]
    finally:
        page.close()


def test_done_tasks_remain_visible_with_done_property(monkeypatch, qapp):
    task = _task(status="DONE")
    page = _build_page(monkeypatch, qapp, [], tasks=[task])

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        chip = page.findChild(calendar_page.QWidget, "CalendarTaskChip")
        done_button = page.findChild(calendar_page.QWidget, "CalendarTaskDoneButton")
        assert chip is not None
        assert chip.property("done") is True
        assert done_button is None
    finally:
        page.close()


def test_toolbar_add_task_uses_normal_blank_defaults(monkeypatch, qapp):
    captured = []

    class FakeTaskDialog:
        def __init__(self, service, task=None, defaults=None, parent=None):
            captured.append(
                {
                    "task": task,
                    "defaults": defaults,
                    "parent": parent,
                }
            )

        def exec(self):
            return True

    monkeypatch.setattr(calendar_page, "TaskDialog", FakeTaskDialog)
    page = _build_page(monkeypatch, qapp, [])

    try:
        assert page._add_task() is True
        assert captured[-1]["task"] is None
        assert captured[-1]["defaults"] is None
    finally:
        page.close()


def test_calendar_task_save_refreshes_office_work(monkeypatch, qapp):
    captured = []

    class FakeTaskDialog:
        def __init__(self, service, task=None, defaults=None, parent=None):
            captured.append(defaults)

        def exec(self):
            return True

    office_work = SimpleNamespace(load_count=0)

    def load_data():
        office_work.load_count += 1

    office_work.load_data = load_data
    monkeypatch.setattr(calendar_page, "TaskDialog", FakeTaskDialog)
    page = _build_page(monkeypatch, qapp, [])
    page.main_window = SimpleNamespace(office_work_page=office_work)

    try:
        assert page._add_task(default_work_date=date(2026, 6, 12)) is True
        assert captured[-1] == {"work_date": date(2026, 6, 12)}
        assert office_work.load_count == 1
    finally:
        page.close()


def test_day_dialog_add_task_uses_clicked_date(monkeypatch, qapp):
    target = date(2026, 6, 12)
    page = _build_page(monkeypatch, qapp, [])
    captured = []

    try:
        monkeypatch.setattr(
            page,
            "_add_task",
            lambda default_due_date=None, default_work_date=None:
            captured.append(default_work_date or default_due_date) or True,
        )
        dialog = calendar_page.CalendarDaySummaryDialog(
            page,
            target,
            [],
            [],
        )
        try:
            dialog._add_task()
            assert captured == [target]
        finally:
            dialog.close()
    finally:
        page.close()


def test_empty_day_dialog_shows_no_appointments(monkeypatch, qapp):
    page = _build_page(monkeypatch, qapp, [])

    try:
        dialog = calendar_page.CalendarDaySummaryDialog(
            page,
            date(2026, 6, 12),
            [],
            [],
        )
        try:
            label = dialog.findChild(
                calendar_page.QWidget,
                "CalendarNoAppointmentsLabel",
            )
            assert label is not None
            assert label.text() == "No appointments"
        finally:
            dialog.close()
    finally:
        page.close()


def test_appointment_chip_opens_missionary_detail(monkeypatch, qapp):
    appointment = _appointment(days_offset=1)
    page = _build_page(monkeypatch, qapp, [appointment])
    opened = []

    try:
        monkeypatch.setattr(
            page,
            "_open_missionary",
            lambda missionary_id: opened.append(missionary_id),
        )
        chip = page._make_calendar_chip(appointment)
        button = chip.findChild(
            calendar_page.QWidget,
            "CalendarAppointmentChipButton",
        )
        button.click()

        assert opened == [appointment.missionary_id]
    finally:
        page.close()


def test_appointment_row_click_opens_missionary_detail(monkeypatch, qapp):
    appointment = _appointment(days_offset=1)
    page = _build_page(monkeypatch, qapp, [appointment])
    opened = []

    try:
        monkeypatch.setattr(
            page,
            "_open_missionary",
            lambda missionary_id: opened.append(missionary_id),
        )
        row = page._make_appointment_row(appointment)
        row.mousePressEvent(SimpleNamespace())

        assert opened == [appointment.missionary_id]
    finally:
        page.close()


def test_calendar_open_missionary_delegates_to_main_window(qapp):
    _ = qapp
    opened = []
    page = CalendarPage.__new__(CalendarPage)
    page.main_window = SimpleNamespace(
        open_missionary_detail=lambda missionary_id:
        opened.append(missionary_id)
    )

    page._open_missionary(42)

    assert opened == [42]


def test_collect_appointments_reads_scheduled_service_without_backfill(monkeypatch):
    class FakeAppointmentService:
        def backfill_all(self):
            raise AssertionError("calendar collection should not backfill")

        def list_scheduled_appointments(self):
            return []

    monkeypatch.setattr(
        calendar_page,
        "AppointmentService",
        FakeAppointmentService,
    )
    page = CalendarPage.__new__(CalendarPage)

    assert CalendarPage._collect_appointments(page) == []


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


def test_overdue_strip_opens_actionable_scheduled_overdue_details(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Overdue One", days_offset=-10),
        _appointment(full_name="Overdue Two", days_offset=-9),
        _appointment(full_name="Overdue Three", days_offset=-8),
        _appointment(full_name="Overdue Four", days_offset=-7),
        _appointment(full_name="Visible Person", days_offset=1),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._show_overdue_calendar_details()

        assert page._selected_tab == TAB_CALENDAR
        assert page.tab_stack.currentIndex() == page.calendar_index
        assert page._show_overdue_detail is True
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


def test_history_rows_hide_complete_and_missed_actions_for_closed_items(monkeypatch, qapp):
    appointments = [
        _appointment(
            full_name="Addelyn Sylvia Holt",
            days_offset=-1,
            status=APPOINTMENT_STATUS_COMPLETED,
        ),
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
            is None
        )
        assert (
            page.findChild(
                calendar_page.QWidget,
                "CalendarMissedAppointmentButton",
            )
            is None
        )
    finally:
        page.close()


def test_completed_history_rows_use_completed_text_and_success_tone():
    appointment = _appointment(
        full_name="Addelyn Sylvia Holt",
        days_offset=-14,
        status=APPOINTMENT_STATUS_COMPLETED,
    )

    assert calendar_page.appointment_status_text(appointment) == "Completed"
    assert calendar_page.appointment_tone(appointment) == "success"


from datetime import date, timedelta
from types import SimpleNamespace

from ui.pages import calendar_page
from ui.pages.calendar_page import (
    AppointmentItem,
    CALENDAR_MODE_MONTH,
    CALENDAR_MODE_WEEK,
    TAB_CALENDAR,
    TAB_HISTORY,
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
    APPOINTMENT_STATUS_SCHEDULED,
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
    status=APPOINTMENT_STATUS_SCHEDULED,
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
        status=status,
    )


def _select_combo_value(combo, value):
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo value not found: {value}")


def _build_page(monkeypatch, qapp, appointments, tasks=None):
    _ = qapp
    tasks = tasks or []
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_appointments",
        lambda self: list(appointments),
    )
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_history_appointments",
        lambda self: list(appointments),
    )
    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_collect_tasks",
        lambda self: list(tasks),
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


def test_visible_range_for_mode_returns_month_dates():
    anchor = date(2026, 6, 9)

    assert visible_range_for_mode(CALENDAR_MODE_WEEK, anchor)[0] == date(
        2026,
        6,
        1,
    )
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
            status=APPOINTMENT_STATUS_MISSED,
        ),
        _appointment(
            full_name="Lucille Victoria Skidmore",
            appointment_type="Pickup",
            days_offset=12,
        ),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        _select_combo_value(page.history_sort_combo, "asc")
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
        _select_combo_value(page.history_status_combo, APPOINTMENT_STATUS_MISSED)
        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == [
            "Jayna Suzanne Koyle",
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
        _appointment(full_name="Visible Later", days_offset=10),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._anchor_date = date(2026, 6, 9)
        visible_dates = set(
            visible_range_for_mode(CALENDAR_MODE_MONTH, page._anchor_date)
        )
        filtered = [
            item
            for item in page._apply_calendar_filters(appointments)
            if item.date in visible_dates
        ]
        assert [item.full_name for item in filtered] == [
            "Visible Interpol",
            "Visible Pickup",
            "Visible Later",
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


def test_history_status_filter_can_show_missed_only(monkeypatch, qapp):
    appointments = [
        _appointment(
            full_name="Missed Person",
            days_offset=-3,
            status=APPOINTMENT_STATUS_MISSED,
        ),
        _appointment(
            full_name="Completed Person",
            days_offset=-1,
            status=APPOINTMENT_STATUS_COMPLETED,
        ),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        _select_combo_value(page.history_status_combo, APPOINTMENT_STATUS_MISSED)

        assert [
            item.full_name for item in page._apply_history_filters(appointments)
        ] == ["Missed Person"]
    finally:
        page.close()


def test_calendar_page_smoke_defaults_to_calendar_month(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Smoke Test", days_offset=-1),
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        assert page._count_label.text() == "1 scheduled appointments"
        assert len(page._appointments) == 1
        assert page._calendar_mode == CALENDAR_MODE_MONTH
        assert page.findChild(calendar_page.QWidget, "CalendarModeSegment") is None
        assert page.tab_stack.currentIndex() == page.calendar_index
        assert page._selected_tab == TAB_CALENDAR
    finally:
        page.close()
