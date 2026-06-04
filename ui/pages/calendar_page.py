from datetime import date, timedelta

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
)

from PySide6.QtCore import Qt

from PySide6.QtGui import QColor, QFont, QPalette

from database.db import SessionLocal

from database.models.missionary import Missionary
from ui.foundation import PageHeader, create_button, create_card, create_scroll_area, divider

from utils.logger import logger


# Appointment date fields on Missionary model
APPOINTMENT_FIELDS = [
    ("interpol_appointment_date", "Interpol", "#7C3AED"),
    ("biometric_appointment_date", "Biometric", "#D97706"),
    ("pickup_appointment_date", "Pickup", "#059669"),
]


class CalendarPage(QWidget):
    def __init__(self, main_window):
        super().__init__()

        self.setObjectName("CalendarPage")

        self.main_window = main_window

        self.setup_ui()

        self.load_data()

    def setup_ui(self):
        outer = QVBoxLayout()

        outer.setContentsMargins(0, 0, 0, 0)

        outer.setSpacing(0)

        self.setLayout(outer)

        self._count_label = QLabel("")

        self._count_label.setObjectName("MutedText")

        header = PageHeader(
            "Appointments Calendar",
            "Upcoming Interpol, biometric, and pickup appointments.",
            [self._count_label],
        )

        outer.addWidget(header)

        outer.addWidget(divider())

        # Scroll area for appointments
        scroll = create_scroll_area()

        scroll.setObjectName("PageSurface")

        content = QWidget()

        self.content_layout = QVBoxLayout()

        self.content_layout.setContentsMargins(
            32, 24, 32, 24
        )

        self.content_layout.setSpacing(16)

        self.content_layout.addStretch()

        content.setLayout(self.content_layout)

        scroll.setWidget(content)

        outer.addWidget(scroll, stretch=1)

    def load_data(self):
        try:
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
                missionaries = (
                    session.query(Missionary)
                    .filter_by(status="ACTIVE")
                    .all()
                )

                today = date.today()

                appointments = []

                for m in missionaries:
                    for field, label, color in (
                        APPOINTMENT_FIELDS
                    ):
                        appt_date = getattr(
                            m, field, None
                        )

                        if appt_date:
                            appointments.append({
                                "missionary": m,
                                "date": appt_date,
                                "type": label,
                                "color": color,
                                "field": field,
                            })

                # Sort by date
                appointments.sort(
                    key=lambda x: x["date"]
                )

                # Group by date
                grouped = {}

                for appt in appointments:
                    d = appt["date"]

                    if d not in grouped:
                        grouped[d] = []

                    grouped[d].append(appt)

                # Sort dates
                sorted_dates = sorted(grouped.keys())

                for d in sorted_dates:
                    appts = grouped[d]

                    day_card = self._make_day_card(
                        d, appts, today
                    )

                    self.content_layout.insertWidget(
                        self.content_layout.count() - 1,
                        day_card,
                    )

                self._count_label.setText(
                    f"{len(appointments)} upcoming"
                    f" appointments"
                )

            finally:
                session.close()

        except Exception:
            logger.exception(
                "Failed to load calendar data"
            )

    def _make_day_card(self, d, appts, today):
        card = create_card()

        card_layout = QVBoxLayout()

        card_layout.setContentsMargins(20, 16, 20, 16)

        card_layout.setSpacing(10)

        card.setLayout(card_layout)

        # Date header
        days_until = (d - today).days

        if days_until < 0:
            days_text = f"({abs(days_until)} days ago)"

        elif days_until == 0:
            days_text = "TODAY"

        else:
            days_text = f"({days_until} days)"

        date_str = d.strftime("%A, %B %d, %Y")

        date_label = QLabel(
            f"{date_str}  {days_text}"
        )

        date_label.setObjectName("PanelTitle")

        card_layout.addWidget(date_label)

        # Appointment rows
        for appt in appts:
            row = QHBoxLayout()

            row.setSpacing(12)

            # Color dot
            dot = QLabel("●")
            dot.setFixedWidth(12)
            dot_palette = dot.palette()
            dot_palette.setColor(
                QPalette.WindowText,
                QColor(appt["color"]),
            )
            dot.setPalette(dot_palette)

            row.addWidget(dot)

            # Type label
            type_label = QLabel(appt["type"])
            type_font = QFont(type_label.font())
            type_font.setPointSize(12)
            type_font.setWeight(QFont.DemiBold)
            type_label.setFont(type_font)
            type_palette = type_label.palette()
            type_palette.setColor(
                QPalette.WindowText,
                QColor(appt["color"]),
            )
            type_label.setPalette(type_palette)

            type_label.setFixedWidth(80)

            row.addWidget(type_label)

            # Name
            name_label = QLabel(
                appt["missionary"].full_name
            )

            name_label.setObjectName("BodyText")

            row.addWidget(name_label)

            row.addStretch()

            # View button
            view_btn = create_button("View", "subtle", fixed_height=24)

            mid = appt["missionary"].id

            view_btn.clicked.connect(
                lambda _=None, m_id=mid:
                self._open_missionary(m_id)
            )

            row.addWidget(view_btn)

            card_layout.addLayout(row)

        return card

    def _open_missionary(self, missionary_id):
        try:
            from ui.pages.missionary_detail_page import (
                MissionaryDetailPage,
            )

            detail = (
                self.main_window.detail_page
            )

            from database.db import SessionLocal

            from database.models.missionary import (
                Missionary as M,
            )

            session = SessionLocal()

            try:
                m = (
                    session.query(M)
                    .filter_by(id=missionary_id)
                    .first()
                )

                if m:
                    detail.load_missionary(m)

                    self.main_window.stack.setCurrentIndex(
                        2
                    )

                    self.main_window.sidebar.setCurrentRow(
                        1
                    )

            finally:
                session.close()

        except Exception:
            logger.exception(
                "Failed to open missionary detail"
            )
