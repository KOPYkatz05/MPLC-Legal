from collections import Counter, defaultdict
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.notification_feed_service import notification_sort_key
from ui.foundation import (
    DialogFooter,
    FLUENT_AVAILABLE,
    MaskDialogBase,
    PageHeader,
    create_button,
    create_card,
    create_scroll_area,
    setup_dialog_shell,
)


TYPE_LABELS = {
    "appointment_due": "Appointments",
    "secretary_task": "Tasks",
    "transfer_reminder": "Transfers",
    "document_expiration": "Expirations",
    "missing_document": "Missing Documents",
}

TYPE_ORDER = (
    "appointment_due",
    "secretary_task",
    "transfer_reminder",
    "document_expiration",
    "missing_document",
)

SEVERITY_TONES = {
    "critical": "danger",
    "warning": "warning",
    "info": "caution",
}


def summarize_startup_alerts(alerts):
    alerts = list(alerts or [])
    counts = Counter(item.get("type") for item in alerts)
    critical = sum(1 for item in alerts if item.get("severity") == "critical")
    warning = sum(1 for item in alerts if item.get("severity") == "warning")
    due_today = sum(1 for item in alerts if item.get("days") == 0)
    overdue = sum(1 for item in alerts if (item.get("days") or 0) < 0)

    parts = []
    if critical:
        parts.append(f"{critical} critical")
    if overdue:
        parts.append(f"{overdue} overdue")
    if due_today:
        parts.append(f"{due_today} due today")
    if warning and not critical:
        parts.append(f"{warning} important")

    by_type = []
    for item_type in TYPE_ORDER:
        count = counts.get(item_type, 0)
        if count:
            label = TYPE_LABELS[item_type].lower()
            by_type.append(f"{count} {label}")

    return {
        "total": len(alerts),
        "critical": critical,
        "warning": warning,
        "overdue": overdue,
        "due_today": due_today,
        "headline": ", ".join(parts) if parts else "Review when you can",
        "by_type": ", ".join(by_type),
    }


def group_startup_alerts(alerts):
    groups = defaultdict(list)
    for item in sorted(alerts or [], key=notification_sort_key):
        groups[item.get("type", "secretary_task")].append(item)
    return [
        {
            "type": item_type,
            "title": TYPE_LABELS.get(item_type, "Other"),
            "items": groups[item_type],
        }
        for item_type in TYPE_ORDER
        if groups.get(item_type)
    ]


