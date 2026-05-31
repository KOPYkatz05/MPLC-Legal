from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QWidget,
    QSizePolicy,
)

from PySide6.QtCore import Qt


class ExpirationAlertDialog(QDialog):

    def __init__(self, alerts, parent=None):
        super().__init__(parent)

        self.setWindowTitle(
            "Document Expiration Alerts"
        )

        self.setMinimumWidth(620)

        self.setMinimumHeight(420)

        self.alerts = alerts

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.setSpacing(0)

        self.setLayout(layout)

        # ==========================================
        # Header
        # ==========================================

        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(
            24, 18, 24, 18
        )

        header.setLayout(header_layout)

        icon = QLabel("⚠")

        icon.setStyleSheet(
            "font-size: 20px; "
            "color: #D97706; "
            "background: transparent;"
        )

        title = QLabel("Document Expiration Alerts")

        title.setObjectName("PageTitle")

        count_badge = QLabel(
            f"{len(self.alerts)} alerts"
        )

        count_badge.setStyleSheet(
            "background-color: #FEF3C7; "
            "color: #92400E; "
            "font-size: 11px; "
            "font-weight: 600; "
            "padding: 3px 10px; "
            "border-radius: 10px; "
            "border: 1px solid #FCD34D;"
        )

        header_layout.addWidget(icon)

        header_layout.addSpacing(8)

        header_layout.addWidget(title)

        header_layout.addStretch()

        header_layout.addWidget(count_badge)

        layout.addWidget(header)

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        layout.addWidget(divider)

        # ==========================================
        # Scroll area with alert rows
        # ==========================================

        scroll = QScrollArea()

        scroll.setWidgetResizable(True)

        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()

        scroll_content.setObjectName(
            "AlertScrollContent"
        )

        scroll_content.setStyleSheet(
            "#AlertScrollContent { "
            "background-color: #F4F4F5; }"
        )

        scroll_layout = QVBoxLayout()

        scroll_layout.setContentsMargins(
            24, 16, 24, 16
        )

        scroll_layout.setSpacing(8)

        scroll_content.setLayout(scroll_layout)

        if not self.alerts:
            empty = QLabel(
                "No documents expiring within "
                "the next 30 days."
            )

            empty.setObjectName("EmptyLabel")

            empty.setAlignment(Qt.AlignCenter)

            scroll_layout.addWidget(empty)

        else:
            for alert in self.alerts:
                row = self._make_alert_row(alert)

                scroll_layout.addWidget(row)

        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)

        layout.addWidget(scroll, stretch=1)

        # ==========================================
        # Footer
        # ==========================================

        footer_divider = QFrame()

        footer_divider.setObjectName(
            "HeaderDivider"
        )

        footer_divider.setFixedHeight(1)

        layout.addWidget(footer_divider)

        footer = QFrame()

        footer.setObjectName("PageHeader")

        footer_layout = QHBoxLayout()

        footer_layout.setContentsMargins(
            24, 12, 24, 12
        )

        footer.setLayout(footer_layout)

        note = QLabel(
            "These alerts check visa, residency, "
            "and prórroga expirations."
        )

        note.setStyleSheet(
            "color: #A1A1AA; "
            "font-size: 12px; "
            "background: transparent;"
        )

        dismiss_btn = QPushButton("Dismiss")

        dismiss_btn.setObjectName("PrimaryButton")

        dismiss_btn.setFixedHeight(34)

        dismiss_btn.clicked.connect(self.accept)

        footer_layout.addWidget(note)

        footer_layout.addStretch()

        footer_layout.addWidget(dismiss_btn)

        layout.addWidget(footer)

    def _make_alert_row(self, alert):
        days = alert["days_remaining"]

        overdue = alert.get("overdue", False)

        row = QFrame()

        row.setFrameShape(QFrame.NoFrame)

        row.setStyleSheet(
            "QFrame { "
            "background-color: #FFFFFF; "
            "border: 1px solid #E4E4E7; "
            "border-radius: 8px; "
            "}"
        )

        row_layout = QHBoxLayout()

        row_layout.setContentsMargins(
            16, 12, 16, 12
        )

        row_layout.setSpacing(16)

        row.setLayout(row_layout)

        # Urgency indicator bar
        bar = QFrame()

        bar.setFixedWidth(4)

        bar.setMinimumHeight(30)

        if overdue:
            bar_color = "#DC2626"
        elif days <= 7:
            bar_color = "#DC2626"
        elif days <= 15:
            bar_color = "#EA580C"
        elif days <= 30:
            bar_color = "#D97706"
        else:
            bar_color = "#059669"

        bar.setStyleSheet(
            f"background-color: {bar_color}; "
            f"border-radius: 2px;"
        )

        row_layout.addWidget(bar)

        # Missionary name
        name_label = QLabel(
            alert["missionary_name"]
        )

        name_label.setStyleSheet(
            "font-weight: 600; "
            "font-size: 13px; "
            "color: #18181B; "
            "background: transparent;"
        )

        name_label.setMinimumWidth(180)

        row_layout.addWidget(name_label)

        # Document type
        type_label = QLabel(
            alert["field_label"]
        )

        type_label.setStyleSheet(
            "color: #71717A; "
            "font-size: 12px; "
            "background: transparent;"
        )

        type_label.setMinimumWidth(160)

        row_layout.addWidget(type_label)

        # Date
        date_label = QLabel(
            alert["date"].strftime("%d %b %Y")
        )

        date_label.setStyleSheet(
            "color: #3F3F46; "
            "font-size: 12px; "
            "background: transparent;"
        )

        date_label.setMinimumWidth(100)

        row_layout.addWidget(date_label)

        row_layout.addStretch()

        # Days badge
        if overdue:
            badge_text = (
                f"{abs(days)}d overdue"
            )

            badge_bg = "#FEE2E2"

            badge_color = "#991B1B"

            badge_border = "#FECACA"

        elif days <= 7:
            badge_text = f"{days}d left"

            badge_bg = "#FEE2E2"

            badge_color = "#991B1B"

            badge_border = "#FECACA"

        elif days <= 15:
            badge_text = f"{days}d left"

            badge_bg = "#FFF7ED"

            badge_color = "#9A3412"

            badge_border = "#FED7AA"

        else:
            badge_text = f"{days}d left"

            badge_bg = "#FEF3C7"

            badge_color = "#92400E"

            badge_border = "#FCD34D"

        badge = QLabel(badge_text)

        badge.setStyleSheet(
            f"background-color: {badge_bg}; "
            f"color: {badge_color}; "
            f"font-size: 11px; "
            f"font-weight: 600; "
            f"padding: 3px 10px; "
            f"border-radius: 10px; "
            f"border: 1px solid {badge_border};"
        )

        row_layout.addWidget(badge)

        return row
