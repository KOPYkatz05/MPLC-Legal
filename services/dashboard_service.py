from datetime import date

from database.db import SessionLocal

from database.models.missionary import Missionary

from database.models.appointment import APPOINTMENT_STATUS_SCHEDULED, Appointment

from database.models.document import Document

from database.models.secretary_work import SecretaryTask

from utils.constants import (
    WORKFLOW_STAGES,
    DOCUMENTS,
    required_documents_for_missionary,
)

from services.expiration_rules import should_track_expiration_field

from utils.logger import logger


EXPIRY_FIELDS = [
    ("visa_expiration", "Visa Expiration"),
    ("residency_expiration", "Residency Expiration"),
    ("passport_expiration", "Passport Expiration"),
]

EXPIRY_WINDOW_DAYS = 60
ATTENTION_WINDOW_DAYS = 7
VISIBLE_TASK_STATUSES = ("OPEN", "WAITING")


def _severity_for_days(days_left):
    if days_left < 0:
        return "critical"
    if days_left == 0:
        return "warning"
    return "info"


def _attention_sort_key(item):
    severity_rank = {
        "critical": 0,
        "warning": 1,
        "info": 2,
    }
    return (
        severity_rank.get(item.get("severity"), 9),
        item.get("days", 9999),
        item.get("title", ""),
    )


class DashboardService:

    def get_summary(self):
        session = SessionLocal()

        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )

            total = len(missionaries)

            # ======================================
            # Stage counts
            # ======================================

            stage_counts = {
                stage: 0
                for stage in WORKFLOW_STAGES
            }

            for missionary in missionaries:
                stage = missionary.current_stage

                if stage in stage_counts:
                    stage_counts[stage] += 1

            # ======================================
            # Expiring documents
            # ======================================

            today = date.today()

            expiring = []
            attention_items = []

            for missionary in missionaries:
                for field, label in EXPIRY_FIELDS:
                    if not should_track_expiration_field(
                        missionary,
                        field,
                    ):
                        continue

                    val = getattr(
                        missionary,
                        field,
                        None,
                    )

                    if val is None:
                        continue

                    days_left = (val - today).days

                    if days_left <= EXPIRY_WINDOW_DAYS:
                        expiring.append({
                            "missionary_id": missionary.id,
                            "name": missionary.full_name,
                            "field_label": label,
                            "date": val,
                            "days_left": days_left,
                        })

                    if days_left <= ATTENTION_WINDOW_DAYS:
                        attention_items.append({
                            "type": "document_expiration",
                            "severity": _severity_for_days(days_left),
                            "title": f"{label} needs attention",
                            "detail": self._document_expiration_detail(
                                missionary.full_name,
                                val,
                                days_left,
                            ),
                            "missionary_id": missionary.id,
                            "target": "missionary",
                            "days": days_left,
                        })

            expiring.sort(
                key=lambda x: x["days_left"]
            )

            # ======================================
            # Missing required documents
            # ======================================

            all_docs = (
                session.query(Document)
                .filter_by(status="ACTIVE")
                .all()
            )

            uploaded_by_missionary = {}

            for doc in all_docs:
                uploaded_by_missionary.setdefault(
                    doc.missionary_id,
                    set(),
                ).add(doc.document_type)

            missing_docs = []

            for missionary in missionaries:
                uploaded = uploaded_by_missionary.get(
                    missionary.id,
                    set(),
                )

                # Only check CURRENT stage
                stage = missionary.current_stage

                required = required_documents_for_missionary(
                    stage,
                    missionary,
                )

                missionary_missing = []

                for doc_type in required:
                    if doc_type not in uploaded:
                        label = (
                            DOCUMENTS
                            .get(doc_type, {})
                            .get("label", doc_type)
                        )

                        missionary_missing.append({
                            "stage": stage,
                            "label": label,
                        })

                        attention_items.append({
                            "type": "missing_document",
                            "severity": "warning",
                            "title": f"Missing {label}",
                            "detail": (
                                f"{missionary.full_name} needs this "
                                f"for {stage}."
                            ),
                            "missionary_id": missionary.id,
                            "target": "missionary",
                            "days": 0,
                        })

                if missionary_missing:
                    missing_docs.append({
                        "missionary_id": missionary.id,
                        "name": missionary.full_name,
                        "missing": missionary_missing,
                    })

            attention_items.extend(
                self._appointment_attention_items(session, today)
            )
            attention_items.extend(
                self._task_attention_items(session, today)
            )
            attention_items.sort(key=_attention_sort_key)

            return {
                "total": total,
                "stage_counts": stage_counts,
                "expiring": expiring,
                "missing_docs": missing_docs,
                "attention_items": attention_items,
            }

        except Exception:
            logger.exception(
                "Failed to load dashboard data"
            )

            return {
                "total": 0,
                "stage_counts": {
                    s: 0 for s in WORKFLOW_STAGES
                },
                "expiring": [],
                "missing_docs": [],
                "attention_items": [],
            }

        finally:
            session.close()

    def _appointment_attention_items(self, session, today):
        rows = (
            session.query(Appointment, Missionary)
            .join(Missionary, Appointment.missionary_id == Missionary.id)
            .filter(
                Appointment.status == APPOINTMENT_STATUS_SCHEDULED,
                Appointment.scheduled_date <= today,
                Missionary.status == "ACTIVE",
            )
            .all()
        )

        items = []
        for appointment, missionary in rows:
            days = (appointment.scheduled_date - today).days
            items.append({
                "type": "appointment_due",
                "severity": _severity_for_days(days),
                "title": f"{appointment.appointment_type} appointment",
                "detail": self._appointment_detail(
                    missionary.full_name,
                    appointment.scheduled_date,
                    days,
                ),
                "appointment_id": appointment.id,
                "missionary_id": missionary.id,
                "target": "missionary",
                "days": days,
            })
        return items

    def _task_attention_items(self, session, today):
        tasks = (
            session.query(SecretaryTask)
            .filter(
                SecretaryTask.status.in_(VISIBLE_TASK_STATUSES),
                SecretaryTask.due_date.isnot(None),
                SecretaryTask.due_date <= today,
            )
            .all()
        )

        items = []
        for task in tasks:
            days = (task.due_date - today).days
            items.append({
                "type": "secretary_task",
                "severity": _severity_for_days(days),
                "title": task.title,
                "detail": self._task_detail(task, days),
                "missionary_id": task.missionary_id,
                "target": (
                    "missionary"
                    if task.missionary_id
                    else "office_work"
                ),
                "days": days,
            })
        return items

    @staticmethod
    def _document_expiration_detail(name, exp_date, days_left):
        if days_left < 0:
            timing = f"{abs(days_left)} day(s) overdue"
        elif days_left == 0:
            timing = "expires today"
        else:
            timing = f"expires in {days_left} day(s)"
        return f"{name}: {timing} on {exp_date.strftime('%b %d, %Y')}."

    @staticmethod
    def _appointment_detail(name, scheduled_date, days):
        if days < 0:
            timing = f"{abs(days)} day(s) overdue"
        else:
            timing = "due today"
        return f"{name}: {timing} on {scheduled_date.strftime('%b %d, %Y')}."

    @staticmethod
    def _task_detail(task, days):
        if days < 0:
            timing = f"{abs(days)} day(s) overdue"
        else:
            timing = "due today"
        priority = (task.priority or "NORMAL").title()
        return f"{priority} task {timing}."