class StartupAlertsDialog(MaskDialogBase):
    def __init__(self, alerts, parent=None):
        fluent_parent = parent.window() if parent is not None else None
        self._use_fluent_dialog = FLUENT_AVAILABLE and fluent_parent is not None
        if self._use_fluent_dialog:
            super().__init__(fluent_parent)
        else:
            QDialog.__init__(self, parent)

        self.alerts = sorted(list(alerts or []), key=notification_sort_key)
        self.summary = summarize_startup_alerts(self.alerts)

        self.setWindowTitle("Mission Legal needs attention")
        self.surface = setup_dialog_shell(
            self,
            surface_width=820,
            surface_min_height=560,
            use_masked_shell=True,
        )
        self.setup_ui()

    def _onDone(self, code):
        if self._use_fluent_dialog:
            super()._onDone(code)
        else:
            QDialog.done(self, code)

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.surface.setLayout(layout)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_body(), stretch=1)
        layout.addWidget(self._build_footer())

    def _build_header(self):
        count_badge = QLabel(
            f"{self.summary['total']} item"
            f"{'s' if self.summary['total'] != 1 else ''}"
        )
        count_badge.setObjectName("WarningBadge")
        count_badge.setAlignment(Qt.AlignCenter)

        return PageHeader(
            "Mission Legal needs attention",
            "Start with the first item, then scan each section by person, action, and due date.",
            actions=[count_badge],
        )

    def _build_body(self):
        body = QWidget()
        body.setObjectName("DialogBody")
        body.setAttribute(Qt.WA_StyledBackground, True)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(28, 20, 28, 20)
        body_layout.setSpacing(14)
        body.setLayout(body_layout)

        body_layout.addWidget(self._build_summary_card())
        if self.alerts:
            body_layout.addWidget(self._build_start_here_card(self.alerts[0]))

        scroll = create_scroll_area(single_direction=True)
        scroll_content = QWidget()
        scroll_content.setObjectName("DialogBody")
        scroll_content.setAttribute(Qt.WA_StyledBackground, True)

        scroll_layout = QVBoxLayout()
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)
        scroll_content.setLayout(scroll_layout)

        for group in group_startup_alerts(self.alerts):
            scroll_layout.addWidget(self._build_group(group))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        body_layout.addWidget(scroll, stretch=1)

        return body

    def _build_summary_card(self):
        card = create_card()
        card.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)
        card.setLayout(layout)

        accent = QFrame()
        accent.setObjectName("UrgencyBar")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(56)
        accent.setProperty(
            "urgency",
            "danger" if self.summary["critical"] else "warning",
        )

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(4)

        headline = QLabel(self.summary["headline"])
        headline.setObjectName("PanelTitle")
        headline.setWordWrap(True)

        detail = QLabel(self.summary["by_type"] or "No startup alerts.")
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        text_stack.addWidget(headline)
        text_stack.addWidget(detail)

        layout.addWidget(accent)
        layout.addLayout(text_stack, stretch=1)

        return card

    def _build_start_here_card(self, item):
        card = create_card()
        card.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)
        card.setLayout(layout)

        label = QLabel("Start here")
        label.setObjectName("WarningBadge")
        label.setAlignment(Qt.AlignCenter)
        label.setFixedWidth(92)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        title = QLabel(item.get("title") or "Review item")
        title.setObjectName("StrongText")
        title.setWordWrap(True)

        detail = QLabel(self._row_meta(item))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        text_stack.addWidget(title)
        text_stack.addWidget(detail)

        layout.addWidget(label)
        layout.addLayout(text_stack, stretch=1)
        layout.addWidget(self._make_badge(item))

        return card

    def _build_group(self, group):
        section = create_card()
        section.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        section.setLayout(layout)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title = QLabel(group["title"])
        title.setObjectName("PanelTitle")

        count = QLabel(str(len(group["items"])))
        count.setObjectName("AlertBadge")
        count.setProperty("tone", "caution")
        count.setAlignment(Qt.AlignCenter)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(count)
        layout.addLayout(header)

        for item in group["items"][:12]:
            layout.addWidget(self._build_row(item))

        hidden_count = len(group["items"]) - 12
        if hidden_count > 0:
            more = QLabel(f"+ {hidden_count} more in {group['title']}")
            more.setObjectName("MutedText")
            layout.addWidget(more)

        return section

    def _build_row(self, item):
        row = QFrame()
        row.setObjectName("StartupAlertRow")
        row.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        row.setLayout(layout)

        accent = QFrame()
        accent.setObjectName("UrgencyBar")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(40)
        accent.setProperty("urgency", self._urgency(item))

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        who = QLabel(item.get("who") or item.get("missionary_name") or "Office")
        who.setObjectName("StrongText")
        who.setWordWrap(True)
        who.setTextInteractionFlags(Qt.TextSelectableByMouse)

        action = QLabel(self._row_action(item))
        action.setObjectName("MutedText")
        action.setWordWrap(True)
        action.setTextInteractionFlags(Qt.TextSelectableByMouse)

        text_stack.addWidget(who)
        text_stack.addWidget(action)

        layout.addWidget(accent)
        layout.addLayout(text_stack, stretch=1)
        layout.addWidget(self._make_badge(item))

        return row

    def _build_footer(self):
        footer = DialogFooter()

        note = QLabel("Dashboard shows the full queue after this dialog closes.")
        note.setObjectName("SubtleText")
        note.setWordWrap(True)

        dismiss_btn = create_button("Done", "primary")
        dismiss_btn.clicked.connect(self.accept)

        footer.layout().insertWidget(0, note, stretch=1)
        footer.add_action(dismiss_btn)

        return footer

    @staticmethod
    def _row_action(item):
        action = item.get("action") or item.get("title") or "Review item"
        field = item.get("field_label")
        if field and field not in action:
            action = f"{field}: {action}"

        target = item.get("target_date")
        if isinstance(target, date):
            action = f"{action} | {target.strftime('%b %d, %Y')}"

        count = item.get("missionary_count") or 0
        if count > 1:
            action = f"{action} | {count} missionaries"

        return action

    @staticmethod
    def _row_meta(item):
        parts = [item.get("who") or item.get("missionary_name") or "Office"]
        detail = item.get("detail")
        if detail:
            parts.append(detail)
        return " | ".join(parts)

    @staticmethod
    def _make_badge(item):
        badge = QLabel(StartupAlertsDialog._badge_text(item))
        badge.setObjectName("AlertBadge")
        badge.setProperty(
            "tone",
            SEVERITY_TONES.get(item.get("severity"), "caution"),
        )
        badge.setAlignment(Qt.AlignCenter)
        badge.setMinimumWidth(86)
        return badge

    @staticmethod
    def _badge_text(item):
        days = item.get("days")
        if days is None:
            return (item.get("severity") or "Open").title()
        if days < 0:
            return f"{abs(days)}d overdue"
        if days == 0:
            return "Today"
        return f"{days}d left"

    @staticmethod
    def _urgency(item):
        return {
            "critical": "danger",
            "warning": "warning",
            "info": "caution",
        }.get(item.get("severity"), "caution")
