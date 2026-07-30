from collections import defaultdict
from datetime import date
from datetime import datetime
import time

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QProgressBar,
    QSizePolicy,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette

from services.reports_data_service import ReportsDataService
from services.settings_service import SettingsService
from utils.i18n import get_i18n

from ui.foundation import StatCard, create_card, create_scroll_area
from ui.foundation.background_loader import LatestRequestLoader
from ui.widgets.animated_tab_strip import AnimatedTabStrip

from utils.constants import (
    DOCUMENTS,
    WORKFLOW_STAGES,
    required_documents_for_missionary,
)

from utils.logger import logger


class ReportsPage(QWidget):
    CACHE_TTL_SECONDS = 90.0

    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("ReportsPage")

        self.main_window = main_window

        self.settings_service = getattr(main_window, "settings_service", None)
        if self.settings_service is None:
            active_language = get_i18n().get_language()
            self.settings_service = SettingsService()
            get_i18n().set_language(active_language)

        self._selected_tab = getattr(
            self.settings_service,
            "get_analytics_default_view",
            lambda: "general",
        )()

        self._tab_buttons = {}

        self._analytics_snapshot = None

        self._last_refresh_at = 0.0

        self._refresh_loader = LatestRequestLoader(parent=self)

        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        outer.addWidget(self._build_top_bar())

        # Scroll area
        scroll = create_scroll_area(single_direction=True)

        scroll.setObjectName("ReportsWorkspaceScroll")

        content = QWidget()
        content.setObjectName("ReportsWorkspace")
        content.setAttribute(Qt.WA_StyledBackground, True)

        self.content_layout = QVBoxLayout()

        self.content_layout.setContentsMargins(
            12, 14, 24, 24
        )

        self.content_layout.setSpacing(14)

        self.content_layout.addStretch()

        content.setLayout(self.content_layout)

        scroll.setWidget(content)

        outer.addWidget(scroll, stretch=1)

    def _build_top_bar(self):
        frame = QFrame()
        frame.setObjectName("ReportsTopBar")
        frame.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 16, 12)
        layout.setSpacing(4)
        frame.setLayout(layout)

        title = QLabel("Analytics")
        title.setObjectName("ReportsTitle")
        subtitle = QLabel(
            "See how the legal process is moving and where work needs attention."
        )
        subtitle.setObjectName("ReportsSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._build_tab_strip())
        return frame

    def _build_tab_strip(self):
        strip = AnimatedTabStrip()

        for key, label in (
            ("general", "General"),
            ("process", "Process"),
            ("documents", "Documents"),
        ):
            strip.add_tab(key, label, self._set_tab)
        self._tab_buttons = strip.buttons
        self._sync_tab_buttons()
        return strip

    def _add_section_header(self, text):
        label = QLabel(text)

        label.setObjectName("ReportSectionTitle")

        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            label,
        )

    def _add_row_layout(self, layout):
        widget = QWidget()
        widget.setObjectName("ReportMetricRow")

        widget.setLayout(layout)

        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            widget,
        )

    def _clear_content(self):
        for i in range(
            self.content_layout.count() - 1, -1, -1
        ):
            item = self.content_layout.itemAt(i)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                self.content_layout.removeWidget(widget)

    def _add_stage_rows(self, stage_counts, total):
        if total <= 0:
            self._add_empty_state("No active missionaries to analyze yet.")
            return

        rows = sorted(
            stage_counts.items(),
            key=lambda item: (-item[1], WORKFLOW_STAGES.index(item[0])),
        )

        for stage, count in rows:
            percent = (count / total) * 100 if total else 0
            self._add_detail_row(
                stage,
                f"{count} missionaries",
                f"{percent:.0f}% of active missionaries",
                tone="#7A6EEC" if count else "#71717A",
            )

    def _add_timing_rows(self, timing_rows):
        if not timing_rows:
            self._add_empty_state(
                "Average stage timing will appear after more appointment dates are recorded."
            )
            return

        for row in timing_rows:
            self._add_detail_row(
                row["label"],
                f"Average: {row['average_days']:.1f} days",
                f"Samples: {row['samples']}",
                tone="#0EA5AC",
            )

    def _add_expiring_rows(self, expiring):
        if not expiring:
            self._add_empty_state("No expirations in the next 30 days.")
            return

        for item in expiring:
            self._add_detail_row(
                item["name"],
                item["label"],
                self._timing_text(item["days"]),
                tone=(
                    "#DC2626"
                    if item["days"] <= 0
                    else "#D97706"
                ),
            )

    def _add_recent_progress(
        self,
        recent_docs,
        stage_changes,
        arrivals,
        completed_tasks,
        month_label,
    ):
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(
            StatCard(
                len(recent_docs),
                "Documents Uploaded",
                subtitle=month_label,
                color="#D97706",
            )
        )
        row.addWidget(
            StatCard(
                len(stage_changes),
                "Stage Changes",
                subtitle=month_label,
                color="#7A6EEC",
            )
        )
        row.addWidget(
            StatCard(
                len(arrivals),
                "Arrivals",
                subtitle=month_label,
                color="#059669",
            )
        )
        row.addWidget(
            StatCard(
                len(completed_tasks),
                "Tasks Completed",
                subtitle=month_label,
                color="#0EA5AC",
            )
        )
        self._add_row_layout(row)

    def _add_detail_row(self, title, meta, trailing, tone="#0EA5AC"):
        row_widget = create_card(object_name="ReportAlertRow")
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(12)
        row_widget.setLayout(row_layout)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("StrongText")
        title_lbl.setWordWrap(True)

        meta_lbl = QLabel(meta)
        meta_lbl.setObjectName("ReportMeta")
        meta_lbl.setWordWrap(True)

        text_stack.addWidget(title_lbl)
        text_stack.addWidget(meta_lbl)

        trailing_lbl = QLabel(trailing)
        trailing_lbl.setObjectName("ReportValue")
        trailing_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        trailing_lbl.setWordWrap(True)

        trailing_font = QFont(trailing_lbl.font())
        trailing_font.setPointSize(12)
        trailing_font.setWeight(QFont.DemiBold)
        trailing_lbl.setFont(trailing_font)
        trailing_palette = trailing_lbl.palette()
        trailing_palette.setColor(
            QPalette.WindowText,
            QColor(tone),
        )
        trailing_lbl.setPalette(trailing_palette)

        row_layout.addLayout(text_stack, stretch=1)
        row_layout.addWidget(trailing_lbl)

        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            row_widget,
        )

    def _add_empty_state(self, text):
        card = create_card(object_name="ReportEmptyState")
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        card.setLayout(layout)

        label = QLabel(text)
        label.setObjectName("ReportMeta")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            card,
        )

    @classmethod
    def _expiration_items(cls, missionaries, today):
        fields = (
            ("visa_expiration", "Visa"),
            ("residency_expiration", "Residency"),
            ("prorroga_expiration", "Prorroga"),
            ("passport_expiration", "Passport"),
        )
        items = []
        for missionary in missionaries:
            if getattr(missionary, "status", "ACTIVE") != "ACTIVE":
                continue
            if (
                (getattr(missionary, "dynamics_status", "In-field") or "In-field")
                != "In-field"
                or (
                    getattr(missionary, "tracking_profile", "LEGAL") or "LEGAL"
                ) == "PERUVIAN_DNI"
            ):
                continue
            for field, label in fields:
                if (
                    field == "visa_expiration"
                    and any(
                        getattr(missionary, name, None)
                        for name in (
                            "residency_expiration",
                            "prorroga_expiration",
                            "carnet_issue_date",
                        )
                    )
                ):
                    continue
                value = cls._as_date(getattr(missionary, field, None))
                if value is None:
                    continue
                days = (value - today).days
                if days <= 30:
                    items.append({
                        "name": getattr(missionary, "full_name", ""),
                        "label": label,
                        "days": days,
                        "date": value,
                    })
        return sorted(items, key=lambda item: (item["days"], item["name"]))

    @classmethod
    def _average_milestone_timing(cls, missionaries):
        pairs = (
            (
                "INTERPOL",
                "Arrival -> Interpol appointment",
                "arrival_date",
                "interpol_appointment_date",
            ),
            (
                "CARNET DE EXTRANJERIA",
                "Interpol appointment -> Biometric appointment",
                "interpol_appointment_date",
                "biometric_appointment_date",
            ),
            (
                "CARNET DE EXTRANJERIA",
                "Biometric appointment -> Pickup appointment",
                "biometric_appointment_date",
                "pickup_appointment_date",
            ),
            (
                "CARNET DE EXTRANJERIA",
                "Pickup appointment -> Carnet issue",
                "pickup_appointment_date",
                "carnet_issue_date",
            ),
            (
                "CANCELACION",
                "Carnet issue -> Cancelacion",
                "carnet_issue_date",
                "cancelacion_date",
            ),
        )
        durations = defaultdict(list)

        for missionary in missionaries:
            if (
                (getattr(missionary, "dynamics_status", "In-field") or "In-field")
                != "In-field"
                or (
                    getattr(missionary, "tracking_profile", "LEGAL") or "LEGAL"
                ) == "PERUVIAN_DNI"
            ):
                continue
            for key, label, start_field, end_field in pairs:
                start = cls._as_date(getattr(missionary, start_field, None))
                end = cls._as_date(getattr(missionary, end_field, None))
                if start is None or end is None:
                    continue

                days = (end - start).days
                if days < 0:
                    continue

                durations[(key, label)].append(days)

        rows = []
        for (key, label), values in durations.items():
            if not values:
                continue
            rows.append({
                "stage": key,
                "label": label,
                "average_days": sum(values) / len(values),
                "samples": len(values),
            })

        return sorted(
            rows,
            key=lambda row: (
                WORKFLOW_STAGES.index(row["stage"])
                if row["stage"] in WORKFLOW_STAGES
                else len(WORKFLOW_STAGES),
                row["label"],
            ),
        )

    @staticmethod
    def _as_date(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if hasattr(value, "date"):
            try:
                return value.date()
            except Exception:
                return None
        return None

    @staticmethod
    def _timing_text(days):
        if days == 0:
            return "TODAY"
        if days < 0:
            return f"{abs(days)} days overdue"
        return f"{days} days"

    def request_refresh(self, force=False):
        now = time.monotonic()
        cache_is_fresh = (
            self._analytics_snapshot is not None
            and now - self._last_refresh_at < self.CACHE_TTL_SECONDS
        )
        if cache_is_fresh and not force:
            return False

        if self._analytics_snapshot is None and not self._refresh_loader.busy:
            self._clear_content()
            self._add_empty_state("Loading analytics…")

        self._refresh_loader.request(
            self._build_snapshot,
            on_success=self._apply_snapshot,
            on_error=self._report_refresh_failed,
        )
        return True

    def load_data(self):
        """Compatibility entry point for callers that need a forced refresh."""
        return self.request_refresh(force=True)

    def _apply_snapshot(self, snapshot):
        self._analytics_snapshot = snapshot
        self._last_refresh_at = time.monotonic()
        self._render_selected_tab()

    def _report_refresh_failed(self, error):
        logger.error(
            "Failed to load reports",
            exc_info=(type(error), error, error.__traceback__),
        )
        if self._analytics_snapshot is None:
            self._clear_content()
            self._add_empty_state(
                "Analytics could not be refreshed. Try this page again."
            )

    def _set_tab(self, tab_key):
        if tab_key not in {"general", "process", "documents"}:
            return

        self._selected_tab = tab_key
        self._sync_tab_buttons()
        self._render_selected_tab()

    def _sync_tab_buttons(self):
        tab_strip = next(
            (button.parentWidget() for button in self._tab_buttons.values()), None
        )
        if isinstance(tab_strip, AnimatedTabStrip):
            tab_strip.set_active(self._selected_tab, animate=False)
            return
        for key, button in getattr(self, "_tab_buttons", {}).items():
            button.setChecked(key == self._selected_tab)

    def _build_snapshot(self):
        data = ReportsDataService().get_data()
        try:
            today = date.today()
            month_start = today.replace(day=1)
            month_label = month_start.strftime("%B %Y")

            active = data["missionaries"]
            docs = data["documents"]
            history = data["stage_history"]
            tasks = data["completed_tasks"]

            stage_counts = {
                stage: 0
                for stage in WORKFLOW_STAGES
            }
            for missionary in active:
                stage = missionary.current_stage
                if stage in stage_counts:
                    stage_counts[stage] += 1

            arrivals = [
                missionary
                for missionary in active
                if self._as_date(getattr(missionary, "arrival_date", None))
                and self._as_date(getattr(missionary, "arrival_date", None))
                >= month_start
            ]
            recent_docs = [
                document
                for document in docs
                if self._as_date(getattr(document, "uploaded_at", None))
                and self._as_date(getattr(document, "uploaded_at", None))
                >= month_start
            ]
            recent_docs = sorted(
                recent_docs,
                key=lambda document: (
                    self._as_date(getattr(document, "uploaded_at", None))
                    or date.min
                ),
                reverse=True,
            )
            stage_changes = [
                item
                for item in history
                if self._as_date(getattr(item, "created_at", None))
                and self._as_date(getattr(item, "created_at", None))
                >= month_start
            ]
            completed_tasks = [
                task
                for task in tasks
                if self._as_date(getattr(task, "completed_at", None))
                and self._as_date(getattr(task, "completed_at", None))
                >= month_start
            ]

            expiring = self._expiration_items(active, today)
            coverage = self._document_coverage(active, docs)
            missionary_names = {
                getattr(missionary, "id", None): getattr(
                    missionary,
                    "full_name",
                    "",
                )
                for missionary in active
            }

            return {
                "today": today,
                "month_start": month_start,
                "month_label": month_label,
                "active": active,
                "total": len(active),
                "documents": docs,
                "recent_docs": recent_docs,
                "verified_docs": [
                    document
                    for document in docs
                    if getattr(document, "verified", False)
                ],
                "stage_counts": stage_counts,
                "arrivals": arrivals,
                "stage_changes": stage_changes,
                "completed_tasks": completed_tasks,
                "expiring": expiring,
                "timing_rows": self._average_milestone_timing(active),
                "coverage": coverage,
                "missionary_names": missionary_names,
                "missing_required": sum(
                    max(row["required"] - row["uploaded"], 0)
                    for row in coverage
                ),
            }
        finally:
            pass


    def _render_selected_tab(self):
        self._clear_content()
        snapshot = self._analytics_snapshot
        if snapshot is None:
            return

        if self._selected_tab == "process":
            self._render_process_tab(snapshot)
        elif self._selected_tab == "documents":
            self._render_documents_tab(snapshot)
        else:
            self._render_general_tab(snapshot)

    def _render_general_tab(self, snapshot):
        self._add_section_header("Overview")
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(
            StatCard(
                snapshot["total"],
                "Active Missionaries",
                subtitle="Currently tracked",
                color="#0EA5AC",
            )
        )
        row.addWidget(
            StatCard(
                len(snapshot["arrivals"]),
                "Arrivals This Month",
                subtitle=snapshot["month_label"],
                color="#059669",
            )
        )
        row.addWidget(
            StatCard(
                len(snapshot["recent_docs"]),
                "Documents This Month",
                subtitle=snapshot["month_label"],
                color="#D97706",
            )
        )
        row.addWidget(
            StatCard(
                len(snapshot["expiring"]),
                "Expiring Soon",
                subtitle="Within 30 days",
                color="#DC2626",
            )
        )
        self._add_row_layout(row)

        self._add_section_header("This Month")
        self._add_recent_progress(
            recent_docs=snapshot["recent_docs"],
            stage_changes=snapshot["stage_changes"],
            arrivals=snapshot["arrivals"],
            completed_tasks=snapshot["completed_tasks"],
            month_label=snapshot["month_label"],
        )

        self._add_section_header("Quick Summary")
        for summary in self._general_summary(snapshot):
            self._add_detail_row(
                summary["title"],
                summary["meta"],
                summary["value"],
                tone=summary["tone"],
            )

    def _render_process_tab(self, snapshot):
        self._add_section_header("Process Health")
        busiest = self._busiest_stage(snapshot["stage_counts"])
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(
            StatCard(
                snapshot["total"],
                "Active Missionaries",
                subtitle="Currently tracked",
                color="#0EA5AC",
            )
        )
        row.addWidget(
            StatCard(
                busiest["count"],
                "Longest Bottleneck",
                subtitle=busiest["stage"],
                color="#D97706" if busiest["count"] else "#71717A",
            )
        )
        row.addWidget(
            StatCard(
                len(snapshot["stage_changes"]),
                "Stage Changes This Month",
                subtitle=snapshot["month_label"],
                color="#7A6EEC",
            )
        )
        row.addWidget(
            StatCard(
                self._average_for_label(
                    snapshot["timing_rows"],
                    "Arrival -> Interpol appointment",
                ),
                "Average Interpol Wait",
                subtitle="Appointment dates only",
                color="#059669",
            )
        )
        self._add_row_layout(row)

        self._add_section_header("Missionaries by Stage")
        self._add_stage_progress_rows(
            snapshot["stage_counts"],
            snapshot["total"],
        )

        self._add_section_header("Average Stage Timing")
        self._add_timing_rows(snapshot["timing_rows"])

        self._add_section_header("Stages Needing Attention")
        self._add_stage_rows(snapshot["stage_counts"], snapshot["total"])

    def _render_documents_tab(self, snapshot):
        self._add_section_header("Document Workload")
        coverage_percent = self._coverage_percent(snapshot["coverage"])
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(
            StatCard(
                len(snapshot["recent_docs"]),
                "Uploaded This Month",
                subtitle=snapshot["month_label"],
                color="#D97706",
            )
        )
        row.addWidget(
            StatCard(
                snapshot["missing_required"],
                "Missing Required",
                subtitle="Across active missionaries",
                color="#DC2626"
                if snapshot["missing_required"]
                else "#059669",
            )
        )
        row.addWidget(
            StatCard(
                len(snapshot["expiring"]),
                "Expiring in 30 Days",
                subtitle="Includes overdue",
                color="#DC2626"
                if snapshot["expiring"]
                else "#059669",
            )
        )
        row.addWidget(
            StatCard(
                len(snapshot["verified_docs"]),
                "Verified Documents",
                subtitle=f"{coverage_percent}% coverage",
                color="#0EA5AC",
            )
        )
        self._add_row_layout(row)

        self._add_section_header("Document Coverage")
        self._add_document_coverage_rows(snapshot["coverage"])

        self._add_section_header("Upcoming Expirations")
        self._add_expiring_rows(snapshot["expiring"])

        self._add_section_header("Recent Uploads")
        self._add_recent_upload_rows(
            snapshot["recent_docs"],
            snapshot["missionary_names"],
        )

    def _add_stage_progress_rows(self, stage_counts, total):
        if total <= 0:
            self._add_empty_state("No active missionaries to analyze yet.")
            return

        for stage in WORKFLOW_STAGES:
            count = stage_counts.get(stage, 0)
            percent = int(round((count / total) * 100)) if total else 0
            self._add_progress_row(
                stage,
                f"{count} missionaries",
                percent,
                f"{percent}% of active missionaries",
            )

    def _add_document_coverage_rows(self, coverage):
        if not coverage:
            self._add_empty_state("Document coverage will appear after missionaries are added.")
            return

        for row in coverage:
            required = row["required"]
            uploaded = row["uploaded"]
            percent = int(round((uploaded / required) * 100)) if required else 0
            self._add_progress_row(
                row["label"],
                f"{uploaded}/{required} uploaded",
                percent,
                f"{percent}% complete",
            )

    def _add_recent_upload_rows(self, recent_docs, missionary_names):
        if not recent_docs:
            self._add_empty_state("No documents uploaded this month.")
            return

        for document in recent_docs[:8]:
            uploaded = self._as_date(getattr(document, "uploaded_at", None))
            label = self._document_label(
                getattr(document, "document_type", "")
            )
            status = (
                "Verified"
                if getattr(document, "verified", False)
                else "Uploaded"
            )
            missionary_name = missionary_names.get(
                getattr(document, "missionary_id", None),
                "Missionary not active",
            )
            self._add_detail_row(
                label,
                (
                    f"{missionary_name} - {uploaded.strftime('%b %d, %Y')}"
                    if uploaded
                    else f"{missionary_name} - upload date unknown"
                ),
                status,
                tone="#059669"
                if getattr(document, "verified", False)
                else "#D97706",
            )

    def _add_progress_row(self, title, meta, percent, trailing):
        row_widget = create_card(object_name="ReportProgressRow")
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        row_widget.setLayout(layout)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(5)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("StrongText")
        title_lbl.setWordWrap(True)

        meta_lbl = QLabel(meta)
        meta_lbl.setObjectName("ReportMeta")

        progress = QProgressBar()
        progress.setObjectName("ReportProgressBar")
        progress.setRange(0, 100)
        progress.setValue(max(0, min(percent, 100)))
        progress.setTextVisible(False)
        progress.setFixedHeight(6)

        text_stack.addWidget(title_lbl)
        text_stack.addWidget(meta_lbl)
        text_stack.addWidget(progress)

        trailing_lbl = QLabel(trailing)
        trailing_lbl.setObjectName("ReportValue")
        trailing_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addLayout(text_stack, stretch=1)
        layout.addWidget(trailing_lbl)

        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            row_widget,
        )

    @staticmethod
    def _general_summary(snapshot):
        total = snapshot["total"]
        expiring = len(snapshot["expiring"])
        stage_changes = len(snapshot["stage_changes"])
        arrivals = len(snapshot["arrivals"])

        if total:
            process_meta = f"{total} active missionaries are being tracked."
        else:
            process_meta = "No active missionaries are currently being tracked."

        if expiring:
            document_meta = f"{expiring} document date(s) need attention soon."
            document_value = "Review"
            document_tone = "#DC2626"
        else:
            document_meta = "No expirations are due in the next 30 days."
            document_value = "Clear"
            document_tone = "#059669"

        return [
            {
                "title": "Process movement",
                "meta": (
                    f"{stage_changes} stage change(s) recorded this month."
                ),
                "value": snapshot["month_label"],
                "tone": "#7A6EEC",
            },
            {
                "title": "Missionary intake",
                "meta": f"{arrivals} arrival(s) recorded this month. {process_meta}",
                "value": "Active",
                "tone": "#0EA5AC",
            },
            {
                "title": "Document watch",
                "meta": document_meta,
                "value": document_value,
                "tone": document_tone,
            },
        ]

    @staticmethod
    def _busiest_stage(stage_counts):
        if not stage_counts:
            return {"stage": "No active stage", "count": 0}

        stage, count = max(
            stage_counts.items(),
            key=lambda item: (
                item[1],
                -WORKFLOW_STAGES.index(item[0])
                if item[0] in WORKFLOW_STAGES
                else 0,
            ),
        )
        return {
            "stage": stage if count else "No active stage",
            "count": count,
        }

    @staticmethod
    def _average_for_label(timing_rows, label):
        for row in timing_rows:
            if row.get("label") == label:
                return f"{row['average_days']:.1f}d"
        return "N/A"

    @classmethod
    def _document_coverage(cls, missionaries, documents):
        uploaded_by_missionary = defaultdict(set)
        for document in documents:
            if getattr(document, "status", "ACTIVE") != "ACTIVE":
                continue
            uploaded_by_missionary[getattr(document, "missionary_id", None)].add(
                getattr(document, "document_type", None)
            )

        groups = [
            ("General Required", lambda key, config: config.get("stage") is None and config.get("required")),
            *[
                (
                    stage,
                    lambda key, config, stage_name=stage: config.get("stage") == stage
                    and config.get("required"),
                )
                for stage in WORKFLOW_STAGES
            ],
        ]

        rows = []
        for label, predicate in groups:
            required = 0
            uploaded = 0
            for missionary in missionaries:
                if label in WORKFLOW_STAGES:
                    keys = required_documents_for_missionary(label, missionary)
                else:
                    keys = [
                        key
                        for key, config in DOCUMENTS.items()
                        if predicate(key, config)
                    ]
                required += len(keys)
                uploaded += sum(
                    1
                    for key in keys
                    if key in uploaded_by_missionary.get(
                        getattr(missionary, "id", None),
                        set(),
                    )
                )

            if required or uploaded:
                rows.append({
                    "label": label,
                    "required": required,
                    "uploaded": uploaded,
                })

        return rows

    @staticmethod
    def _coverage_percent(coverage):
        required = sum(row["required"] for row in coverage)
        uploaded = sum(row["uploaded"] for row in coverage)
        if not required:
            return 0
        return int(round((uploaded / required) * 100))

    @staticmethod
    def _document_label(document_type):
        config = DOCUMENTS.get(document_type or "")
        if config:
            return config.get("label") or document_type
        return (document_type or "Document").replace("_", " ").title()
