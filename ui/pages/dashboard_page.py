from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
)

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette

from services.dashboard_service import (
    DashboardService,
)
from services.appointment_service import AppointmentService
from ui.foundation import (
    PageHeader,
    SectionTitle as SectionHeader,
    StatCard,
    create_button,
    create_scroll_area,
    divider,
    show_message,
)
from ui.foundation.fluent import SimpleCardWidget

from utils.constants import WORKFLOW_STAGES

from utils.logger import logger


# ==========================================
# COLOR PALETTE
# ==========================================

STAGE_COLORS = {
    "INTERPOL": "#7C3AED",
    "CARNET DE EXTRANJERIA": "#D97706",
    "PRORROGA": "#059669",
    "CANCELACION": "#DC2626",
}

STAGE_LABELS = {
    "INTERPOL": "Interpol",
    "CARNET DE EXTRANJERIA": "Carnet de\nExtranjería",
    "PRORROGA": "Prórroga",
    "CANCELACION": "Cancelación",
}


# ==========================================
# COLUMN HEADER ROW
# ==========================================

class ColumnHeaderRow(QFrame):
    def __init__(self, columns, parent=None):
        super().__init__(parent)

        self.setObjectName("ColumnHeaderRow")

        layout = QHBoxLayout()

        layout.setContentsMargins(20, 8, 20, 8)

        layout.setSpacing(16)

        self.setLayout(layout)

        for text, stretch in columns:
            lbl = QLabel(text.upper())

            lbl.setObjectName("ColHeaderLabel")

            layout.addWidget(lbl, stretch=stretch)


# ==========================================
# TABLE ROW
# ==========================================

class TableRow(QFrame):
    clicked = Signal(object)

    def __init__(self, alternate=False, parent=None):
        super().__init__(parent)
        self.item_data = None

        self.setObjectName(
            "TableRowAlt" if alternate else "TableRow"
        )

        self.layout_ = QHBoxLayout()

        self.layout_.setContentsMargins(20, 12, 20, 12)

        self.layout_.setSpacing(16)

        self.setLayout(self.layout_)

    def set_click_data(self, item_data):
        self.item_data = item_data
        self.setCursor(Qt.PointingHandCursor)

    def add_button(self, text, callback, variant="subtle"):
        button = create_button(text, variant, fixed_height=28)
        button.clicked.connect(callback)
        self.layout_.addWidget(button)
        return button

    def mousePressEvent(self, event):
        if self.item_data is not None and event.button() == Qt.LeftButton:
            self.clicked.emit(self.item_data)
            event.accept()
            return

        super().mousePressEvent(event)

    def add_cell(
        self,
        text,
        stretch=1,
        bold=False,
        color=None,
        align=Qt.AlignVCenter,
        word_wrap=False,
    ):
        lbl = QLabel(text)

        lbl.setObjectName("RowText")

        lbl.setAlignment(align)

        lbl.setWordWrap(word_wrap)

        if bold:
            font = QFont(lbl.font())
            font.setWeight(QFont.DemiBold)
            lbl.setFont(font)

        if color:
            palette = lbl.palette()
            palette.setColor(QPalette.WindowText, QColor(color))
            lbl.setPalette(palette)

        self.layout_.addWidget(lbl, stretch=stretch)


# ==========================================
# LIST CARD (container for table rows)
# ==========================================

