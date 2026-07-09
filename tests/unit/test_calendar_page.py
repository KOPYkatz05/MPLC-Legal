from datetime import date, timedelta
from types import SimpleNamespace

from PySide6.QtWidgets import QToolButton

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
from utils.i18n import get_i18n


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
        summary_card = page.findChild(calendar_page.QFrame, "CalendarSummaryCard")
        assert summary_card is not None
        assert summary_card.maximumHeight() == 62
        assert page.calendar_layout.spacing() == 6
        assert page.calendar_layout.contentsMargins().top() == 6
        assert page.tab_buttons[TAB_CALENDAR].property("active") is True
        assert not hasattr(page.tab_buttons[TAB_CALENDAR], "_calendar_indicator")
    finally:
        page.close()


def test_calendar_history_renders_lazily(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Lazy History", days_offset=1),
    ]
    render_calls = []

    def record_history(self):
        render_calls.append(self._selected_tab)

    monkeypatch.setattr(calendar_page.CalendarPage, "_render_history", record_history)
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        assert render_calls == []
        assert page._history_loaded is False

        page._select_tab(TAB_HISTORY)

        assert render_calls == [TAB_HISTORY]
    finally:
        page.close()


def test_calendar_search_change_schedules_render(monkeypatch, qapp):
    page = _build_page(monkeypatch, qapp, [_appointment()])
    scheduled = []
    monkeypatch.setattr(
        page,
        "_schedule_calendar_render",
        lambda: scheduled.append("calendar"),
    )

    try:
        page._calendar_search_changed("foo")

        assert scheduled == ["calendar"]
    finally:
        page.close()


def test_history_search_change_schedules_render(monkeypatch, qapp):
    page = _build_page(monkeypatch, qapp, [_appointment()])
    scheduled = []
    monkeypatch.setattr(
        page,
        "_schedule_history_render",
        lambda: scheduled.append("history"),
    )

    try:
        page.history_search_edit.setText("foo")

        assert scheduled == ["history"]
    finally:
        page.close()


def test_history_filters_are_cached(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Cache One", days_offset=-2),
        _appointment(full_name="Cache Two", days_offset=3),
    ]
    page = _build_page(monkeypatch, qapp, appointments)
    calls = []

    def record_compute(self, appointments, *, query, type_filter, status_filter):
        calls.append((query, type_filter, status_filter, len(appointments)))
        return list(appointments)

    monkeypatch.setattr(
        calendar_page.CalendarPage,
        "_compute_history_filters",
        record_compute,
    )

    try:
        page._select_tab(TAB_HISTORY)
        page._apply_history_filters(page._history_appointments)
        page._apply_history_filters(page._history_appointments)

        assert len(calls) == 2
        assert calls[0] == calls[1]
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

        task_pill = page.findChild(
            calendar_page.QFrame,
            "CalendarTaskChip",
        )
        assert task_pill is not None
        assert task_pill.property("done") is False
        task_label = task_pill.findChild(calendar_page.QLabel, "PillActionLabel")
        assert task_label is not None
        assert task_label.text() == "Prepare cita packet"
        assert task_pill.findChild(QToolButton, "PillActionIconButton") is not None
    finally:
        page.close()


def test_calendar_task_chip_uses_active_language(monkeypatch, qapp):
    i18n = get_i18n()
    original_language = i18n.get_language()
    i18n.set_language("es")
    task = _task(
        due_date=date(2026, 6, 20),
        work_date=date(2026, 6, 10),
    )
    page = _build_page(monkeypatch, qapp, [], tasks=[task])

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        task_pill = page.findChild(
            calendar_page.QFrame,
            "CalendarTaskChip",
        )

        assert task_pill is not None
        task_label = task_pill.findChild(calendar_page.QLabel, "PillActionLabel")
        assert task_label is not None
        assert task_label.text() == "Prepare cita packet"
        assert task_pill.toolTip().startswith("Tarea: ")
        assert task_pill.findChild(QToolButton, "PillActionIconButton") is not None
    finally:
        page.close()
        i18n.set_language(original_language)


