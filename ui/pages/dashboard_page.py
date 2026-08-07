from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QBoxLayout,
    QLabel,
    QFrame,
    QSizePolicy,
    QStackedLayout,
    QGraphicsOpacityEffect,
)

from PySide6.QtCore import (
    Qt,
    Signal,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QObject,
    QRunnable,
    QThreadPool,
    Slot,
)
from PySide6.QtGui import QColor, QFont, QPalette, QPainter, QPen

from services.dashboard_service import (
    DashboardService,
)
from services.appointment_service import AppointmentService
from services.daily_digest_service import DailyDigestService
from services.settings_service import SettingsService
from ui.foundation import (
    SectionTitle as SectionHeader,
    StatCard,
    create_pill_button,
    create_scroll_area,
    show_message,
)
from ui.foundation.fluent import SimpleCardWidget

from utils.constants import WORKFLOW_STAGES
from utils.i18n import tr

from utils.logger import logger

import time


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


def create_button(
    text,
    variant="secondary",
    fixed_height=30,
    parent=None,
    icon=None,
):
    """Dashboard-wide pill action factory using the shared Fluent helper."""
    button = create_pill_button(text, parent=parent, icon=icon)
    button.setObjectName("DashboardPillButton")
    button.setProperty("dashboardTone", variant)
    button.setFixedHeight(fixed_height)
    button.setMinimumWidth(0)
    return button

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


