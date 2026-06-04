from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsBlurEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui.foundation import create_button, create_card, create_scroll_area

try:
    from qfluentwidgets import (
        BodyLabel,
        MaskDialogBase,
        SubtitleLabel,
    )

    FLUENT_DIALOG_AVAILABLE = True
except Exception:
    BodyLabel = QLabel
    SubtitleLabel = QLabel
    MaskDialogBase = QDialog
    FLUENT_DIALOG_AVAILABLE = False


class ExpirationAlertDialog(MaskDialogBase):
    def __init__(self, alerts, parent=None):
        super().__init__(parent)

        self.alerts = alerts

        self._blur_target = self._resolve_blur_target(parent)
        self._blur_effect = None
        self._applied_blur = False

        self.setWindowTitle("Document Expiration Alerts")

        if FLUENT_DIALOG_AVAILABLE:
            self._configure_fluent_shell()
        else:
            self.setModal(True)
            self.setMinimumWidth(760)
            self.setMinimumHeight(520)

        self.setup_ui()

    def _configure_fluent_shell(self):
        self.setMaskColor(QColor(74, 80, 90, 84))
        self.setShadowEffect(
            70,
            (0, 16),
            QColor(15, 23, 42, 90),
        )

        self._hBoxLayout.setContentsMargins(
            24, 24, 24, 24
        )
        self._hBoxLayout.removeWidget(self.widget)
        self._hBoxLayout.addWidget(
            self.widget,
            1,
            Qt.AlignCenter,
        )

        self.widget.setObjectName(
            "ExpirationAlertSurface"
        )
        self.widget.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )
        self.widget.setFixedWidth(760)
        self.widget.setMinimumHeight(520)

    def _resolve_blur_target(self, parent):
        if not parent:
            return None

        window = parent.window()
        if window and window is not parent:
            central_widget_getter = getattr(
                window,
                "centralWidget",
                None,
            )

            if callable(central_widget_getter):
                central_widget = central_widget_getter()
                if central_widget:
                    return central_widget

        central_widget_getter = getattr(
            parent,
            "centralWidget",
            None,
        )

        if callable(central_widget_getter):
            central_widget = central_widget_getter()
            if central_widget:
                return central_widget

        return parent

    def _apply_backdrop_effect(self):
        if not self._blur_target:
            return

        if self._blur_target.graphicsEffect():
            return

        self._blur_effect = QGraphicsBlurEffect(self)
        self._blur_effect.setBlurRadius(10)
        self._blur_target.setGraphicsEffect(self._blur_effect)
        self._applied_blur = True

    def _clear_backdrop_effect(self):
        if not self._applied_blur or not self._blur_target:
            return

        if self._blur_target.graphicsEffect() is self._blur_effect:
            self._blur_target.setGraphicsEffect(None)

        self._blur_effect = None
        self._applied_blur = False

    def showEvent(self, event):
        self._apply_backdrop_effect()
        super().showEvent(event)

    def closeEvent(self, event):
        self._clear_backdrop_effect()
        super().closeEvent(event)

    def _onDone(self, code):
        self._clear_backdrop_effect()

        if FLUENT_DIALOG_AVAILABLE:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def setup_ui(self):
        surface = self.widget if FLUENT_DIALOG_AVAILABLE else self
        surface.setObjectName("ExpirationAlertSurface")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        surface.setLayout(layout)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_body(), stretch=1)
        layout.addWidget(self._build_footer())

    def _build_header(self):
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(
            28, 24, 28, 18
        )
        header_layout.setSpacing(12)
        header.setLayout(header_layout)

        icon = QLabel("⚠")
        icon.setObjectName("WarningIcon")

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(4)

        title = SubtitleLabel("Document Expiration Alerts")
        title.setObjectName("PageTitle")

        subtitle = BodyLabel(
            "Review the most urgent expirations first. "
            "Each row shows the deadline, document type, and days remaining."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)

        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)

        count_badge = QLabel(
            f"{len(self.alerts)} alert"
            f"{'s' if len(self.alerts) != 1 else ''}"
        )
        count_badge.setObjectName("WarningBadge")
        count_badge.setAlignment(Qt.AlignCenter)

        header_layout.addWidget(icon)
        header_layout.addLayout(title_stack)
        header_layout.addStretch()
        header_layout.addWidget(count_badge)

        return header

    def _build_body(self):
        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(
            28, 20, 28, 20
        )
        body_layout.setSpacing(14)
        body.setLayout(body_layout)

        body_layout.addWidget(self._build_summary_card())

        scroll = create_scroll_area()

        scroll_content = QWidget()
        scroll_content.setObjectName("DialogBody")
        scroll_content.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        scroll_layout = QVBoxLayout()
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)
        scroll_content.setLayout(scroll_layout)

        if not self.alerts:
            empty = self._build_empty_state()
            scroll_layout.addWidget(empty)
        else:
            for alert in self.alerts:
                scroll_layout.addWidget(
                    self._make_alert_row(alert)
                )

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        body_layout.addWidget(scroll, stretch=1)

        return body

    def _build_summary_card(self):
        overdue_count = 0
        urgent_count = 0
        soon_count = 0

        for alert in self.alerts:
            days = int(alert["days_remaining"])
            overdue = alert.get("overdue", False) or days < 0

            if overdue:
                overdue_count += 1
            elif days <= 7:
                urgent_count += 1
            elif days <= 15:
                soon_count += 1

        card = create_card()
        card.setAttribute(Qt.WA_StyledBackground, True)

        card_layout = QHBoxLayout()
        card_layout.setContentsMargins(
            18, 16, 18, 16
        )
        card_layout.setSpacing(16)
        card.setLayout(card_layout)

        accent = QFrame()
        accent.setObjectName("UrgencyBar")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(52)
        if overdue_count:
            summary_tone = "danger"
        elif urgent_count:
            summary_tone = "warning"
        elif soon_count:
            summary_tone = "caution"
        else:
            summary_tone = "success"
        accent.setProperty("urgency", summary_tone)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        headline = QLabel(
            f"{len(self.alerts)} document"
            f"{'s' if len(self.alerts) != 1 else ''} need attention"
        )
        headline.setObjectName("StrongText")
        headline.setWordWrap(True)

        detail_parts = []
        if overdue_count:
            detail_parts.append(
                f"{overdue_count} overdue"
            )
        if urgent_count:
            detail_parts.append(
                f"{urgent_count} due within 7 days"
            )
        if soon_count:
            detail_parts.append(
                f"{soon_count} due within 15 days"
            )

        if detail_parts:
            detail_text = ", ".join(detail_parts)
        else:
            detail_text = (
                "No active expirations in the urgent window."
            )

        detail = QLabel(detail_text)
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        text_stack.addWidget(headline)
        text_stack.addWidget(detail)

        card_layout.addWidget(accent)
        card_layout.addLayout(text_stack)
        card_layout.addStretch()

        return card

    def _build_empty_state(self):
        empty_card = create_card()
        empty_card.setAttribute(
            Qt.WA_StyledBackground,
            True,
        )

        empty_layout = QVBoxLayout()
        empty_layout.setContentsMargins(
            22, 20, 22, 20
        )
        empty_layout.setSpacing(6)
        empty_card.setLayout(empty_layout)

        empty_title = QLabel("Nothing is expiring soon.")
        empty_title.setObjectName("StrongText")

        empty_note = QLabel(
            "No documents are scheduled to expire within the next 30 days."
        )
        empty_note.setObjectName("MutedText")
        empty_note.setWordWrap(True)

        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_note)

        return empty_card

    def _build_footer(self):
        footer = QFrame()
        footer.setObjectName("PageHeader")
        footer.setAttribute(Qt.WA_StyledBackground, True)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(
            28, 12, 28, 16
        )
        footer_layout.setSpacing(12)
        footer.setLayout(footer_layout)

        note = QLabel(
            "These alerts cover visa, residency, and prórroga expirations."
        )
        note.setObjectName("SubtleText")
        note.setWordWrap(True)

        dismiss_btn = create_button("Dismiss", "primary")
        dismiss_btn.clicked.connect(self.accept)

        footer_layout.addWidget(note)
        footer_layout.addStretch()
        footer_layout.addWidget(dismiss_btn)

        return footer

    def _make_alert_row(self, alert):
        days = int(alert["days_remaining"])
        overdue = alert.get("overdue", False) or days < 0

        row = create_card()
        row.setAttribute(Qt.WA_StyledBackground, True)

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(
            16, 12, 16, 12
        )
        row_layout.setSpacing(14)
        row.setLayout(row_layout)

        bar = QFrame()
        bar.setObjectName("UrgencyBar")
        bar.setFixedWidth(4)
        bar.setMinimumHeight(42)

        if overdue or days <= 7:
            bar.setProperty("urgency", "danger")
        elif days <= 15:
            bar.setProperty("urgency", "warning")
        elif days <= 30:
            bar.setProperty("urgency", "caution")
        else:
            bar.setProperty("urgency", "success")

        row_layout.addWidget(bar)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        name_label = QLabel(alert["missionary_name"])
        name_label.setObjectName("StrongText")
        name_label.setMinimumWidth(180)
        name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        type_label = QLabel(alert["field_label"])
        type_label.setObjectName("MutedText")
        type_label.setMinimumWidth(160)
        type_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        date_label = QLabel(alert["date"].strftime("%d %b %Y"))
        date_label.setObjectName("MutedText")
        date_label.setMinimumWidth(100)
        date_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        top_row.addWidget(name_label)
        top_row.addSpacing(8)
        top_row.addWidget(type_label)
        top_row.addStretch()
        top_row.addWidget(date_label)

        text_stack.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)

        if overdue:
            badge_text = f"{abs(days)}d overdue"
            badge_tone = "danger"
        elif days <= 7:
            badge_text = f"{days}d left"
            badge_tone = "danger"
        elif days <= 15:
            badge_text = f"{days}d left"
            badge_tone = "warning"
        else:
            badge_text = f"{days}d left"
            badge_tone = "caution"

        badge = QLabel(badge_text)
        badge.setObjectName("AlertBadge")
        badge.setProperty("tone", badge_tone)
        badge.setAlignment(Qt.AlignCenter)

        bottom_row.addWidget(badge)
        bottom_row.addStretch()

        text_stack.addLayout(bottom_row)

        row_layout.addLayout(text_stack)

        return row
