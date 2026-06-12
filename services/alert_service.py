from datetime import date, timedelta

from database.db import SessionLocal

from database.models.missionary import Missionary

from utils.logger import logger


class AlertService:

    EXPIRATION_FIELDS = [
        ("visa_expiration", "Visa"),
        ("residency_expiration", "Residency (Carnet)"),
        ("passport_expiration", "Passport"),
    ]

    def get_expiring_soon(
        self,
        within_days=30,
    ):
        session = SessionLocal()

        alerts = []

        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )

            today = date.today()

            cutoff = today + timedelta(
                days=within_days
            )

            for m in missionaries:
                for field, label in (
                    self.EXPIRATION_FIELDS
                ):
                    exp_date = getattr(
                        m, field, None
                    )

                    if (
                        exp_date
                        and today <= exp_date <= cutoff
                    ):
                        days_remaining = (
                            exp_date - today
                        ).days

                        alerts.append({
                            "missionary_name": (
                                m.full_name
                            ),
                            "missionary_id": m.id,
                            "field_label": label,
                            "date": exp_date,
                            "days_remaining": (
                                days_remaining
                            ),
                            "overdue": False,
                        })

            alerts.sort(
                key=lambda x: x["days_remaining"]
            )

            return alerts

        except Exception:
            logger.exception(
                "Failed to get expiring documents"
            )

            return []

        finally:
            session.close()

    def get_overdue(self):
        session = SessionLocal()

        overdue = []

        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )

            today = date.today()

            for m in missionaries:
                for field, label in (
                    self.EXPIRATION_FIELDS
                ):
                    exp_date = getattr(
                        m, field, None
                    )

                    if exp_date and exp_date < today:
                        days_overdue = (
                            today - exp_date
                        ).days

                        overdue.append({
                            "missionary_name": (
                                m.full_name
                            ),
                            "missionary_id": m.id,
                            "field_label": label,
                            "date": exp_date,
                            "days_remaining": (
                                -days_overdue
                            ),
                            "overdue": True,
                        })

            overdue.sort(
                key=lambda x: x["days_remaining"]
            )

            return overdue

        except Exception:
            logger.exception(
                "Failed to get overdue documents"
            )

            return []

        finally:
            session.close()

    def get_all_alerts(self, within_days=30):
        overdue = self.get_overdue()

        expiring = self.get_expiring_soon(
            within_days=within_days
        )

        return overdue + expiring