class RefreshSpinner(QWidget):
    """Small indeterminate spinner used beside the dashboard refresh action."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(18, 18)

    def start(self):
        self._angle = 0
        self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()

    def _advance(self):
        self._angle = (self._angle + 28) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#0F8D94"), 2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(3, 3, 12, 12, -self._angle * 16, 235 * 16)


class RefreshStatusIndicator(QWidget):
    """Fades from a spinning refresh indicator to a confirmation checkmark."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)

        layout = QStackedLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._spinner = RefreshSpinner(self)
        self._check = QLabel("✓", self)
        self._check.setAlignment(Qt.AlignCenter)
        self._check.setStyleSheet("color: #059669; font-size: 17px; font-weight: 600;")
        layout.addWidget(self._spinner)
        layout.addWidget(self._check)
        self._layout = layout

        self._spinner_opacity = QGraphicsOpacityEffect(self._spinner)
        self._spinner.setGraphicsEffect(self._spinner_opacity)
        self._check_opacity = QGraphicsOpacityEffect(self._check)
        self._check.setGraphicsEffect(self._check_opacity)
        self._fade = QPropertyAnimation(self._spinner_opacity, b"opacity", self)
        self._fade.setDuration(150)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._show_checkmark)
        self._check_fade = QPropertyAnimation(self._check_opacity, b"opacity", self)
        self._check_fade.setDuration(180)
        self._check_fade.setEasingCurve(QEasingCurve.OutCubic)
        self.hide()

    def show_loading(self):
        self._fade.stop()
        self._check_fade.stop()
        self._layout.setCurrentWidget(self._spinner)
        self._spinner_opacity.setOpacity(1.0)
        self._check_opacity.setOpacity(0.0)
        self.show()
        self._spinner.start()

    def show_complete(self):
        self._spinner.stop()
        self._fade.setStartValue(self._spinner_opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _show_checkmark(self):
        self._layout.setCurrentWidget(self._check)
        self._check_fade.setStartValue(0.0)
        self._check_fade.setEndValue(1.0)
        self._check_fade.start()


class DashboardLoadSignals(QObject):
    finished = Signal(int, object, object, float)
    failed = Signal(int, str)


class DashboardLoadWorker(QRunnable):
    def __init__(
        self,
        generation,
        service,
        digest_service,
        digest_options,
        settings_service=None,
        run_automation=False,
    ):
        super().__init__()
        self.generation = generation
        self.service = service
        self.digest_service = digest_service
        self.digest_options = dict(digest_options)
        self.settings_service = settings_service
        self.run_automation = run_automation
        self.signals = DashboardLoadSignals()

    @Slot()
    def run(self):
        started = time.perf_counter()
        try:
            if self.run_automation and self.settings_service is not None:
                from services.process_automation_service import (
                    ProcessAutomationService,
                )

                ProcessAutomationService(
                    settings_service=self.settings_service
                ).run()
            data = self.service.get_summary()
            digest = self.digest_service.build_digest(
                **self.digest_options,
                items=data.get("attention_items", []),
            )
            self.signals.finished.emit(
                self.generation,
                data,
                digest,
                (time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc))


# ==========================================
# DASHBOARD PAGE
# ==========================================

class DashboardPage(QWidget):
    startup_alerts_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardPage")

        self.main_window = parent
        self.service = DashboardService()
        self.digest_service = DailyDigestService()
        self.startup_alerts = []
        self._automation_running = False
        self._show_all_priorities = False
        self._digest_expanded = False
        self._expiring_expanded = False
        self._missing_expanded = False
        self._last_dashboard_data = None
        self._last_dashboard_digest = None
        self._dashboard_size_class = None
        self._refresh_generation = 0
        self._refresh_in_flight = False
        self._refresh_requested_after_current = False
        self._last_refresh_at = 0.0
        self._dashboard_cache_ttl_seconds = 30.0
        self._dashboard_workers = {}
        self._thread_pool = QThreadPool.globalInstance()

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

        command_row = QHBoxLayout()
        command_row.setContentsMargins(0, 0, 0, 0)
        command_row.setSpacing(12)

        self.dashboard_title = QLabel(tr("dashboard_title"))
        self.dashboard_title.setObjectName("DashboardTitle")

        self.dashboard_subtitle = QLabel(tr("dashboard_loading"))
        self.dashboard_subtitle.setObjectName("DashboardSubtitle")
        self.dashboard_subtitle.setWordWrap(True)
        self.dashboard_subtitle.setMinimumWidth(0)
        self.dashboard_subtitle.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )

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
            self._refresh_from_button
        )
        self.refresh_status = RefreshStatusIndicator()

        command_row.addLayout(title_stack)
        command_row.addStretch()
        command_row.addWidget(self.refresh_btn)
        command_row.addWidget(self.refresh_status)
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

        if self.main_window is None:
            self.load_data()
        else:
            QTimer.singleShot(0, lambda: self.request_refresh(force=False))

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
        """Compatibility entry point: mutations request a forced refresh."""
        if self.main_window is None:
            self._load_data_synchronously()
            return
        self.request_refresh(force=True)

    def _load_data_synchronously(self):
        self._run_process_automation()
        data = self.service.get_summary()
        self._last_dashboard_data = data
        self._last_dashboard_digest = self._build_digest_payload(data)
        self._last_refresh_at = time.monotonic()
        self._render_dashboard(data)
        logger.info("Dashboard data loaded")

    def request_refresh(self, force=False):
        now = time.monotonic()
        cache_is_fresh = (
            self._last_dashboard_data is not None
            and now - self._last_refresh_at < self._dashboard_cache_ttl_seconds
        )
        if cache_is_fresh and not force:
            return False
        if self._refresh_in_flight:
            self._refresh_requested_after_current |= bool(force)
            return False

        settings_service = (
            self.main_window.settings_service
            if self.main_window is not None
            and hasattr(self.main_window, "settings_service")
            else SettingsService()
        )
        digest_settings = settings_service.get_daily_digest_settings()
        digest_options = {
            "include_overdue": digest_settings.get("include_overdue", True),
            "detail_level": digest_settings.get("detail_level", "balanced"),
            "language": settings_service.get_language(),
        }
        self._refresh_generation += 1
        generation = self._refresh_generation
        self._refresh_in_flight = True
        self._automation_running = self.main_window is not None
        self.refresh_btn.setEnabled(False)
        self.refresh_status.show_loading()

        worker = DashboardLoadWorker(
            generation,
            self.service,
            self.digest_service,
            digest_options,
            settings_service=settings_service,
            run_automation=self.main_window is not None,
        )
        worker.signals.finished.connect(self._dashboard_refresh_finished)
        worker.signals.failed.connect(self._dashboard_refresh_failed)
        self._dashboard_workers[generation] = worker
        self._thread_pool.start(worker)
        return True

    @Slot(int, object, object, float)
    def _dashboard_refresh_finished(self, generation, data, digest, elapsed_ms):
        self._dashboard_workers.pop(generation, None)
        if generation != self._refresh_generation:
            return
        self._refresh_in_flight = False
        self._automation_running = False
        content_changed = (
            data != self._last_dashboard_data
            or digest != self._last_dashboard_digest
        )
        self._last_dashboard_data = data
        self._last_dashboard_digest = digest
        self._last_refresh_at = time.monotonic()
        self._set_dashboard_subtitle_from_digest(digest)
        if content_changed:
            self._render_dashboard(data)
        self.refresh_btn.setEnabled(True)
        self.refresh_status.show_complete()
        logger.info("Dashboard refreshed in %.1f ms", elapsed_ms)
        if self._refresh_requested_after_current:
            self._refresh_requested_after_current = False
            self.request_refresh(force=True)

    @Slot(int, str)
    def _dashboard_refresh_failed(self, generation, message):
        self._dashboard_workers.pop(generation, None)
        if generation != self._refresh_generation:
            return
        self._refresh_in_flight = False
        self._automation_running = False
        self.refresh_btn.setEnabled(True)
        self.refresh_status.show_complete()
        logger.error("Dashboard background refresh failed: %s", message)

    def _refresh_from_button(self):
        self.request_refresh(force=True)

    def _render_dashboard(self, data):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._build_dashboard_workspace(data)
        self.content_layout.addStretch()

    def _build_digest_payload(self, data=None):
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
            items=(data or {}).get("attention_items") if data is not None else None,
        )
        self._set_dashboard_subtitle_from_digest(digest)
        return digest

    @staticmethod
    def _dashboard_class_for_width(width):
        if width < 700:
            return "narrow"
        if width < 1100:
            return "compact"
        return "wide"

    def _current_dashboard_class(self):
        return self._dashboard_size_class or self._dashboard_class_for_width(
            self.width()
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size_class = self._dashboard_class_for_width(event.size().width())
        if size_class == self._dashboard_size_class:
            return
        self._dashboard_size_class = size_class
        if self._last_dashboard_data is not None:
            QTimer.singleShot(
                0,
                lambda: self._render_dashboard(self._last_dashboard_data),
            )

    def _build_dashboard_workspace(self, data):
        self._build_startup_alert_banner()
        self._build_focus_metrics(data)

        middle = QWidget()
        middle.setObjectName("DashboardMiddleRow")
        middle_layout = QVBoxLayout()
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(12)
        middle.setLayout(middle_layout)
        middle_layout.addWidget(self._build_upcoming_card(data))

        tracking = QWidget()
        tracking.setObjectName("DashboardTrackingRow")
        direction = (
            QBoxLayout.LeftToRight
            if self._current_dashboard_class() == "wide"
            else QBoxLayout.TopToBottom
        )
        tracking_layout = QBoxLayout(direction)
        tracking_layout.setContentsMargins(0, 0, 0, 0)
        tracking_layout.setSpacing(12)
        tracking.setLayout(tracking_layout)
        tracking_layout.addWidget(self._build_residency_expiration_card(data), 1)
        tracking_layout.addWidget(self._build_cancelaciones_card(data), 1)
        middle_layout.addWidget(tracking)
        self.content_layout.addWidget(middle)

        self._build_exception_cards(data)
        if self._expiring_expanded:
            self._build_expiring_section(data.get("expiring", []))
        if self._missing_expanded:
            self._build_missing_section(data.get("missing_docs", []))

    def _build_focus_metrics(self, data):
        wrapper = QWidget()
        wrapper.setObjectName("DashboardFocusMetrics")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        wrapper.setLayout(grid)
        size_class = self._current_dashboard_class()
        columns = 4 if size_class == "wide" else (2 if size_class == "compact" else 1)
        metrics = [
            (data.get("total", 0), tr("dashboard_active_missionaries"), "info"),
            (data.get("urgent_count", 0), tr("dashboard_urgent_items"), "danger"),
            (data.get("appointments_today", 0), tr("dashboard_appointments_today"), "info"),
            (data.get("open_task_count", 0), tr("dashboard_open_tasks"), "success"),
        ]
        for index, (value, title, tone) in enumerate(metrics):
            card = SimpleCardWidget()
            card.setObjectName("DashboardFocusMetric")
            card.setProperty("tone", tone)
            layout = QVBoxLayout()
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(2)
            card.setLayout(layout)
            value_label = QLabel(str(value))
            value_label.setObjectName("DashboardFocusMetricValue")
            value_label.setProperty("tone", tone)
            title_label = QLabel(title)
            title_label.setObjectName("MutedText")
            title_label.setWordWrap(True)
            layout.addWidget(value_label)
            layout.addWidget(title_label)
            grid.addWidget(card, index // columns, index % columns)
        self.content_layout.addWidget(wrapper)

    @staticmethod
    def _priority_identity(item):
        if item.get("task_id"):
            return ("task", item["task_id"])
        if item.get("fingerprint"):
            return ("fingerprint", item["fingerprint"])
        return (
            item.get("type"),
            item.get("source_id"),
            item.get("missionary_id"),
            item.get("title"),
        )

    def _merged_priorities(self, data):
        items = [dict(item) for item in data.get("attention_items", [])]
        seen = {self._priority_identity(item) for item in items}
        for task in data.get("recommended_tasks", []):
            item = {
                **task,
                "type": "secretary_task",
                "task_id": task.get("id"),
                "target": "office_work",
                "title": task.get("title") or tr("dashboard_recommended_task"),
            }
            identity = self._priority_identity(item)
            if identity not in seen:
                seen.add(identity)
                items.append(item)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(
            items,
            key=lambda item: (
                severity_order.get(item.get("severity"), 9),
                item.get("days", 9999),
                item.get("title", ""),
            ),
        )

    def _build_priorities(self, data):
        self.content_layout.addWidget(SectionHeader(tr("dashboard_todays_priorities")))
        card = SimpleCardWidget()
        card.setObjectName("DashboardPrioritiesCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        card.setLayout(layout)
        priorities = self._merged_priorities(data)
        visible = priorities if self._show_all_priorities else priorities[:6]
        if not visible:
            empty = QLabel(tr("dashboard_no_urgent_items"))
            empty.setObjectName("EmptyLabel")
            layout.addWidget(empty)
        for item in visible:
            layout.addWidget(self._make_priority_row(item))
        if len(priorities) > 6:
            toggle = create_button(
                tr("dashboard_show_less") if self._show_all_priorities
                else tr("dashboard_view_all_priorities", count=len(priorities)),
                "subtle",
                fixed_height=30,
            )
            toggle.setObjectName("DashboardPriorityToggle")
            toggle.setMinimumWidth(0)
            toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            toggle.clicked.connect(self._toggle_priorities)
            layout.addWidget(toggle, alignment=Qt.AlignRight)
        self.content_layout.addWidget(card)

    def _make_priority_row(self, item):
        row = QFrame()
        row.setObjectName("DashboardPriorityRow")
        row.setProperty("severity", item.get("severity", "info"))
        row.setAttribute(Qt.WA_StyledBackground, True)
        direction = (
            QBoxLayout.TopToBottom
            if self._current_dashboard_class() == "narrow"
            else QBoxLayout.LeftToRight
        )
        layout = QBoxLayout(direction)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        row.setLayout(layout)
        text_stack = QVBoxLayout()
        title = QLabel(item.get("who") or item.get("missionary_name") or item.get("title", ""))
        title.setObjectName("StrongText")
        detail = QLabel(self._priority_detail_text(item))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)
        text_stack.addWidget(title)
        text_stack.addWidget(detail)
        layout.addLayout(text_stack, 1)
        badge = QLabel(self._attention_type_label(item.get("type")))
        badge.setObjectName("DashboardPriorityBadge")
        badge.setProperty("severity", item.get("severity", "info"))
        badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(badge)
        if item.get("type") == "appointment_due":
            complete = create_button(tr("dashboard_complete"), "success", fixed_height=28)
            complete.clicked.connect(
                lambda checked=False, payload=item: self._complete_attention_appointment(payload)
            )
            missed = create_button(tr("dashboard_missed"), "danger", fixed_height=28)
            missed.clicked.connect(
                lambda checked=False, payload=item: self._miss_attention_appointment(payload)
            )
            layout.addWidget(complete)
            layout.addWidget(missed)
        open_btn = create_button(self._attention_action_label(item), "secondary", fixed_height=28)
        open_btn.clicked.connect(
            lambda checked=False, payload=item: self._open_attention_item(payload)
        )
        layout.addWidget(open_btn)
        return row

    @staticmethod
    def _priority_detail_text(item):
        detail = item.get("detail") or ""
        if item.get("type") != "missing_document":
            return detail or item.get("title", "")

        document_label = item.get("document_label")
        missing_title = (
            f"Missing {document_label}"
            if document_label
            else item.get("title", "Missing document")
        )
        return f"{missing_title}. {detail}" if detail else missing_title

    def _toggle_priorities(self):
        self._show_all_priorities = not self._show_all_priorities
        self._render_dashboard(self._last_dashboard_data or {})

    def _build_upcoming_card(self, data):
        card = SimpleCardWidget()
        card.setObjectName("DashboardUpcomingCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        card.setLayout(layout)
        title = QLabel(tr("dashboard_upcoming"))
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        appointments = data.get("today_appointments", [])[:3]
        tasks = data.get("today_tasks", [])[:3]
        appointments_label = QLabel(tr("dashboard_appointments_today"))
        appointments_label.setObjectName("SectionHeader")
        layout.addWidget(appointments_label)
        if appointments:
            for item in appointments:
                layout.addWidget(
                    self._make_upcoming_row(
                        item.get("name") or tr("dashboard_office"),
                        item.get("type") or tr("dashboard_appointment"),
                        lambda checked=False, missionary_id=item.get("missionary_id"):
                        self._open_missionary(missionary_id),
                    )
                )
        else:
            layout.addWidget(self._muted_label(tr("dashboard_no_appointments_today")))

        tasks_label = QLabel(tr("dashboard_tasks_today"))
        tasks_label.setObjectName("SectionHeader")
        layout.addWidget(tasks_label)
        if tasks:
            for item in tasks:
                layout.addWidget(
                    self._make_upcoming_row(
                        item.get("title") or tr("dashboard_task"),
                        str(item.get("status") or "").title(),
                        lambda checked=False, task_id=item.get("id"), title=item.get("title", ""):
                        self._open_office_task(task_id, title),
                    )
                )
        else:
            layout.addWidget(self._muted_label(tr("dashboard_no_tasks_today")))

        actions = QBoxLayout(
            QBoxLayout.TopToBottom
            if self._current_dashboard_class() == "narrow"
            else QBoxLayout.LeftToRight
        )
        calendar_btn = create_button(tr("dashboard_action_open_calendar"), "subtle", fixed_height=28)
        calendar_btn.clicked.connect(self._open_calendar)
        office_btn = create_button(tr("dashboard_action_office_work"), "subtle", fixed_height=28)
        office_btn.clicked.connect(lambda: self._open_office_task(None, ""))
        actions.addWidget(calendar_btn)
        actions.addWidget(office_btn)
        if self._current_dashboard_class() != "narrow":
            actions.addStretch()
        layout.addLayout(actions)
        return card

    def _make_upcoming_row(self, title_text, detail_text, callback):
        row = QFrame()
        row.setObjectName("DashboardUpcomingRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        direction = (
            QBoxLayout.TopToBottom
            if self._current_dashboard_class() == "narrow"
            else QBoxLayout.LeftToRight
        )
        layout = QBoxLayout(direction)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        row.setLayout(layout)
        title = QLabel(title_text)
        title.setObjectName("StrongText")
        title.setWordWrap(True)
        detail = QLabel(detail_text)
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)
        open_btn = create_button(tr("dashboard_action_open"), "subtle", fixed_height=26)
        open_btn.clicked.connect(callback)
        layout.addWidget(title, 2)
        layout.addWidget(detail, 1)
        layout.addWidget(open_btn)
        return row

    @staticmethod
    def _muted_label(text):
        label = QLabel(text)
        label.setObjectName("MutedText")
        label.setWordWrap(True)
        return label

    def _build_residency_expiration_card(self, data):
        card = SimpleCardWidget()
        card.setObjectName("DashboardResidencyCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        card.setLayout(layout)
        title = QLabel(tr("dashboard_residency_expiration"))
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        items = data.get("residency_expirations", [])
        if items:
            for item in items:
                row = QFrame()
                row.setObjectName("DashboardResidencyRow")
                row_layout = QBoxLayout(
                    QBoxLayout.TopToBottom
                    if self._current_dashboard_class() == "narrow"
                    else QBoxLayout.LeftToRight
                )
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(8)
                row.setLayout(row_layout)

                identity = QVBoxLayout()
                name = QLabel(item.get("name", ""))
                name.setObjectName("StrongText")
                expiration = item.get("expiration_date")
                date_text = expiration.strftime("%b %d, %Y") if expiration else ""
                detail = QLabel(
                    tr(
                        "dashboard_residency_due",
                        date=date_text,
                        count=item.get("days_left", 0),
                    )
                )
                detail.setObjectName("MutedText")
                identity.addWidget(name)
                identity.addWidget(detail)
                row_layout.addLayout(identity, 1)

                for label_key, value in (
                    ("dashboard_prorroga_pago", item.get("has_pago")),
                    ("dashboard_prorroga_papers", item.get("papers_started")),
                ):
                    indicator = QLabel(f"{'●' if value else '○'}  {tr(label_key)}")
                    indicator.setObjectName("DashboardProgressIndicator")
                    indicator.setProperty("complete", bool(value))
                    row_layout.addWidget(indicator)

                open_btn = create_button(
                    tr("dashboard_action_open"), "subtle", fixed_height=26
                )
                open_btn.clicked.connect(
                    lambda checked=False, missionary_id=item.get("missionary_id"):
                    self._open_missionary(missionary_id)
                )
                row_layout.addWidget(open_btn)
                layout.addWidget(row)
        else:
            layout.addWidget(
                self._muted_label(tr("dashboard_no_residency_expirations"))
            )
        return card

    def _build_cancelaciones_card(self, data):
        card = SimpleCardWidget()
        card.setObjectName("DashboardCancelacionesCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        card.setLayout(layout)
        title = QLabel(tr("dashboard_cancelaciones"))
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        items = data.get("cancelaciones", [])
        if items:
            for item in items:
                row = QFrame()
                row.setObjectName("DashboardCancelacionesRow")
                row_layout = QBoxLayout(
                    QBoxLayout.TopToBottom
                    if self._current_dashboard_class() == "narrow"
                    else QBoxLayout.LeftToRight
                )
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(8)
                row.setLayout(row_layout)

                identity = QVBoxLayout()
                name = QLabel(item.get("name", ""))
                name.setObjectName("StrongText")
                release = item.get("release_date")
                date_text = release.strftime("%b %d, %Y") if release else ""
                detail = QLabel(
                    tr(
                        "dashboard_cancelacion_due",
                        date=date_text,
                        count=item.get("days_left", 0),
                    )
                )
                detail.setObjectName("MutedText")
                identity.addWidget(name)
                identity.addWidget(detail)
                row_layout.addLayout(identity, 1)

                for label_key, value in (
                    ("dashboard_cancelacion_pago", item.get("has_pago")),
                    (
                        "dashboard_cancelacion_papers_submitted",
                        item.get("papers_submitted"),
                    ),
                ):
                    indicator = QLabel(f"{'●' if value else '○'}  {tr(label_key)}")
                    indicator.setObjectName("DashboardProgressIndicator")
                    indicator.setProperty("complete", bool(value))
                    row_layout.addWidget(indicator)

                open_btn = create_button(
                    tr("dashboard_action_open"), "subtle", fixed_height=26
                )
                open_btn.clicked.connect(
                    lambda checked=False, missionary_id=item.get("missionary_id"):
                    self._open_missionary(missionary_id)
                )
                row_layout.addWidget(open_btn)
                layout.addWidget(row)
        else:
            layout.addWidget(self._muted_label(tr("dashboard_no_cancelaciones")))
        return card

    def _toggle_digest(self):
        self._digest_expanded = not self._digest_expanded
        self._render_dashboard(self._last_dashboard_data or {})

    def _build_exception_cards(self, data):
        self.content_layout.addWidget(SectionHeader(tr("dashboard_exceptions")))
        wrapper = QWidget()
        wrapper.setObjectName("DashboardExceptionsRow")
        direction = (
            QBoxLayout.LeftToRight
            if self._current_dashboard_class() != "narrow"
            else QBoxLayout.TopToBottom
        )
        layout = QBoxLayout(direction)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        wrapper.setLayout(layout)
        layout.addWidget(
            self._make_exception_card(
                len(data.get("expiring", [])),
                tr("dashboard_expiring_soon"),
                "warning",
                self._toggle_expiring,
                self._expiring_expanded,
            ),
            1,
        )
        layout.addWidget(
            self._make_exception_card(
                len(data.get("missing_docs", [])),
                tr("dashboard_missing_required_documents"),
                "danger",
                self._toggle_missing,
                self._missing_expanded,
            ),
            1,
        )
        self.content_layout.addWidget(wrapper)

    def _make_exception_card(self, value, title_text, tone, callback, expanded):
        card = SimpleCardWidget()
        card.setObjectName("DashboardExceptionCard")
        card.setProperty("tone", tone)
        layout = QBoxLayout(
            QBoxLayout.TopToBottom
            if self._current_dashboard_class() == "narrow"
            else QBoxLayout.LeftToRight
        )
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        card.setLayout(layout)
        value_label = QLabel(str(value))
        value_label.setObjectName("DashboardExceptionValue")
        value_label.setProperty("tone", tone)
        title = QLabel(title_text)
        title.setObjectName("StrongText")
        title.setWordWrap(True)
        toggle = create_button(
            tr("dashboard_hide_details") if expanded else tr("dashboard_view_details"),
            "subtle",
            fixed_height=28,
        )
        toggle.clicked.connect(callback)
        layout.addWidget(value_label)
        layout.addWidget(title, 1)
        layout.addWidget(toggle)
        return card

    def _toggle_expiring(self):
        self._expiring_expanded = not self._expiring_expanded
        self._render_dashboard(self._last_dashboard_data or {})

    def _toggle_missing(self):
        self._missing_expanded = not self._missing_expanded
        self._render_dashboard(self._last_dashboard_data or {})

    def _open_calendar(self):
        if self.main_window is not None:
            self.main_window.set_current_key("calendar")

    def _open_office_task(self, task_id, title):
        if self.main_window is None:
            return
        opener = getattr(self.main_window, "open_alert_workspace", None)
        if task_id and callable(opener):
            opener(task_id, return_key="dashboard")
            return
        office_page = getattr(self.main_window, "office_work_page", None)
        if office_page is not None and hasattr(office_page, "focus_task_context"):
            office_page.focus_task_context(task_id=task_id, title=title)
        self.main_window.set_current_key("office_work")

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
        self.request_refresh(force=False)
