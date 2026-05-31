from datetime import date, timedelta

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QPushButton,
    QSizePolicy,
)

from PySide6.QtCore import Qt

from PySide6.QtGui import QColor

from database.db import SessionLocal

from database.models.missionary import Missionary

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

        # Header
        header = QFrame()

        header.setObjectName("PageHeader")

        header_layout = QHBoxLayout()

        header_layout.setContentsMargins(32, 20, 32, 20)

        header.setLayout(header_layout)

        title = QLabel("Appointments Calendar")

        title.setObjectName("PageTitle")

        header_layout.addWidget(title)

        header_layout.addStretch()

        self._count_label = QLabel("")

        self._count_label.setStyleSheet(
            "font-size: 13px; color: #71717A;"
        )

        header_layout.addWidget(self._count_label)

        outer.addWidget(header)

        divider = QFrame()

        divider.setObjectName("HeaderDivider")

        divider.setFixedHeight(1)

        outer.addWidget(divider)

        # Scroll area for appointments
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
        card = QFrame()

        card.setStyleSheet(
            "background-color: #FFFFFF;"
            "border: 1px solid #E4E4E7;"
            "border-radius: 10px;"
        )

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

        date_label.setStyleSheet(
            "font-size: 14px; font-weight: 700;"
            "color: #18181B;"
        )

        card_layout.addWidget(date_label)

        # Appointment rows
        for appt in appts:
            row = QHBoxLayout()

            row.setSpacing(12)

            # Color dot
            dot = QLabel("")

            dot.setFixedSize(10, 10)

            dot.setStyleSheet(
                f"background-color: {appt['color']};"
                "border-radius: 5px;"
            )

            row.addWidget(dot)

            # Type label
            type_label = QLabel(appt["type"])

            type_label.setStyleSheet(
                f"color: {appt['color']};"
                "font-size: 12px;"
                "font-weight: 600;"
            )

            type_label.setFixedWidth(80)

            row.addWidget(type_label)

            # Name
            name_label = QLabel(
                appt["missionary"].full_name
            )

            name_label.setStyleSheet(
                "font-size: 13px; color: #18181B;"
            )

            row.addWidget(name_label)

            row.addStretch()

            # View button
            view_btn = QPushButton("View")

            view_btn.setFixedHeight(24)

            view_btn.setStyleSheet(
                "QPushButton {"
                "background-color: #F4F4F5;"
                "color: #18181B;"
                "border: 1px solid #E4E4E7;"
                "border-radius: 4px;"
                "padding: 2px 10px;"
                "font-size: 11px;"
                "}"
                "QPushButton:hover {"
                "background-color: #E4E4E7;"
                "}"
            )

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
