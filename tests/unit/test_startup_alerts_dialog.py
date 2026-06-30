from datetime import date

from PySide6.QtWidgets import QLabel, QPushButton

from ui.dialogs.startup_alerts_dialog import (
    StartupAlertsDialog,
    group_startup_alerts,
    summarize_startup_alerts,
)
from utils.i18n import get_i18n


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


def test_startup_alert_summary_uses_active_language():
    i18n = get_i18n()
    original_language = i18n.get_language()
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

    try:
        i18n.set_language("es")
        summary = summarize_startup_alerts(alerts)
        groups = group_startup_alerts(alerts)

        assert summary["headline"] == (
            "1 crítico(s), 1 vencido(s), 1 vence(n) hoy"
        )
        assert summary["by_type"] == "1 tareas, 1 vencimientos"
        assert [group["title"] for group in groups] == [
            "Tareas",
            "Vencimientos",
        ]
    finally:
        i18n.set_language(original_language)


def test_startup_alert_dialog_chrome_uses_active_language(qapp):
    _ = qapp
    i18n = get_i18n()
    original_language = i18n.get_language()
    alerts = [
        {
            "type": "secretary_task",
            "severity": "critical",
            "days": -3,
            "title": "Overdue task",
            "who": "Elder One",
            "detail": "Needs review",
        }
    ]

    try:
        i18n.set_language("es")
        dialog = StartupAlertsDialog(alerts)
        labels = {
            label.text()
            for label in dialog.findChildren(QLabel)
            if label.text()
        }
        buttons = {
            button.text()
            for button in dialog.findChildren(QPushButton)
            if button.text()
        }

        assert dialog.windowTitle() == "Mission Legal necesita atención"
        assert "Mission Legal necesita atención" in labels
        assert "Empiece aquí" in labels
        assert "El panel muestra toda la cola después de cerrar este diálogo." in labels
        assert "Hecho" in buttons
    finally:
        i18n.set_language(original_language)
        if "dialog" in locals():
            dialog.close()
