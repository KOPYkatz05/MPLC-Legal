from datetime import date, timedelta

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
)

from PySide6.QtCore import Qt

from database.db import SessionLocal

from database.models.missionary import Missionary

from database.models.document import Document

from database.models.stage_history import StageHistory

from utils.constants import WORKFLOW_STAGES

from utils.logger import logger


class StatCard(QFrame):
    def __init__(
        self,
        count,
        title,
        subtitle="",
        color="#3B82F6",
        parent=None,
    ):
        super().__init__(parent)

        self.setStyleSheet(
            "background-color: #FFFFFF;"
            "border: 1px solid #E4E4E7;"
            "border-radius: 10px;"
        )

        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )

        self.setMinimumHeight(110)

        layout = QVBoxLayout()

        layout.setContentsMargins(20, 16, 20, 16)

        layout.setSpacing(2)

        self.setLayout(layout)

        count_label = QLabel(str(count))

        count_label.setStyleSheet(
            f"color: {color};"
            "font-size: 38px;"
            "font-weight: 700;"
        )

        title_label = QLabel(title)

        title_label.setStyleSheet(
            "font-size: 13px;"
            "font-weight: 600;"
            "color: #18181B;"
        )

        layout.addWidget(count_label)

        layout.addWidget(title_label)

        if subtitle:
            sub_label = QLabel(subtitle)

            sub_label.setStyleSheet(
                "font-size: 11px; color: #71717A;"
            )

            layout.addWidget(sub_label)

        layout.addStretch()


class ReportsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("ReportsPage")

        self.main_window = main_window

        self.setup_ui()

        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        # Header
        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(32, 20, 32, 20)

        header.setLayout(header_layout)

        title = QLabel("Reports & Statistics")

        title.setObjectName("PageTitle")

        header_layout.addWidget(title)

        header_layout.addStretch()

        outer.addWidget(header)

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        outer.addWidget(divider)

        # Scroll area
        scroll = QScrollArea()

        scroll.setWidgetResizable(True)

        scroll.setStyleSheet(
            "background-color: #F4F4F5;"
        )

        content = QWidget()

        self.content_layout = QVBoxLayout()

        self.content_layout.setContentsMargins(
            32, 24, 32, 24
        )

        self.content_layout.setSpacing(20)

        self.content_layout.addStretch()

        content.setLayout(self.content_layout)

        scroll.setWidget(content)

        outer.addWidget(scroll, stretch=1)

    def load_data(self):
        try:
            # Clear existing widgets
            for i in range(
                self.content_layout.count() - 1, -1, -1
            ):
                widget = (
                    self.content_layout.itemAt(i)
                    .widget()
                )

                if widget:
                    widget.deleteLater()

                    self.content_layout.removeWidget(
                        widget
                    )

            session = SessionLocal()

            try:
                today = date.today()

                month_start = today.replace(day=1)

                # Active missionaries
                active = (
                    session.query(Missionary)
                    .filter_by(status="ACTIVE")
                    .all()
                )

                total = len(active)

                # Stage counts
                stage_counts = {
                    s: 0 for s in WORKFLOW_STAGES
                }

                for m in active:
                    stage = m.current_stage

                    if stage in stage_counts:
                        stage_counts[stage] += 1

                # Arrivals this month
                arrivals = [
                    m
                    for m in active
                    if m.arrival_date
                    and m.arrival_date >= month_start
                ]

                # Documents uploaded this month
                docs = (
                    session.query(Document)
                    .all()
                )

                recent_docs = [
                    d
                    for d in docs
                    if hasattr(d, "uploaded_at")
                    and d.uploaded_at
                    and d.uploaded_at.date()
                    >= month_start
                ]

                # Stage history — average time per stage
                history = (
                    session.query(StageHistory)
                    .all()
                )

                stage_durations = {}

                for h in history:
                    if h.from_stage and h.created_at:
                        # Simple: track time between stage transitions
                        key = (
                            h.from_stage,
                            h.to_stage,
                        )

                        if key not in stage_durations:
                            stage_durations[key] = []

                # Expiring soon
                expiring = []

                for m in active:
                    for field in [
                        "visa_expiration",
                        "residency_expiration",
                        "prorroga_expiration",
                    ]:
                        val = getattr(m, field, None)

                        if val and (val - today).days <= 30:
                            expiring.append({
                                "name": m.full_name,
                                "field": field,
                                "days": (val - today).days,
                            })

                # Build sections
                self._add_section_header(
                    "Overview"
                )

                row = QHBoxLayout()

                row.setSpacing(16)

                row.addWidget(
                    StatCard(
                        total,
                        "Active Missionaries",
                        color="#3B82F6",
                    )
                )

                row.addWidget(
                    StatCard(
                        len(arrivals),
                        "Arrivals This Month",
                        subtitle=month_start.strftime(
                            "%B %Y"
                        ),
                        color="#059669",
                    )
                )

                row.addWidget(
                    StatCard(
                        len(recent_docs),
                        "Documents This Month",
                        subtitle=month_start.strftime(
                            "%B %Y"
                        ),
                        color="#D97706",
                    )
                )

                row.addWidget(
                    StatCard(
                        len(expiring),
                        "Expiring Soon",
                        subtitle="Within 30 days",
                        color="#DC2626",
                    )
                )

                self._add_row_layout(row)

                # Stage breakdown
                self._add_section_header(
                    "Missionaries by Stage"
                )

                row2 = QHBoxLayout()

                row2.setSpacing(16)

                for stage in WORKFLOW_STAGES:
                    row2.addWidget(
                        StatCard(
                            stage_counts[stage],
                            stage,
                            color="#7C3AED",
                        )
                    )

                self._add_row_layout(row2)

                # Expiring detail
                if expiring:
                    self._add_section_header(
                        "Expiring Documents"
                    )

                    for e in sorted(
                        expiring,
                        key=lambda x: x["days"],
                    ):
                        label = e["field"].replace(
                            "_", " "
                        ).title()

                        row_widget = QFrame()

                        row_widget.setStyleSheet(
                            "background-color: #FFFFFF;"
                            "border: 1px solid #E4E4E7;"
                            "border-radius: 6px;"
                        )

                        row_layout = QHBoxLayout()

                        row_layout.setContentsMargins(
                            16, 10, 16, 10
                        )

                        row_widget.setLayout(row_layout)

                        name_lbl = QLabel(e["name"])

                        name_lbl.setStyleSheet(
                            "font-size: 13px;"
                            "font-weight: 600;"
                        )

                        type_lbl = QLabel(label)

                        type_lbl.setStyleSheet(
                            "font-size: 12px;"
                            "color: #71717A;"
                        )

                        days_text = (
                            "TODAY"
                            if e["days"] == 0
                            else (
                                f"{e['days']} days"
                                if e["days"] > 0
                                else (
                                    f"{abs(e['days'])}"
                                    f" days overdue"
                                )
                            )
                        )

                        days_lbl = QLabel(days_text)

                        days_lbl.setStyleSheet(
                            (
                                "color: #DC2626;"
                                if e["days"] <= 0
                                else "color: #D97706;"
                            )
                            + "font-size: 12px;"
                            "font-weight: 600;"
                        )

                        row_layout.addWidget(name_lbl)

                        row_layout.addWidget(type_lbl)

                        row_layout.addStretch()

                        row_layout.addWidget(days_lbl)

                        self.content_layout.insertWidget(
                            self.content_layout.count()
                            - 1,
                            row_widget,
                        )

            finally:
                session.close()

        except Exception:
            logger.exception(
                "Failed to load reports"
            )

    def _add_section_header(self, text):
        label = QLabel(text)

        label.setStyleSheet(
            "font-size: 16px;"
            "font-weight: 700;"
            "color: #18181B;"
            "padding-top: 8px;"
        )

        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            label,
        )

    def _add_row_layout(self, layout):
        widget = QWidget()

        widget.setLayout(layout)

        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            widget,
        )