def test_calendar_task_row_keeps_title_only_summary(monkeypatch, qapp):
    task = _task(
        due_date=date(2026, 6, 20),
        work_date=date(2026, 6, 10),
    )
    page = _build_page(monkeypatch, qapp, [], tasks=[task])

    try:
        row = page._make_task_row(task)

        assert (
            row.findChild(calendar_page.QLabel, "PillActionLabel").text()
            == "Prepare cita packet"
        )
        assert row.minimumHeight() == 50
        assert row.maximumHeight() == 50
        assert row.sizePolicy().horizontalPolicy() == (
            calendar_page.QSizePolicy.Expanding
        )
        subtitle = row.findChild(calendar_page.QLabel, "PillActionSubtitle")
        assert subtitle is not None
        assert "Due" in subtitle.text()
        assert subtitle.sizePolicy().horizontalPolicy() == (
            calendar_page.QSizePolicy.Ignored
        )
        assert row.findChild(QToolButton, "PillActionIconButton") is not None
    finally:
        page.close()


def test_calendar_appointment_chip_uses_shared_pill_factory(monkeypatch, qapp):
    appointment = _appointment(full_name="Alex", appointment_type="Interpol", days_offset=2)
    page = _build_page(monkeypatch, qapp, [appointment])

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        appointment_pill = page.findChild(
            calendar_page.QFrame,
            "CalendarAppointmentChip",
        )
        assert appointment_pill is not None
        label = appointment_pill.findChild(calendar_page.QLabel, "PillActionLabel")
        assert label is not None
        assert label.text().startswith("Interpol - Alex")
    finally:
        page.close()


def test_calendar_month_chips_use_compact_pill_geometry(monkeypatch, qapp):
    appointment = _appointment(full_name="Alex", appointment_type="Interpol", days_offset=2)
    task = _task(work_date=date(2026, 6, 10))
    page = _build_page(monkeypatch, qapp, [appointment], tasks=[task])

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        appointment_pill = page.findChild(
            calendar_page.QFrame,
            "CalendarAppointmentChip",
        )
        task_pill = page.findChild(
            calendar_page.QFrame,
            "CalendarTaskChip",
        )

        assert appointment_pill is not None
        assert task_pill is not None
        assert appointment_pill.height() == 30
        assert task_pill.height() == 30
        assert appointment_pill.sizePolicy().horizontalPolicy() == (
            calendar_page.QSizePolicy.Maximum
        )
        assert task_pill.sizePolicy().horizontalPolicy() == (
            calendar_page.QSizePolicy.Maximum
        )
    finally:
        page.close()


def test_calendar_month_cell_limits_visible_pills_when_crowded(monkeypatch, qapp):
    appointments = [
        _appointment(full_name=f"Alex {index}", days_offset=2)
        for index in range(4)
    ]
    page = _build_page(monkeypatch, qapp, appointments)

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        visible_pills = page.findChildren(
            calendar_page.QFrame,
            "CalendarAppointmentChip",
        )
        overflow = page.findChild(calendar_page.QPushButton, "CalendarOverflowButton")

        assert len(visible_pills) == 2
        assert overflow is not None
        assert overflow.text() == "+2 more"
    finally:
        page.close()


def test_calendar_day_summary_dialog_tracks_anchor_geometry(monkeypatch, qapp):
    page = _build_page(monkeypatch, qapp, [])
    anchor = calendar_page.QFrame()
    anchor.setGeometry(50, 80, 140, 52)
    anchor.show()
    qapp.processEvents()

    try:
        dialog = calendar_page.CalendarDaySummaryDialog(
            page,
            date(2026, 6, 12),
            [],
            [],
            anchor_widget=anchor,
        )
        try:
            assert isinstance(dialog, calendar_page.QMenu)
            assert dialog.objectName() == "CalendarDaySummaryMenu"
            panel = dialog.actions()[0].defaultWidget()
            assert panel.objectName() == "CalendarDaySummaryPanel"
            assert panel.width() == 500
            scroll = panel.findChild(
                calendar_page.QWidget,
                "CalendarDaySummaryScroll",
            )
            assert scroll is not None
            assert scroll.maximumHeight() == 300
            assert (
                panel.findChild(calendar_page.QPushButton, "CalendarDayCloseButton")
                is not None
            )
            assert (
                panel.findChild(calendar_page.QPushButton, "CalendarDayAddTaskButton")
                is not None
            )
            geometry = dialog._anchor_geometry()
            assert geometry is not None
            assert geometry.width() == 140
            assert geometry.height() == 52
        finally:
            dialog.close()
    finally:
        page.close()


