from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QFrame,
)

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette

from services.dashboard_service import (
    DashboardService,
)
from services.appointment_service import AppointmentService
from services.daily_digest_service import DailyDigestService
from services.settings_service import SettingsService
from ui.foundation import (
    SectionTitle as SectionHeader,
    StatCard,
    create_button,
    create_scroll_area,
    show_message,
)
from ui.foundation.fluent import SimpleCardWidget

from utils.constants import WORKFLOW_STAGES
from utils.i18n import tr

from utils.logger import logger


# ==========================================
# COLOR PALETTE
# ==========================================

STAGE_COLORS = {
    "INTERPOL": "#7A6EEC",
    "CARNET DE EXTRANJERIA": "#D97706",
    "PRORROGA": "#059669",
    "CANCELACION": "#DC2626",
}

TONE_COLORS = {
    "#DC2626": "danger",
    "#D97706": "warning",
    "#0EA5AC": "info",
    "#059669": "success",
    "#71717A": "neutral",
    "#52525B": "neutral",
}


def _tone_from_color(color):
    return TONE_COLORS.get(str(color or "").upper(), "neutral")

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
        self.digest_service = DailyDigestService()
        self.startup_alerts = []
        self._automation_running = False

        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        header_bar = QFrame()
        header_bar.setObjectName("DashboardTopBar")
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(12, 10, 16, 12)
        header_layout.setSpacing(8)
        header_bar.setLayout(header_layout)

        header_layout.addWidget(self._build_dashboard_tabs())

        command_row = QHBoxLayout()
        command_row.setContentsMargins(0, 0, 0, 0)
        command_row.setSpacing(12)

        self.dashboard_title = QLabel(tr("dashboard_title"))
        self.dashboard_title.setObjectName("DashboardTitle")

        self.dashboard_subtitle = QLabel(tr("dashboard_loading"))
        self.dashboard_subtitle.setObjectName("DashboardSubtitle")

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(3)
        title_stack.addWidget(self.dashboard_title)
        title_stack.addWidget(self.dashboard_subtitle)

        self.refresh_btn = create_button(
            tr("common_refresh"),
            "secondary",
        )

        self.refresh_btn.setObjectName("RefreshButton")

        self.refresh_btn.clicked.connect(
            self.load_data
        )

        command_row.addLayout(title_stack)
        command_row.addStretch()
        command_row.addWidget(self.refresh_btn)
        header_layout.addLayout(command_row)

        outer.addWidget(header_bar)

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
            12, 12, 24, 24
        )

        self.content_layout.setSpacing(12)

        self.content_widget.setLayout(
            self.content_layout
        )

        scroll.setWidget(self.content_widget)

        outer.addWidget(scroll, stretch=1)

        self.load_data()

    def _build_dashboard_tabs(self):
        strip = QFrame()
        strip.setObjectName("DashboardTabStrip")
        strip.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        strip.setLayout(layout)

        for text, active in [
            (tr("dashboard_tab_mission"), True),
            (tr("dashboard_tab_process"), False),
            (tr("dashboard_tab_link"), False),
        ]:
            label = QLabel(text)
            label.setObjectName("DashboardTopTab")
            label.setProperty("active", active)
            label.setFixedHeight(30)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)

        layout.addStretch()
        return strip

    def load_data(self):
        self._run_process_automation()

        # Clear existing content
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

        data = self.service.get_summary()

        self._build_dashboard_workspace(data)

        self.content_layout.addStretch()

        logger.info("Dashboard data loaded")

    def _build_dashboard_workspace(self, data):
        self._build_startup_alert_banner()

        workspace = QWidget()
        workspace.setObjectName("DashboardWorkspace")
        workspace.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        workspace.setLayout(layout)

        primary = QWidget()
        primary.setObjectName("DashboardPrimaryColumn")
        primary_layout = QVBoxLayout()
        primary_layout.setContentsMargins(0, 0, 0, 0)
        primary_layout.setSpacing(12)
        primary.setLayout(primary_layout)

        side = QWidget()
        side.setObjectName("DashboardSideColumn")
        side_layout = QVBoxLayout()
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        side.setLayout(side_layout)

        layout.addWidget(primary, stretch=7)
        layout.addWidget(side, stretch=5)

        self._build_daily_digest_section(primary_layout)
        self._build_attention_section(
            data.get("attention_items", []),
            primary_layout,
        )
        primary_layout.addStretch()

        self._build_recommended_section(
            data.get("recommended_tasks", []),
            side_layout,
        )
        self._build_stat_cards(data, side_layout)
        self._build_expiring_section(data["expiring"], side_layout)
        self._build_missing_section(data["missing_docs"], side_layout)
        side_layout.addStretch()

        self.content_layout.addWidget(workspace)

    def _run_process_automation(self):
        if self.main_window is None or self._automation_running:
            return
        self._automation_running = True
        try:
            from services.process_automation_service import (
                ProcessAutomationService,
            )

            ProcessAutomationService(
                settings_service=self.main_window.settings_service
            ).run()
        except Exception:
            logger.exception("Process automation failed during dashboard load")
        finally:
            self._automation_running = False

    def set_startup_alerts(self, alerts):
        self.startup_alerts = list(alerts or [])
        self.load_data()

    def _build_startup_alert_banner(self, target_layout=None):
        if not self.startup_alerts:
            return

        overdue_count = sum(
            1
            for alert in self.startup_alerts
            if int(alert.get("days", 0)) < 0
        )
        urgent_count = sum(
            1
            for alert in self.startup_alerts
            if alert.get("severity") in {"critical", "warning"}
            and int(alert.get("days", 9999)) >= 0
        )
        parts = []
        if overdue_count:
            parts.append(tr("dashboard_alert_overdue", count=overdue_count))
        if urgent_count:
            parts.append(tr("dashboard_alert_due_week", count=urgent_count))
        if not parts:
            parts.append(tr("dashboard_alert_due_month"))

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
            tr(
                "dashboard_alert_banner_title",
                count=len(self.startup_alerts),
            )
        )
        title.setObjectName("StrongText")

        detail = QLabel(", ".join(parts))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        text_stack.addWidget(title)
        text_stack.addWidget(detail)

        button = create_button(tr("dashboard_review_alerts"), "primary")
        button.clicked.connect(self.startup_alerts_requested.emit)

        layout.addWidget(accent)
        layout.addLayout(text_stack, stretch=1)
        layout.addWidget(button)

        (target_layout or self.content_layout).addWidget(banner)

    def _build_daily_digest_section(self, target_layout=None):
        target_layout = target_layout or self.content_layout
        settings_service = (
            self.main_window.settings_service
            if self.main_window is not None
            and hasattr(self.main_window, "settings_service")
            else SettingsService()
        )
        settings = settings_service.get_daily_digest_settings()
        digest = self.digest_service.build_digest(
            include_overdue=settings.get("include_overdue", True),
            detail_level=settings.get("detail_level", "balanced"),
            language=settings_service.get_language(),
        )

        self._set_dashboard_subtitle_from_digest(digest)

        target_layout.addWidget(
            SectionHeader(tr("dashboard_today"))
        )

        card = SimpleCardWidget()
        card.setObjectName("DailyDigestCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)
        card.setLayout(layout)

        self._add_digest_summary(layout, digest)
        self._add_digest_details(layout, digest)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch()

        refresh = create_button(tr("common_refresh"), "secondary")
        refresh.clicked.connect(self.load_data)
        actions.addWidget(refresh)

        copy = create_button(tr("dashboard_copy_summary"), "primary")
        copy.clicked.connect(
            lambda checked=False, text=digest.get("text", ""):
            self._copy_daily_digest(text)
        )
        actions.addWidget(copy)
        layout.addLayout(actions)

        target_layout.addWidget(card)

    def _set_dashboard_subtitle_from_digest(self, digest):
        if not hasattr(self, "dashboard_subtitle"):
            return

        summary = digest.get("summary") or {}
        total = summary.get("total", 0)
        self.dashboard_subtitle.setText(self._digest_total_text(total))

    @staticmethod
    def _digest_total_text(total):
        try:
            total = int(total or 0)
        except (TypeError, ValueError):
            total = 0

        if total == 0:
            return tr("dashboard_no_actions_today")
        if total == 1:
            return tr("dashboard_one_action_today")
        return tr("dashboard_many_actions_today", count=total)

    @staticmethod
    def _flatten_digest_items(digest):
        items = []
        for group in digest.get("detail_groups") or []:
            for item in group.get("items", []) or []:
                items.append(item)
        return items

    def _add_digest_summary(self, layout, digest):
        summary = digest.get("summary") or {}
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        for key, label, color in [
            ("critical", tr("dashboard_metric_critical"), "#DC2626"),
            ("overdue", tr("dashboard_metric_overdue"), "#D97706"),
            ("due_today", tr("dashboard_metric_due_today"), "#0EA5AC"),
            ("total", tr("dashboard_metric_total_open"), "#71717A"),
        ]:
            row.addWidget(
                self._make_digest_metric_tile(summary.get(key, 0), label, color)
            )

        layout.addLayout(row)

    def _add_digest_details(self, layout, digest):
        groups = digest.get("detail_groups") or []

        self._build_digest_start_here(layout, digest)

        if not self._flatten_digest_items(digest):
            return

        intro = QLabel(tr("dashboard_mission_queue"))
        intro.setObjectName("SectionHeader")
        layout.addWidget(intro)

        for group in groups:
            if group.get("items"):
                self._build_digest_mission_group(layout, group)

    def _build_digest_start_here(self, layout, digest):
        items = self._flatten_digest_items(digest)

        panel = QFrame()
        panel.setObjectName("DigestStartHerePanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)

        panel_layout = QHBoxLayout()
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(14)
        panel.setLayout(panel_layout)

        accent = QFrame()
        accent.setObjectName("DigestStartHereAccent")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(58)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(5)

        label = QLabel(tr("dashboard_start_here"))
        label.setObjectName("SectionHeader")
        text_stack.addWidget(label)

        if not items:
            title = QLabel(tr("dashboard_all_clear_title"))
            title.setObjectName("StrongText")
            detail = QLabel(tr("dashboard_all_clear_detail"))
            detail.setObjectName("MutedText")
            detail.setWordWrap(True)
            text_stack.addWidget(title)
            text_stack.addWidget(detail)
            panel_layout.addWidget(accent)
            panel_layout.addLayout(text_stack, stretch=1)
            layout.addWidget(panel)
            return

        first_item = min(
            items,
            key=lambda item: (
                item.get("severity_rank", 99),
                item.get("days", 9999),
                item.get("action", ""),
            ),
        )

        title = QLabel(
            first_item.get("action") or tr("dashboard_review_due_work")
        )
        title.setObjectName("PanelTitle")
        title.setWordWrap(True)

        detail_parts = [first_item.get("who") or tr("dashboard_office")]
        count = first_item.get("missionary_count") or 0
        if count > 1:
            detail_parts.append(
                tr("dashboard_missionaries_affected", count=count)
            )
        if first_item.get("timing"):
            detail_parts.append(first_item["timing"])

        detail = QLabel("  |  ".join(part for part in detail_parts if part))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        chip = self._make_digest_chip(
            first_item.get("timing") or tr("dashboard_open"),
            self._attention_color(first_item.get("severity")),
        )

        review_btn = create_button(
            tr("dashboard_review"),
            "primary",
            fixed_height=30,
        )
        review_btn.clicked.connect(
            lambda checked=False, payload=first_item:
            self._open_digest_item(payload)
        )

        text_stack.addWidget(title)
        text_stack.addWidget(detail)

        panel_layout.addWidget(accent)
        panel_layout.addLayout(text_stack, stretch=1)
        panel_layout.addWidget(chip)
        panel_layout.addWidget(review_btn)

        layout.addWidget(panel)

    def _build_digest_mission_group(self, layout, group):
        card = QFrame()
        card.setObjectName("DigestMissionCard")
        card.setAttribute(Qt.WA_StyledBackground, True)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)
        card.setLayout(card_layout)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title = QLabel(
            tr(
                "dashboard_group_title",
                title=group.get("title") or tr("dashboard_work"),
            )
        )
        title.setObjectName("StrongText")
        count = self._make_digest_chip(
            tr("dashboard_open_count", count=group.get("count", 0)),
            "#71717A",
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(count)
        card_layout.addLayout(header)

        for item in group.get("items", [])[:12]:
            row = QFrame()
            row.setObjectName("DigestMissionRow")
            row.setAttribute(Qt.WA_StyledBackground, True)
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(10)
            row.setLayout(row_layout)

            text_stack = QVBoxLayout()
            text_stack.setContentsMargins(0, 0, 0, 0)
            text_stack.setSpacing(2)

            who = QLabel(item.get("who") or tr("dashboard_office"))
            who.setObjectName("StrongText")
            who.setWordWrap(True)

            action_text = item.get("action") or tr("dashboard_task")
            item_count = item.get("missionary_count") or 0
            if item_count > 1:
                action_text = (
                    f"{action_text} "
                    f"({tr('dashboard_missionaries_count', count=item_count)})"
                )

            action = QLabel(action_text)
            action.setObjectName("RowText")
            action.setWordWrap(True)

            text_stack.addWidget(who)
            text_stack.addWidget(action)

            timing = self._make_digest_chip(
                item.get("timing") or tr("dashboard_open"),
                self._attention_color(item.get("severity")),
            )

            open_btn = create_button(
                tr("dashboard_action_open"),
                "subtle",
                fixed_height=28,
            )
            open_btn.clicked.connect(
                lambda checked=False, payload=item:
                self._open_digest_item(payload)
            )

            row_layout.addLayout(text_stack, stretch=1)
            row_layout.addWidget(timing)
            row_layout.addWidget(open_btn)

            card_layout.addWidget(row)

        if group.get("count", 0) > 12:
            more = QLabel(
                f"+ {group['count'] - 12} more in {group.get('title', 'Work')}"
            )
            more.setObjectName("MutedText")
            card_layout.addWidget(more)

        layout.addWidget(card)

    @staticmethod
    def _make_digest_metric_tile(value, label, color):
        tile = QFrame()
        tile.setObjectName("DigestSummaryTile")
        tile.setAttribute(Qt.WA_StyledBackground, True)
        tile_layout = QVBoxLayout()
        tile_layout.setContentsMargins(12, 10, 12, 10)
        tile_layout.setSpacing(2)
        tile.setLayout(tile_layout)

        value_label = QLabel(str(value))
        value_label.setObjectName("DigestMetricValue")
        value_label.setProperty("tone", _tone_from_color(color))

        caption = QLabel(label)
        caption.setObjectName("MutedText")

        tile_layout.addWidget(value_label)
        tile_layout.addWidget(caption)

        return tile

    @staticmethod
    def _make_digest_chip(text, color):
        chip = QLabel(str(text or tr("dashboard_open")))
        chip.setObjectName("DigestChip")
        chip.setAlignment(Qt.AlignCenter)
        chip.setProperty("tone", _tone_from_color(color))
        return chip

    def _open_digest_item(self, item):
        if not item:
            return
        task_id = item.get("task_id")
        if task_id and self.main_window is not None:
            opener = getattr(self.main_window, "open_alert_workspace", None)
            if callable(opener):
                opener(task_id, return_key="dashboard")
                return
        if item.get("missionary_id") and self.main_window is not None:
            opener = getattr(self.main_window, "open_missionary_detail", None)
            if callable(opener):
                opener(item.get("missionary_id"))
                return
        if self.main_window is None:
            return
        office_page = getattr(self.main_window, "office_work_page", None)
        if office_page is not None and hasattr(office_page, "focus_task_context"):
            office_page.focus_task_context(
                task_id=item.get("task_id"),
                title=item.get("action", ""),
            )
        self.main_window.set_current_key("office_work")

    def _copy_daily_digest(self, text):
        QApplication.clipboard().setText(text or "")
        show_message(
            self,
            tr("dashboard_daily_digest"),
            tr("dashboard_digest_copied"),
        )

    def _build_attention_section(self, attention_items, target_layout=None):
        target_layout = target_layout or self.content_layout
        target_layout.addWidget(
            SectionHeader(tr("dashboard_needs_attention"))
        )

        card = ListCard()
        card.setObjectName("NeedsAttentionCard")

        if not attention_items:
            card.add_empty(tr("dashboard_no_urgent_items"))
            target_layout.addWidget(card)
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
                    tr("dashboard_complete"),
                    lambda checked=False, payload=item:
                    self._complete_attention_appointment(payload),
                    variant="success",
                )
                row.add_button(
                    tr("dashboard_missed"),
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

        target_layout.addWidget(card)

    def _build_recommended_section(self, tasks, target_layout=None):
        target_layout = target_layout or self.content_layout
        target_layout.addWidget(
            SectionHeader(tr("dashboard_recommended_this_week"))
        )

        card = SimpleCardWidget()
        card.setObjectName("RecommendedThisWeekCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        card.setLayout(layout)

        if not tasks:
            self._add_recommended_empty(layout)
            target_layout.addWidget(card)
            return

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)

        title = QLabel(tr("dashboard_weekly_mission_plan"))
        title.setObjectName("PanelTitle")

        subtitle = QLabel(self._recommended_summary_text(tasks))
        subtitle.setObjectName("MutedText")
        subtitle.setWordWrap(True)

        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)

        header.addLayout(title_stack, stretch=1)
        header.addWidget(
            self._make_digest_chip(
                f"{len(tasks)} open",
                "#71717A",
            )
        )
        layout.addLayout(header)

        lead_task = tasks[0]
        self._add_recommended_focus(layout, lead_task)

        if len(tasks) > 1:
            queue_label = QLabel(tr("dashboard_this_week_queue"))
            queue_label.setObjectName("SectionHeader")
            layout.addWidget(queue_label)

        for task in tasks[1:10]:
            layout.addWidget(self._make_recommended_row(task))

        if len(tasks) > 10:
            more = QLabel(
                tr(
                    "dashboard_more_recommendations",
                    count=len(tasks) - 10,
                )
            )
            more.setObjectName("MutedText")
            layout.addWidget(more)

        target_layout.addWidget(card)

    def _add_recommended_empty(self, layout):
        panel = QFrame()
        panel.setObjectName("RecommendedEmptyPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)

        panel_layout = QHBoxLayout()
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(14)
        panel.setLayout(panel_layout)

        accent = QFrame()
        accent.setObjectName("RecommendedAccent")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(44)
        accent.setProperty("tone", "success")

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(3)

        title = QLabel(tr("dashboard_no_recommended_title"))
        title.setObjectName("StrongText")

        detail = QLabel(tr("dashboard_no_recommended_detail"))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        text_stack.addWidget(title)
        text_stack.addWidget(detail)
        panel_layout.addWidget(accent)
        panel_layout.addLayout(text_stack, stretch=1)

        layout.addWidget(panel)

    def _add_recommended_focus(self, layout, task):
        panel = QFrame()
        panel.setObjectName("RecommendedFocusPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)

        panel_layout = QHBoxLayout()
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(14)
        panel.setLayout(panel_layout)

        accent = QFrame()
        accent.setObjectName("RecommendedAccent")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(58)
        accent.setProperty("tone", self._recommended_tone(task))

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(5)

        label = QLabel(tr("dashboard_next_best_move"))
        label.setObjectName("SectionHeader")

        title = QLabel(task.get("title") or tr("dashboard_recommended_task"))
        title.setObjectName("PanelTitle")
        title.setWordWrap(True)

        detail = QLabel(task.get("detail", ""))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        text_stack.addWidget(label)
        text_stack.addWidget(title)
        if task.get("detail"):
            text_stack.addWidget(detail)

        chip = self._make_digest_chip(
            task.get("timing") or tr("dashboard_open"),
            self._attention_color(task.get("severity")),
        )

        open_btn = create_button(
            self._attention_action_label(self._recommended_payload(task)),
            "primary",
            fixed_height=30,
        )
        open_btn.clicked.connect(
            lambda checked=False, payload=self._recommended_payload(task):
            self._open_attention_item(payload)
        )

        panel_layout.addWidget(accent)
        panel_layout.addLayout(text_stack, stretch=1)
        panel_layout.addWidget(chip)
        panel_layout.addWidget(open_btn)

        layout.addWidget(panel)

    def _make_recommended_row(self, task):
        row = QFrame()
        row.setObjectName("RecommendedThisWeekRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setCursor(Qt.PointingHandCursor)
        row.mousePressEvent = (
            lambda event, payload=self._recommended_payload(task):
            self._open_attention_item(payload)
        )

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(10)
        row.setLayout(row_layout)

        accent = QFrame()
        accent.setObjectName("RecommendedAccent")
        accent.setFixedWidth(4)
        accent.setMinimumHeight(42)
        accent.setProperty("tone", self._recommended_tone(task))

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(2)

        title = QLabel(task.get("title") or tr("dashboard_recommended_task"))
        title.setObjectName("StrongText")
        title.setWordWrap(True)

        detail = QLabel(task.get("detail", ""))
        detail.setObjectName("RowText")
        detail.setWordWrap(True)

        text_stack.addWidget(title)
        if task.get("detail"):
            text_stack.addWidget(detail)

        chip = self._make_digest_chip(
            task.get("timing") or tr("dashboard_open"),
            self._attention_color(task.get("severity")),
        )

        open_btn = create_button(
            self._attention_action_label(self._recommended_payload(task)),
            "subtle",
            fixed_height=28,
        )
        open_btn.clicked.connect(
            lambda checked=False, payload=self._recommended_payload(task):
            self._open_attention_item(payload)
        )

        row_layout.addWidget(accent)
        row_layout.addLayout(text_stack, stretch=1)
        row_layout.addWidget(chip)
        row_layout.addWidget(open_btn)

        return row

    @staticmethod
    def _recommended_payload(task):
        task_id = task.get("task_id") or task.get("id")
        return {
            "type": "secretary_task" if task_id else None,
            "task_id": task_id,
            "target": (
                "missionary"
                if task.get("missionary_id")
                else "office_work"
            ),
            "missionary_id": task.get("missionary_id"),
        }

    @staticmethod
    def _recommended_summary_text(tasks):
        overdue = sum(1 for task in tasks if task.get("days", 0) < 0)
        today = sum(1 for task in tasks if task.get("days") == 0)
        upcoming = max(0, len(tasks) - overdue - today)

        parts = []
        if overdue:
            parts.append(tr("dashboard_summary_overdue", count=overdue))
        if today:
            parts.append(tr("dashboard_summary_due_today", count=today))
        if upcoming:
            parts.append(tr("dashboard_summary_upcoming", count=upcoming))
        return " | ".join(parts) if parts else tr("dashboard_no_dated_recommendations")

    @staticmethod
    def _recommended_tone(task):
        severity = task.get("severity")
        if severity == "critical":
            return "danger"
        if severity == "warning":
            return "warning"
        return "info"

    @staticmethod
    def _attention_type_label(item_type):
        labels = {
            "document_expiration": "Document",
            "missing_document": "Missing Doc",
            "appointment_due": "Appointment",
            "secretary_task": "Task",
            "waiting_follow_up": "Follow-Up",
            "waiting_no_follow_up": "Follow-Up",
            "ready_task": "Task",
            "transfer_reminder": "Task",
        }
        return labels.get(item_type, "Item")

    @staticmethod
    def _attention_color(severity):
        return {
            "critical": "#DC2626",
            "warning": "#D97706",
            "info": "#0EA5AC",
        }.get(severity, "#71717A")

    @staticmethod
    def _attention_action_label(item):
        if item.get("task_id") and item.get("type") in {
            "secretary_task",
            "waiting_follow_up",
            "waiting_no_follow_up",
            "ready_task",
            "transfer_reminder",
        }:
            return tr("dashboard_action_review_task")
        if item.get("missionary_id"):
            return tr("dashboard_action_open_missionary")
        target = item.get("target")
        if target == "office_work":
            return tr("dashboard_action_office_work")
        if target == "appointments":
            return tr("dashboard_action_open_calendar")
        return tr("dashboard_action_open")

    def _open_attention_item(self, item):
        if not item:
            return

        task_id = item.get("task_id")
        if (
            task_id
            and item.get("type") in {
                "secretary_task",
                "waiting_follow_up",
                "waiting_no_follow_up",
                "ready_task",
                "transfer_reminder",
            }
            and self.main_window is not None
        ):
            opener = getattr(self.main_window, "open_alert_workspace", None)
            if callable(opener):
                opener(task_id, return_key="dashboard")
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
                tr("dashboard_appointment_error"),
                tr("dashboard_appointment_complete_failed"),
                kind="critical",
            )

    def _miss_attention_appointment(self, item):
        appointment_id = item.get("appointment_id")
        if not appointment_id:
            return

        confirm = show_message(
            self,
            tr("dashboard_mark_missed_title"),
            (
                tr("dashboard_mark_missed_message")
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
                tr("dashboard_appointment_error"),
                tr("dashboard_appointment_missed_failed"),
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

    def _build_stat_cards(self, data, target_layout=None):
        target_layout = target_layout or self.content_layout
        target_layout.addWidget(
            SectionHeader("Overview")
        )

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        cards = []

        # Total card
        total_card = StatCard(
            data["total"],
            tr("dashboard_active_missionaries"),
            color="#0EA5AC",
        )

        cards.append(total_card)

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

            cards.append(card)

        for index, card in enumerate(cards):
            grid.addWidget(card, index // 2, index % 2)

        wrapper = QWidget()
        wrapper.setObjectName("DashboardStatGrid")
        wrapper.setLayout(grid)

        target_layout.addWidget(wrapper)

    # ==========================================
    # EXPIRING DOCUMENTS
    # ==========================================

    def _build_expiring_section(self, expiring, target_layout=None):
        target_layout = target_layout or self.content_layout
        target_layout.addWidget(
            SectionHeader(tr("dashboard_expiring_soon"))
        )

        card = ListCard()

        card.add_widget(
            ColumnHeaderRow([
                (tr("missionary_label"), 3),
                (tr("dashboard_document"), 3),
                (tr("dashboard_expiry_date"), 2),
                (tr("dashboard_days_remaining"), 2),
                ("", 1),
            ])
        )

        if not expiring:
            card.add_empty(
                tr("dashboard_no_expiring_documents")
            )

        else:
            for i, item in enumerate(expiring):
                days = item["days_left"]

                if days < 0:
                    day_color = "#DC2626"
                    urgency = tr("dashboard_expired")

                elif days <= 14:
                    day_color = "#DC2626"
                    urgency = tr("dashboard_days_count", count=days)

                elif days <= 30:
                    day_color = "#D97706"
                    urgency = tr("dashboard_days_count", count=days)

                else:
                    day_color = "#059669"
                    urgency = tr("dashboard_days_count", count=days)

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
                    tr("dashboard_action_open"),
                    lambda checked=False, missionary_id=item.get("missionary_id"):
                    self._open_missionary(missionary_id),
                )

                card.add_widget(row)

        target_layout.addWidget(card)

    # ==========================================
    # MISSING DOCUMENTS
    # ==========================================

    def _build_missing_section(self, missing_docs, target_layout=None):
        target_layout = target_layout or self.content_layout
        target_layout.addWidget(
            SectionHeader(tr("dashboard_missing_required_documents"))
        )

        card = ListCard()

        card.add_widget(
            ColumnHeaderRow([
                (tr("missionary_label"), 2),
                (tr("dashboard_missing_documents"), 5),
                ("", 1),
            ])
        )

        if not missing_docs:
            card.add_empty(
                tr("dashboard_no_missing_documents")
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
                    tr("dashboard_action_open"),
                    lambda checked=False, missionary_id=item.get("missionary_id"):
                    self._open_missionary(missionary_id),
                )

                card.add_widget(row)

        target_layout.addWidget(card)

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
