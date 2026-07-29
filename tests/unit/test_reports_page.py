from datetime import date

from ui.pages.reports_page import ReportsPage


class MissionaryStub:
    def __init__(self, **kwargs):
        self.full_name = kwargs.pop("full_name", "Test Missionary")
        for key, value in kwargs.items():
            setattr(self, key, value)


class DocumentStub:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_selected_tab_defaults_to_general(qtbot, monkeypatch):
    monkeypatch.setattr(ReportsPage, "load_data", lambda self: None)

    page = ReportsPage(None)
    qtbot.addWidget(page)

    assert page._selected_tab == "general"
    assert page._tab_buttons["general"].isChecked()
    assert not page._tab_buttons["process"].isChecked()
    assert not page._tab_buttons["documents"].isChecked()


def test_average_milestone_timing_uses_only_complete_date_pairs():
    rows = ReportsPage._average_milestone_timing([
        MissionaryStub(
            arrival_date=date(2026, 1, 1),
            interpol_appointment_date=date(2026, 1, 6),
            biometric_appointment_date=date(2026, 1, 16),
            pickup_appointment_date=date(2026, 1, 26),
        ),
        MissionaryStub(
            arrival_date=date(2026, 2, 1),
            interpol_appointment_date=date(2026, 2, 11),
        ),
        MissionaryStub(
            arrival_date=date(2026, 3, 10),
        ),
    ])

    by_label = {row["label"]: row for row in rows}

    assert by_label["Arrival -> Interpol appointment"]["average_days"] == 7.5
    assert by_label["Arrival -> Interpol appointment"]["samples"] == 2
    assert by_label[
        "Interpol appointment -> Biometric appointment"
    ]["average_days"] == 10
    assert by_label[
        "Biometric appointment -> Pickup appointment"
    ]["samples"] == 1


def test_average_milestone_timing_skips_negative_ranges():
    rows = ReportsPage._average_milestone_timing([
        MissionaryStub(
            arrival_date=date(2026, 1, 10),
            interpol_appointment_date=date(2026, 1, 5),
        )
    ])

    assert rows == []


def test_expiration_items_are_sorted_by_urgency_and_include_overdue():
    items = ReportsPage._expiration_items(
        [
            MissionaryStub(
                full_name="Later",
                visa_expiration=date(2026, 7, 20),
            ),
            MissionaryStub(
                full_name="Overdue",
                residency_expiration=date(2026, 7, 1),
            ),
            MissionaryStub(
                full_name="Too Far",
                passport_expiration=date(2026, 9, 1),
            ),
        ],
        date(2026, 7, 5),
    )

    assert [item["name"] for item in items] == ["Overdue", "Later"]
    assert items[0]["days"] == -4
    assert items[1]["days"] == 15


def test_expiration_items_hide_superseded_visa_dates():
    items = ReportsPage._expiration_items(
        [
            MissionaryStub(
                full_name="Prorroga",
                visa_expiration=date(2026, 7, 1),
                prorroga_expiration=date(2026, 7, 20),
            ),
            MissionaryStub(
                full_name="Carnet",
                visa_expiration=date(2026, 7, 1),
                carnet_issue_date=date(2026, 6, 15),
            ),
        ],
        date(2026, 7, 5),
    )

    assert [(item["name"], item["label"]) for item in items] == [
        ("Prorroga", "Prorroga"),
    ]


def test_expiration_items_hide_archived_missionaries():
    items = ReportsPage._expiration_items(
        [
            MissionaryStub(
                full_name="Archived",
                status="ARCHIVED",
                visa_expiration=date(2026, 7, 1),
            ),
            MissionaryStub(
                full_name="Active",
                status="ACTIVE",
                visa_expiration=date(2026, 7, 1),
            ),
        ],
        date(2026, 7, 5),
    )

    assert [item["name"] for item in items] == ["Active"]


def test_general_summary_does_not_include_detailed_attention_rows():
    snapshot = {
        "total": 1,
        "expiring": [
            {
                "name": "Overdue Missionary",
                "label": "Passport",
                "days": -2,
            }
        ],
        "stage_changes": [],
        "arrivals": [],
        "month_label": "July 2026",
    }

    text = " ".join(
        f"{item['title']} {item['meta']} {item['value']}"
        for item in ReportsPage._general_summary(snapshot)
    )

    assert "Overdue Missionary" not in text
    assert "Passport" not in text
    assert "document date(s) need attention soon" in text


def test_document_coverage_handles_empty_document_data():
    rows = ReportsPage._document_coverage(
        [
            MissionaryStub(
                id=1,
                nationality="USA",
            )
        ],
        [],
    )

    assert rows
    assert all(row["uploaded"] == 0 for row in rows)
    assert sum(row["required"] for row in rows) > 0


def test_document_coverage_counts_uploaded_required_documents():
    rows = ReportsPage._document_coverage(
        [
            MissionaryStub(
                id=1,
                nationality="USA",
            )
        ],
        [
            DocumentStub(
                missionary_id=1,
                document_type="PASSPORT",
                status="ACTIVE",
            ),
            DocumentStub(
                missionary_id=1,
                document_type="TAM",
                status="ACTIVE",
            ),
            DocumentStub(
                missionary_id=1,
                document_type="FBI",
                status="ACTIVE",
            ),
            DocumentStub(
                missionary_id=1,
                document_type="PAGO_INTERPOL",
                status="INVALIDATED",
            ),
        ],
    )

    by_label = {row["label"]: row for row in rows}

    assert by_label["General Required"]["uploaded"] == 1
    assert by_label["INTERPOL"]["uploaded"] == 2


def test_timing_text_formats_today_future_and_overdue():
    assert ReportsPage._timing_text(0) == "TODAY"
    assert ReportsPage._timing_text(3) == "3 days"
    assert ReportsPage._timing_text(-5) == "5 days overdue"