def test_calendar_day_details_use_render_cache(monkeypatch, qapp):
    appointments = [
        _appointment(full_name="Cache Match", days_offset=1),
        _appointment(full_name="Other Day", days_offset=4),
    ]
    task = _task(work_date=date(2026, 6, 10))
    page = _build_page(monkeypatch, qapp, appointments, tasks=[task])

    captured = {}

    class FakeDialog:
        def __init__(self, calendar_page, summary_date, appts, tasks, anchor_widget=None):
            captured["summary_date"] = summary_date
            captured["appointments"] = list(appts)
            captured["tasks"] = list(tasks)
            captured["anchor_widget"] = anchor_widget

        def exec(self):
            return 0

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        monkeypatch.setattr(
            page,
            "_appointments_by_date",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("appointment grouping recomputed")
            ),
        )
        monkeypatch.setattr(
            page,
            "_apply_calendar_filters",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("calendar filter recomputed")
            ),
        )
        monkeypatch.setattr(
            page,
            "_tasks_by_date",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("task grouping recomputed")
            ),
        )
        monkeypatch.setattr(calendar_page, "CalendarDaySummaryDialog", FakeDialog)

        page._show_calendar_day_details(date(2026, 6, 10))

        assert [item.full_name for item in captured["appointments"]] == [
            "Cache Match",
        ]
        assert [item["title"] for item in captured["tasks"]] == [
            "Prepare cita packet"
        ]
        assert captured["summary_date"] == date(2026, 6, 10)
    finally:
        page.close()


def test_calendar_day_details_opens_menu_non_blocking(monkeypatch, qapp):
    appointments = [_appointment(full_name="Menu Person", days_offset=1)]
    task = _task(work_date=date(2026, 6, 10))
    page = _build_page(monkeypatch, qapp, appointments, tasks=[task])

    try:
        page._anchor_date = date(2026, 6, 9)
        page._render_calendar()

        page._show_calendar_day_details(date(2026, 6, 10))
        qapp.processEvents()

        assert isinstance(page._day_summary_menu, calendar_page.QMenu)
        assert page._day_summary_menu.objectName() == "CalendarDaySummaryMenu"

        page._day_summary_menu.hide()
        qapp.processEvents()
        assert page._day_summary_menu is None
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
        assert chip is not None
        done_button = chip.findChild(QToolButton, "PillActionIconButton")
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


def test_calendar_chrome_uses_active_language(monkeypatch, qapp):
    i18n = get_i18n()
    original_language = i18n.get_language()
    i18n.set_language("es")

    page = _build_page(monkeypatch, qapp, [_appointment()])

    try:
        labels = {
            label.text()
            for label in page.findChildren(calendar_page.QLabel)
            if label.text()
        }
        buttons = {
            button.text()
            for button in page.findChildren(calendar_page.QPushButton)
            if button.text()
        }

        assert "Calendario de citas" in labels
        assert "1 citas programadas" in labels
        assert "Calendario" in buttons
        assert "Historial" in buttons
        assert "Hoy" in buttons
        assert "Agregar tarea" in buttons
        assert (
            page.calendar_search_edit.placeholderText()
            == "Buscar calendario"
        )
        assert (
            page.history_search_edit.placeholderText()
            == "Buscar misionero"
        )
        assert page.calendar_type_combo.itemText(0) == "Todos los tipos"
        assert page.calendar_type_combo.itemData(0) == "All Types"
    finally:
        page.close()
        i18n.set_language(original_language)


def test_day_summary_dialog_uses_active_language(monkeypatch, qapp):
    i18n = get_i18n()
    original_language = i18n.get_language()
    i18n.set_language("es")

    page = _build_page(monkeypatch, qapp, [])

    try:
        dialog = calendar_page.CalendarDaySummaryDialog(
            page,
            date(2026, 6, 12),
            [],
            [],
        )
        try:
            labels = {
                label.text()
                for label in dialog.findChildren(calendar_page.QLabel)
                if label.text()
            }
            buttons = {
                button.text()
                for button in dialog.findChildren(calendar_page.QPushButton)
                if button.text()
            }

            assert "Citas y tareas planificadas para este dia." in labels
            assert "Citas" in labels
            assert "No hay citas" in labels
            assert "No hay tareas planificadas." in labels
            assert "Cerrar" in buttons
            assert "Agregar tarea" in buttons
        finally:
            dialog.close()
    finally:
        page.close()
        i18n.set_language(original_language)


