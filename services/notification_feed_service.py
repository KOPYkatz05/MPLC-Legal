from collections import Counter
from datetime import date, timedelta

from database.db import SessionLocal
from database.models.appointment import APPOINTMENT_STATUS_SCHEDULED, Appointment
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask, SecretaryTaskMissionary
from services.expiration_rules import should_track_expiration_field
from services.settings_service import SettingsService
from utils.constants import DOCUMENTS, required_documents_for_missionary
from utils.logger import logger


EXPIRY_FIELDS = [
    ("visa_expiration", "Visa Expiration"),
    ("residency_expiration", "Residency Expiration"),
    ("passport_expiration", "Passport Expiration"),
]
VISIBLE_TASK_STATUSES = ("OPEN", "READY", "WAITING")
AUTOMATION_SOURCE = "process_automation"


def week_end_for(value):
    return value + timedelta(days=6 - value.weekday())


def severity_rank(severity):
    return {
        "critical": 0,
        "warning": 1,
        "info": 2,
    }.get(severity, 9)


def notification_sort_key(item):
    return (
        severity_rank(item.get("severity")),
        item.get("days", 9999),
        item.get("target_date") or date.max,
        item.get("title", ""),
    )


class NotificationFeedService:
    def __init__(self, settings_service=None):
        self.settings_service = settings_service or SettingsService()

    def build_feed(self, *, today=None, settings=None):
        today = today or date.today()
        settings = settings or self.settings_service.get_notification_settings()
        session = SessionLocal()
        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )
            items = []
            items.extend(
                self._document_items(session, missionaries, today, settings)
            )
            items.extend(
                self._missing_document_items(session, missionaries, settings)
            )
            items.extend(self._appointment_items(session, today, settings))
            items.extend(self._task_items(session, today, settings))
            return sorted(items, key=notification_sort_key)
        except Exception:
            logger.exception("Failed to build notification feed")
            return []
        finally:
            session.close()

    def expiring_documents(self, *, today=None, settings=None):
        today = today or date.today()
        settings = settings or self.settings_service.get_notification_settings()
        if not settings.get("include_expiring_documents", True):
            return []
        session = SessionLocal()
        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )
            window = int(settings.get("dashboard_expiration_days", 60) or 60)
            expiring = []
            for missionary in missionaries:
                for field, label in EXPIRY_FIELDS:
                    if not should_track_expiration_field(missionary, field):
                        continue
                    value = getattr(missionary, field, None)
                    if value is None:
                        continue
                    days = (value - today).days
                    if days <= window:
                        expiring.append({
                            "missionary_id": missionary.id,
                            "name": missionary.full_name,
                            "field_label": label,
                            "date": value,
                            "days_left": days,
                        })
            return sorted(expiring, key=lambda item: item["days_left"])
        finally:
            session.close()

    def missing_documents(self, *, settings=None):
        settings = settings or self.settings_service.get_notification_settings()
        if not settings.get("include_missing_documents", True):
            return []
        session = SessionLocal()
        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )
            uploaded = self._uploaded_documents_by_missionary(session)
            missing = []
            for missionary in missionaries:
                missionary_missing = self._missing_for_missionary(
                    missionary,
                    uploaded.get(missionary.id, set()),
                )
                if missionary_missing:
                    missing.append({
                        "missionary_id": missionary.id,
                        "name": missionary.full_name,
                        "missing": missionary_missing,
                    })
            return missing
        finally:
            session.close()

    def startup_items(self, *, today=None):
        settings = self.settings_service.get_notification_settings()
        if not settings.get("startup_popup_enabled", True):
            return []
        return [
            item for item in self.build_feed(today=today, settings=settings)
            if "windows" in item.get("channel_tags", ())
        ]

    def windows_summary(self, items):
        items = list(items or [])
        if not items:
            return None
        counts = Counter(item.get("type") for item in items)
        parts = []
        labels = {
            "secretary_task": "task",
            "waiting_follow_up": "waiting follow-up",
            "waiting_no_follow_up": "task missing follow-up",
            "ready_task": "ready task",
            "appointment_due": "appointment",
            "document_expiration": "document",
            "missing_document": "missing document",
            "transfer_reminder": "transfer reminder",
        }
        for key in (
            "appointment_due",
            "secretary_task",
            "waiting_follow_up",
            "waiting_no_follow_up",
            "ready_task",
            "transfer_reminder",
            "document_expiration",
            "missing_document",
        ):
            count = counts.get(key, 0)
            if not count:
                continue
            label = labels[key]
            if count != 1:
                label = f"{label}s"
            parts.append(f"{count} {label}")
        fingerprint = "|".join(sorted(item["fingerprint"] for item in items))
        return {
            "title": "Mission Legal needs attention",
            "body": f"{len(items)} item(s): " + ", ".join(parts),
            "fingerprint": fingerprint,
        }

    def _document_items(self, session, missionaries, today, settings):
        if not settings.get("include_expiring_documents", True):
            return []
        window = int(settings.get("dashboard_expiration_days", 60) or 60)
        critical_window = int(settings.get("critical_expiration_days", 7) or 7)
        items = []
        for missionary in missionaries:
            for field, label in EXPIRY_FIELDS:
                if not should_track_expiration_field(missionary, field):
                    continue
                value = getattr(missionary, field, None)
                if value is None:
                    continue
                days = (value - today).days
                if days > window:
                    continue
                severity = "critical" if days < 0 else "warning"
                if days > critical_window:
                    severity = "info"
                missionary_name = self._missionary_name(missionary)
                items.append({
                    "type": "document_expiration",
                    "severity": severity,
                    "channel_tags": ["dashboard", "email", "windows"]
                    if severity in {"critical", "warning"}
                    else ["dashboard", "email"],
                    "title": f"{label} needs attention",
                    "detail": self._document_detail(
                        missionary.full_name,
                        value,
                        days,
                    ),
                    "who": missionary_name,
                    "missionary_name": missionary_name,
                    "target_date": value,
                    "source_id": f"{missionary.id}:{field}",
                    "source_kind": "missionary_expiration",
                    "fingerprint": f"document:{missionary.id}:{field}:{value}",
                    "missionary_id": missionary.id,
                    "target": "missionary",
                    "field_label": label,
                    "days": days,
                })
        return items

    def _missing_document_items(self, session, missionaries, settings):
        if not settings.get("include_missing_documents", True):
            return []
        uploaded = self._uploaded_documents_by_missionary(session)
        items = []
        for missionary in missionaries:
            missing = self._missing_for_missionary(
                missionary,
                uploaded.get(missionary.id, set()),
            )
            for doc in missing:
                title = f"Missing {doc['label']}"
                missionary_name = self._missionary_name(missionary)
                items.append({
                    "type": "missing_document",
                    "severity": "warning",
                    "channel_tags": ["dashboard", "email"],
                    "title": title,
                    "detail": (
                        f"{missionary.full_name} needs this "
                        f"for {doc['stage']}."
                    ),
                    "who": missionary_name,
                    "missionary_name": missionary_name,
                    "target_date": None,
                    "source_id": f"{missionary.id}:{doc['doc_type']}",
                    "source_kind": "missing_document",
                    "fingerprint": (
                        f"missing:{missionary.id}:{doc['stage']}:"
                        f"{doc['doc_type']}"
                    ),
                    "missionary_id": missionary.id,
                    "target": "missionary",
                    "stage": doc["stage"],
                    "doc_type": doc["doc_type"],
                    "document_label": doc["label"],
                    "days": 0,
                })
        return items

    def _appointment_items(self, session, today, settings):
        if not settings.get("include_appointments", True):
            return []
        week_end = week_end_for(today)
        rows = (
            session.query(Appointment, Missionary)
            .join(Missionary, Appointment.missionary_id == Missionary.id)
            .filter(
                Appointment.status == APPOINTMENT_STATUS_SCHEDULED,
                Appointment.scheduled_date <= week_end,
                Missionary.status == "ACTIVE",
            )
            .all()
        )
        items = []
        for appointment, missionary in rows:
            days = (appointment.scheduled_date - today).days
            label = appointment.appointment_type or "Appointment"
            missionary_name = self._missionary_name(missionary)
            if days < 0:
                severity = "critical"
            elif days == 0:
                severity = "warning"
            else:
                severity = "info"
            items.append({
                "type": "appointment_due",
                "severity": severity,
                "channel_tags": ["dashboard", "email", "windows"]
                if days <= 0
                else ["dashboard", "email"],
                "title": f"{label} appointment",
                "detail": self._appointment_detail(
                    missionary.full_name,
                    appointment.scheduled_date,
                    days,
                ),
                "who": missionary_name,
                "missionary_name": missionary_name,
                "target_date": appointment.scheduled_date,
                "source_id": appointment.id,
                "source_kind": "appointment",
                "fingerprint": (
                    f"appointment:{appointment.id}:"
                    f"{appointment.scheduled_date}"
                ),
                "appointment_id": appointment.id,
                "missionary_id": missionary.id,
                "target": "missionary",
                "days": days,
            })
        return items

    def _task_items(self, session, today, settings):
        tasks = (
            session.query(SecretaryTask)
            .filter(
                SecretaryTask.status.in_(VISIBLE_TASK_STATUSES),
                (
                    (
                        SecretaryTask.due_date.isnot(None)
                        & (SecretaryTask.due_date <= today)
                    )
                    | (
                        (SecretaryTask.status == "WAITING")
                        & SecretaryTask.waiting_follow_up_date.isnot(None)
                        & (SecretaryTask.waiting_follow_up_date <= today)
                    )
                    | (
                        (SecretaryTask.status == "WAITING")
                        & SecretaryTask.waiting_follow_up_date.is_(None)
                    )
                    | (SecretaryTask.status == "READY")
                ),
            )
            .all()
        )
        items = []
        for task in tasks:
            task_is_due = (
                task.due_date is not None and task.due_date <= today
            )
            if task.status == "READY":
                item = self._task_item_for_date(
                    session,
                    task,
                    today,
                    settings,
                    task.due_date or today,
                    "ready",
                )
                if item:
                    items.append(item)
                continue
            if task_is_due:
                item = self._task_item_for_date(
                    session,
                    task,
                    today,
                    settings,
                    task.due_date,
                    "due",
                )
                if item:
                    items.append(item)
            if (
                task.status == "WAITING"
                and task.waiting_follow_up_date is not None
                and task.waiting_follow_up_date <= today
            ):
                item = self._task_item_for_date(
                    session,
                    task,
                    today,
                    settings,
                    task.waiting_follow_up_date,
                    "follow_up",
                )
                if item:
                    items.append(item)
            if (
                task.status == "WAITING"
                and task.waiting_follow_up_date is None
                and not task_is_due
            ):
                item = self._task_item_for_date(
                    session,
                    task,
                    today,
                    settings,
                    today,
                    "missing_follow_up",
                )
                if item:
                    items.append(item)
        return items

    def _task_item_for_date(
        self,
        session,
        task,
        today,
        settings,
        target_date,
        date_kind,
    ):
        days = (target_date - today).days
        automation_key = task.automation_key or ""
        is_transfer = automation_key.startswith("transfer:")
        if is_transfer and date_kind == "due":
            if not settings.get("include_transfer_reminders", True):
                return None
            item_type = "transfer_reminder"
        else:
            if days < 0 and not settings.get("include_overdue_tasks", True):
                return None
            if days == 0 and not settings.get("include_due_today_tasks", True):
                return None
            if date_kind == "ready":
                item_type = "ready_task"
            elif date_kind == "follow_up":
                item_type = "waiting_follow_up"
            elif date_kind == "missing_follow_up":
                item_type = "waiting_no_follow_up"
            else:
                item_type = "secretary_task"
        priority = (task.priority or "NORMAL").upper()
        severity = self._task_severity(priority, days)
        return {
            "type": item_type,
            "severity": severity,
            "channel_tags": ["dashboard", "email", "windows"]
            if severity in {"critical", "warning"}
            else ["dashboard", "email"],
            "title": task.title,
            "detail": self._task_detail(task, days, date_kind),
            "target_date": target_date,
            "source_id": task.id,
            "source_kind": "secretary_task",
            "fingerprint": (
                f"task:{task.id}:{task.status}:{date_kind}:{target_date}"
            ),
            "task_id": task.id,
            "missionary_id": task.missionary_id,
            "target": "missionary" if task.missionary_id else "office_work",
            "priority": priority,
            "days": days,
            "automation_key": task.automation_key,
            "automation_source": task.automation_source,
            "group_id": task.group_id,
            "group_scope_label": task.group_scope_label,
            "missionary_count": self._task_missionary_count(session, task),
            "who": self._task_who(task),
            "action": task.title or "Task",
        }

    @staticmethod
    def _uploaded_documents_by_missionary(session):
        rows = session.query(Document).filter_by(status="ACTIVE").all()
        uploaded = {}
        for document in rows:
            uploaded.setdefault(document.missionary_id, set()).add(
                document.document_type
            )
        return uploaded

    @staticmethod
    def _missing_for_missionary(missionary, uploaded):
        stage = missionary.current_stage
        missing = []
        for doc_type in required_documents_for_missionary(stage, missionary):
            if doc_type in uploaded:
                continue
            label = DOCUMENTS.get(doc_type, {}).get("label", doc_type)
            missing.append({
                "stage": stage,
                "label": label,
                "doc_type": doc_type,
            })
        return missing

    @staticmethod
    def _document_detail(name, exp_date, days):
        if days < 0:
            timing = f"{abs(days)} day(s) overdue"
        elif days == 0:
            timing = "expires today"
        else:
            timing = f"expires in {days} day(s)"
        return f"{name}: {timing} on {exp_date.strftime('%b %d, %Y')}."

    @staticmethod
    def _appointment_detail(name, scheduled_date, days):
        if days < 0:
            timing = f"{abs(days)} day(s) overdue"
        elif days == 0:
            timing = "due today"
        else:
            timing = f"prepare in {days} day(s)"
        return f"{name}: {timing} on {scheduled_date.strftime('%b %d, %Y')}."

    @staticmethod
    def _task_detail(task, days, date_kind="due"):
        if days < 0:
            timing = f"{abs(days)} day(s) overdue"
        else:
            timing = "due today"
        priority = (task.priority or "NORMAL").title()
        if date_kind == "ready":
            if days < 0:
                return (
                    f"{priority} task ready for review "
                    f"and {abs(days)} day(s) overdue."
                )
            return f"{priority} task ready for review."
        if date_kind == "follow_up":
            return f"{priority} waiting follow-up {timing}."
        if date_kind == "missing_follow_up":
            return f"{priority} waiting task needs a follow-up date."
        return f"{priority} task {timing}."

    @staticmethod
    def _task_severity(priority, days):
        if priority == "CRITICAL" or days < 0:
            return "critical"
        if days == 0 or priority == "IMPORTANT":
            return "warning"
        return "info"

    @staticmethod
    def _task_missionary_count(session, task):
        if task.id is None:
            return 0
        return (
            session.query(SecretaryTaskMissionary)
            .filter_by(task_id=task.id)
            .count()
        )

    @staticmethod
    def _task_who(task):
        missionary = getattr(task, "missionary", None)
        if missionary is not None and missionary.full_name:
            return missionary.full_name
        if task.missionary_id:
            return "Missionary record"
        if task.group_id:
            return task.group_scope_label or "Missionary group"
        return "Office"

    @staticmethod
    def _missionary_name(missionary):
        return missionary.full_name or missionary.preferred_name or "Missionary"
