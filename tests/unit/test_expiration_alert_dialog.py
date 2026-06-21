from datetime import date

from PySide6.QtWidgets import QFrame, QLabel

from ui.dialogs.expiration_alert_dialog import ExpirationAlertDialog


def test_expiration_alert_dialog_uses_shared_fluent_shell(qapp):
    dialog = ExpirationAlertDialog(
        [
            {
                "missionary_name": "Ada Lovelace",
                "field_label": "Visa expiration",
                "date": date(2026, 7, 1),
                "days_remaining": 5,
            }
        ]
    )

    try:
        assert dialog.surface.objectName() == "AppDialogSurface"
        assert dialog.findChild(QFrame, "PageHeader") is not None
        assert dialog.findChild(QFrame, "DialogFooter") is not None

        label_texts = {
            label.text()
            for label in dialog.findChildren(QLabel)
        }
        assert "Document Expiration Alerts" in label_texts
        assert "Ada Lovelace" in label_texts
        assert "5d left" in label_texts
    finally:
        dialog.close()