def test_calendar_history_empty_state_uses_active_language(monkeypatch, qapp):
    i18n = get_i18n()
    original_language = i18n.get_language()
    i18n.set_language("es")

    page = _build_page(monkeypatch, qapp, [])

    try:
        page._select_tab(TAB_HISTORY)

        labels = {
            label.text()
            for label in page.findChildren(calendar_page.QLabel)
            if label.text()
        }

        assert "Todavia no hay historial de citas." in labels
        assert "Ajuste los filtros o agregue fechas de citas." in labels
    finally:
        page.close()
        i18n.set_language(original_language)


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
        chip.clicked.emit()

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
        label = row.findChild(calendar_page.QLabel, "PillActionLabel")
        assert row.minimumHeight() == 50
        assert row.maximumHeight() == 50
        assert row.sizePolicy().horizontalPolicy() == (
            calendar_page.QSizePolicy.Expanding
        )
        assert label is not None
        assert label.sizePolicy().horizontalPolicy() == (
            calendar_page.QSizePolicy.Ignored
        )
        row.clicked.emit()

        assert opened == [appointment.missionary_id]
    finally:
        page.close()


def test_appointment_row_subtitle_includes_cita_type(monkeypatch, qapp):
    appointment = _appointment(
        appointment_type="Biometric",
        days_offset=-2,
    )
    page = _build_page(monkeypatch, qapp, [appointment])

    try:
        row = page._make_appointment_row(appointment)
        subtitle = row.findChild(calendar_page.QLabel, "PillActionSubtitle")

        assert subtitle is not None
        assert "Biometric cita" in subtitle.text()
        assert "Stage:" not in subtitle.text()
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


def test_calendar_toolbar_no_longer_shows_overdue_strip(monkeypatch, qapp):
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
        assert overdue_strip is None
        assert toolbar.parentWidget() is grid.parentWidget()

        parent_layout = toolbar.parentWidget().layout()
        assert parent_layout.indexOf(toolbar) < parent_layout.indexOf(grid)
    finally:
        page.close()


def test_overdue_action_opens_history_overdue_column(monkeypatch, qapp):
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

        assert page._selected_tab == TAB_HISTORY
        assert page.tab_stack.currentIndex() == page.history_index
        assert page.history_status_combo.currentData() == "overdue"
        board = page.findChild(calendar_page.QWidget, "CalendarHistoryBoard")
        assert board is not None
        row = page.findChild(calendar_page.QWidget, "CalendarAppointmentRow")
        buttons = [button.toolTip() for button in row.findChildren(QToolButton)]
        assert "Complete" in buttons
        assert "Missed" in buttons
    finally:
        page.close()


def test_history_uses_two_columns_for_single_missionary_search(monkeypatch, qapp):
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

        board = page.history_layout.itemAt(0).widget()
        overdue_column = board.findChildren(
            calendar_page.QWidget,
            "CalendarHistoryColumn",
        )
        rows = board.findChildren(calendar_page.QWidget, "CalendarAppointmentRow")
        assert board is not None
        assert board.objectName() == "CalendarHistoryBoard"
        assert len(overdue_column) == 2
        assert [row.findChild(calendar_page.QLabel, "PillActionLabel").text() for row in rows] == [
            "Addelyn Sylvia Holt",
        ]
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

        tooltips = [
            button.toolTip()
            for button in page.findChildren(QToolButton)
        ]
        assert "Complete" not in tooltips
        assert "Missed" not in tooltips
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
        summary_card = page.findChild(calendar_page.QFrame, "CalendarSummaryCard")
        assert summary_card is not None
        assert summary_card.maximumHeight() == 62
        assert page.calendar_layout.spacing() == 6
        assert page.calendar_layout.contentsMargins().top() == 6
        assert page.tab_buttons[TAB_CALENDAR].property("active") is True
        assert not hasattr(page.tab_buttons[TAB_CALENDAR], "_calendar_indicator")
    finally:
        page.close()
