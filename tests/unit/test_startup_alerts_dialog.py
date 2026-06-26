from datetime import date

from ui.dialogs.startup_alerts_dialog import (
    group_startup_alerts,
    summarize_startup_alerts,
)


def test_summarize_startup_alerts_highlights_urgent_counts():
    alerts = [
        {
            "type": "secretary_task",
            "severity": "critical",
            "days": -3,
            "title": "Overdue task",
        },
        {
            "type": "document_expiration",
            "severity": "warning",
            "days": 0,
            "target_date": date(2026, 6, 25),
            "title": "Residency Expiration needs attention",
        },
    ]

    summary = summarize_startup_alerts(alerts)

    assert summary["total"] == 2
    assert summary["critical"] == 1
    assert summary["overdue"] == 1
    assert summary["due_today"] == 1
    assert summary["headline"] == "1 critical, 1 overdue, 1 due today"
    assert summary["by_type"] == "1 tasks, 1 expirations"


def test_group_startup_alerts_orders_by_type_and_urgency():
    alerts = [
        {
            "type": "document_expiration",
            "severity": "warning",
            "days": 6,
            "title": "Residency Expiration needs attention",
            "target_date": date(2026, 7, 1),
        },
        {
            "type": "secretary_task",
            "severity": "warning",
            "days": 0,
            "title": "Due today",
            "target_date": date(2026, 6, 25),
        },
        {
            "type": "secretary_task",
            "severity": "critical",
            "days": -11,
            "title": "Overdue task",
            "target_date": date(2026, 6, 14),
        },
    ]

    groups = group_startup_alerts(alerts)

    assert [group["title"] for group in groups] == ["Tasks", "Expirations"]
    assert [item["title"] for item in groups[0]["items"]] == [
        "Overdue task",
        "Due today",
    ]