class ListCard(SimpleCardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("ListCard")

        self._layout = QVBoxLayout()

        self._layout.setContentsMargins(0, 0, 0, 0)

        self._layout.setSpacing(0)

        self.setLayout(self._layout)

    def add_widget(self, widget):
        self._layout.addWidget(widget)

    def add_empty(self, text):
        lbl = QLabel(f"  {text}")

        lbl.setObjectName("EmptyLabel")

        self._layout.addWidget(lbl)


# ==========================================
# DASHBOARD PAGE
# ==========================================

class DashboardPage(QWidget):
    startup_alerts_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.main_window = parent
        self.service = DashboardService()
        self.startup_alerts = []

        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        # ======================================
        # Top header bar
        # ======================================

        header_bar = QFrame()

        header_bar.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(32, 20, 32, 20)

        header_bar.setLayout(header_layout)

        title = QLabel("Dashboard")

        title.setObjectName("PageTitle")

        self.refresh_btn = create_button(
            "Refresh",
            "secondary",
        )

        self.refresh_btn.setObjectName("RefreshButton")

        self.refresh_btn.clicked.connect(
            self.load_data
        )

        header_layout.addWidget(title)

        header_layout.addStretch()

        header_layout.addWidget(self.refresh_btn)

        outer.addWidget(header_bar)

        # ======================================
        # Divider
        # ======================================

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        outer.addWidget(divider)

        # ======================================
        # Scrollable content area
        # ======================================

        scroll = create_scroll_area(single_direction=True)

        scroll.setObjectName("DashboardScroll")

        self.content_widget = QWidget()

        self.content_widget.setObjectName(
            "DashboardContent"
        )

        self.content_layout = QVBoxLayout()

        self.content_layout.setContentsMargins(
            32, 24, 32, 32
        )

        self.content_layout.setSpacing(20)

        self.content_widget.setLayout(
            self.content_layout
        )

        scroll.setWidget(self.content_widget)

        outer.addWidget(scroll, stretch=1)

        self.load_data()

    def load_data(self):
        # Clear existing content
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

        data = self.service.get_summary()

        self._build_startup_alert_banner()

        self._build_attention_section(
            data.get("attention_items", [])
        )

        self._build_stat_cards(data)

        self._build_expiring_section(
            data["expiring"]
        )

        self._build_missing_section(
            data["missing_docs"]
        )

        self.content_layout.addStretch()

        logger.info("Dashboard data loaded")

    def set_startup_alerts(self, alerts):
        self.startup_alerts = list(alerts or [])
        self.load_data()

    def _build_startup_alert_banner(self):
        if not self.startup_alerts:
            return

        overdue_count = sum(
            1
            for alert in self.startup_alerts
            if alert.get("overdue") or int(alert.get("days_remaining", 0)) < 0
        )
        urgent_count = sum(
            1
            for alert in self.startup_alerts
            if not alert.get("overdue")
            and 0 <= int(alert.get("days_remaining", 0)) <= 7
        )
        parts = []
        if overdue_count:
            parts.append(f"{overdue_count} overdue")
        if urgent_count:
            parts.append(f"{urgent_count} due within 7 days")
        if not parts:
            parts.append("due within 30 days")

        banner = QFrame()
        banner.setObjectName("DashboardAlertBanner")
        banner.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)
        banner.setLayout(layout)

        accent = QFrame()
        accent.setObjectName("DashboardAlertAccent")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(48)
        if overdue_count or urgent_count:
            accent.setProperty("tone", "danger")
        else:
            accent.setProperty("tone", "warning")

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(2)

        title = QLabel(
            f"{len(self.startup_alerts)} document"
            f"{'s' if len(self.startup_alerts) != 1 else ''} need attention"
        )
        title.setObjectName("StrongText")

        detail = QLabel(", ".join(parts))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        text_stack.addWidget(title)
        text_stack.addWidget(detail)

        button = create_button("Review alerts", "primary")
        button.clicked.connect(self.startup_alerts_requested.emit)

        layout.addWidget(accent)
        layout.addLayout(text_stack, stretch=1)
        layout.addWidget(button)

        self.content_layout.addWidget(banner)

    def _build_attention_section(self, attention_items):
        self.content_layout.addWidget(
            SectionHeader("Needs Attention")
        )

        card = ListCard()
        card.setObjectName("NeedsAttentionCard")

        if not attention_items:
            card.add_empty("No urgent items need attention.")
            self.content_layout.addWidget(card)
            return

        for i, item in enumerate(attention_items[:12]):
            row = TableRow(alternate=(i % 2 == 1))
            row.setObjectName("NeedsAttentionRow")
            row.set_click_data(item)
            row.clicked.connect(self._open_attention_item)
            row.setProperty("severity", item.get("severity", "info"))

            row.add_cell(
                item.get("title", "Needs attention"),
                stretch=3,
                bold=True,
            )
            row.add_cell(
                item.get("detail", ""),
                stretch=5,
                word_wrap=True,
                color="#52525B",
            )
            row.add_cell(
                self._attention_type_label(item.get("type")),
                stretch=2,
                color=self._attention_color(item.get("severity")),
            )
            if item.get("type") == "appointment_due":
                row.add_button(
                    "Complete",
                    lambda checked=False, payload=item:
                    self._complete_attention_appointment(payload),
                    variant="success",
                )
                row.add_button(
                    "Missed",
                    lambda checked=False, payload=item:
                    self._miss_attention_appointment(payload),
                    variant="danger",
                )
            row.add_button(
                self._attention_action_label(item),
                lambda checked=False, payload=item:
                self._open_attention_item(payload),
                variant="secondary",
            )
            card.add_widget(row)

        self.content_layout.addWidget(card)

    @staticmethod
    def _attention_type_label(item_type):
        labels = {
            "document_expiration": "Document",
            "missing_document": "Missing Doc",
            "appointment_due": "Appointment",
            "secretary_task": "Task",
        }
        return labels.get(item_type, "Item")

    @staticmethod
    def _attention_color(severity):
        return {
            "critical": "#DC2626",
            "warning": "#D97706",
            "info": "#2563EB",
        }.get(severity, "#71717A")

    @staticmethod
    def _attention_action_label(item):
        target = item.get("target")
        if target == "office_work":
            return "Office Work"
        if target == "appointments":
            return "Appointments"
        return "Open"

    def _open_attention_item(self, item):
        if not item:
            return

        missionary_id = item.get("missionary_id")
        if missionary_id and self.main_window is not None:
            opener = getattr(
                self.main_window,
                "open_missionary_detail",
                None,
            )
            if callable(opener):
                opener(missionary_id)
                return

        target = item.get("target")
        if target == "office_work" and self.main_window is not None:
            self.main_window.set_current_key("office_work")
        elif target == "appointments" and self.main_window is not None:
            self.main_window.go_to_calendar()

    def _complete_attention_appointment(self, item):
        appointment_id = item.get("appointment_id")
        if not appointment_id:
            return

        try:
            AppointmentService().complete_appointment(appointment_id)
            self._refresh_after_appointment_action()
        except Exception:
            logger.exception("Failed to complete appointment from dashboard")
            show_message(
                self,
                "Appointment Error",
                "Could not mark the appointment complete.",
                kind="critical",
            )

    def _miss_attention_appointment(self, item):
        appointment_id = item.get("appointment_id")
        if not appointment_id:
            return

        confirm = show_message(
            self,
            "Mark Appointment Missed?",
            (
                "This will mark the appointment as missed, remove it from "
                "Needs Attention, and create the follow-up task."
            ),
            kind="question",
            buttons="yes_no",
        )
        if confirm not in {1, 16384}:
            return

        try:
            AppointmentService().miss_appointment(appointment_id)
            self._refresh_after_appointment_action()
        except Exception:
            logger.exception("Failed to mark appointment missed from dashboard")
            show_message(
                self,
                "Appointment Error",
                "Could not mark the appointment missed.",
                kind="critical",
            )

    def _refresh_after_appointment_action(self):
        self.load_data()

        if self.main_window is None:
            return

        for attr in ("calendar_page", "office_work_page"):
            page = getattr(self.main_window, attr, None)
            if page is not None and hasattr(page, "load_data"):
                page.load_data()

    # ==========================================
    # STAT CARDS
    # ==========================================

    def _build_stat_cards(self, data):
        self.content_layout.addWidget(
            SectionHeader("Overview")
        )

        row = QHBoxLayout()

        row.setSpacing(16)

        # Total card
        total_card = StatCard(
            data["total"],
            "Active Missionaries",
            color="#3B82F6",
        )

        row.addWidget(total_card)

        # Per-stage cards
        for stage in WORKFLOW_STAGES:
            count = data["stage_counts"].get(stage, 0)

            card = StatCard(
                count,
                STAGE_LABELS.get(stage, stage),
                color=STAGE_COLORS.get(
                    stage,
                    "#6B7280",
                ),
            )

            row.addWidget(card)

        wrapper = QWidget()

        wrapper.setLayout(row)

        self.content_layout.addWidget(wrapper)

    # ==========================================
    # EXPIRING DOCUMENTS
    # ==========================================

    def _build_expiring_section(self, expiring):
        self.content_layout.addWidget(
            SectionHeader("Expiring Within 60 Days")
        )

        card = ListCard()

        card.add_widget(
            ColumnHeaderRow([
                ("Missionary", 3),
                ("Document", 3),
                ("Expiry Date", 2),
                ("Days Remaining", 2),
                ("", 1),
            ])
        )

        if not expiring:
            card.add_empty(
                "No documents expiring within 60 days."
            )

        else:
            for i, item in enumerate(expiring):
                days = item["days_left"]

                if days < 0:
                    day_color = "#DC2626"
                    urgency = "Expired"

                elif days <= 14:
                    day_color = "#DC2626"
                    urgency = f"{days} days"

                elif days <= 30:
                    day_color = "#D97706"
                    urgency = f"{days} days"

                else:
                    day_color = "#059669"
                    urgency = f"{days} days"

                row = TableRow(alternate=(i % 2 == 1))
                row.set_click_data(item)
                row.clicked.connect(
                    lambda payload: self._open_missionary(
                        payload.get("missionary_id")
                    )
                )

                row.add_cell(
                    item["name"],
                    stretch=3,
                    bold=True,
                )

                row.add_cell(
                    item["field_label"],
                    stretch=3,
                )

                row.add_cell(
                    item["date"].strftime("%b %d, %Y"),
                    stretch=2,
                )

                row.add_cell(
                    urgency,
                    stretch=2,
                    bold=True,
                    color=day_color,
                )

                row.add_button(
                    "Open",
                    lambda checked=False, missionary_id=item.get("missionary_id"):
                    self._open_missionary(missionary_id),
                )

                card.add_widget(row)

        self.content_layout.addWidget(card)

    # ==========================================
    # MISSING DOCUMENTS
    # ==========================================

    def _build_missing_section(self, missing_docs):
        self.content_layout.addWidget(
            SectionHeader("✗   Missing Required Documents")
        )

        card = ListCard()

        card.add_widget(
            ColumnHeaderRow([
                ("Missionary", 2),
                ("Missing Documents", 5),
                ("", 1),
            ])
        )

        if not missing_docs:
            card.add_empty(
                "All missionaries have their "
                "required documents."
            )

        else:
            for i, item in enumerate(missing_docs):
                row = TableRow(alternate=(i % 2 == 1))
                row.set_click_data(item)
                row.clicked.connect(
                    lambda payload: self._open_missionary(
                        payload.get("missionary_id")
                    )
                )

                row.add_cell(
                    item["name"],
                    stretch=2,
                    bold=True,
                    align=Qt.AlignTop | Qt.AlignLeft,
                )

                lines = []

                for doc in item["missing"]:
                    stage = doc["stage"]
                    label = doc["label"]

                    lines.append(
                        f"[{stage}]  {label}"
                    )

                row.add_cell(
                    "\n".join(lines),
                    stretch=5,
                    word_wrap=True,
                    color="#71717A",
                )

                row.add_button(
                    "Open",
                    lambda checked=False, missionary_id=item.get("missionary_id"):
                    self._open_missionary(missionary_id),
                )

                card.add_widget(row)

        self.content_layout.addWidget(card)

    def _open_missionary(self, missionary_id):
        if missionary_id is None or self.main_window is None:
            return

        opener = getattr(
            self.main_window,
            "open_missionary_detail",
            None,
        )
        if callable(opener):
            opener(missionary_id)

    # ==========================================
    # AUTO-REFRESH ON SHOW
    # ==========================================

    def showEvent(self, event):
        super().showEvent(event)

        self.load_data()
