from collections import Counter, defaultdict
from datetime import date

from database.db import SessionLocal
from database.models.appointment import APPOINTMENT_STATUS_SCHEDULED, Appointment
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask, SecretaryTaskMissionary
from services.notification_feed_service import NotificationFeedService
from utils.logger import logger


VISIBLE_TASK_STATUSES = ("OPEN", "WAITING")
PRIORITY_RANK = {
    "CRITICAL": 0,
    "IMPORTANT": 1,
    "NORMAL": 2,
    "LOW": 3,
}
DETAIL_LIMITS = {
    "brief": 0,
    "balanced": 5,
    "detailed": 10,
}


TEXT = {
    "en": {
        "title": "Today's Digest",
        "subject": "Mission Legal - Today's Digest",
        "due_today": "Due today",
        "overdue": "Overdue",
        "top_items": "Top items",
        "empty": "No due work today.",
        "task_due": "{count} {label} due today",
        "task_overdue": "{count} overdue {label}",
        "appt_due": "{count} {label} appointments due today",
        "appt_week": "{count} {label} appointments this week",
        "appt_overdue": "{count} overdue {label} appointments",
        "doc_expiring": "{count} expiring/expired documents",
        "missing_docs": "{count} missing required documents",
        "transfer": "{count} transfer-cycle reminders",
        "office_tasks": "office tasks",
        "prorrogas": "prorrogas",
        "tasks": "tasks",
        "task_item": "{priority} task: {title}",
        "appt_item": "{type} appointment: {name}",
        "overdue_days": "{days} day(s) overdue",
        "today": "today",
    },
    "es": {
        "title": "Resumen de Hoy",
        "subject": "Mission Legal - Resumen de Hoy",
        "due_today": "Vence hoy",
        "overdue": "Atrasado",
        "top_items": "Más importante",
        "empty": "No hay trabajo pendiente para hoy.",
        "task_due": "{count} {label} para hoy",
        "task_overdue": "{count} {label} atrasadas",
        "appt_due": "{count} citas {label} para hoy",
        "appt_week": "{count} citas {label} esta semana",
        "appt_overdue": "{count} citas {label} atrasadas",
        "doc_expiring": "{count} documentos vencidos/por vencer",
        "missing_docs": "{count} documentos requeridos faltantes",
        "transfer": "{count} recordatorios de traslados",
        "office_tasks": "tareas de oficina",
        "prorrogas": "prórrogas",
        "tasks": "tareas",
        "task_item": "Tarea {priority}: {title}",
        "appt_item": "Cita {type}: {name}",
        "overdue_days": "{days} día(s) atrasado",
        "today": "hoy",
    },
}


GROUP_LABELS = {
    "prorroga": "Prorrogas",
    "gvm": "Travel Connect/GVM",
    "appointment": "Appointments",
    "document": "Documents",
    "missing": "Missing Documents",
    "transfer": "Transfer Reminders",
    "office": "Office Work",
    "other": "Other Tasks",
}


class DailyDigestService:
    def __init__(self, notification_feed_service=None):
        self.notification_feed_service = (
            notification_feed_service or NotificationFeedService()
        )

    def build_digest(
        self,
        *,
        include_overdue=True,
        detail_level="balanced",
        language="en",
        today=None,
    ):
        language = language if language in TEXT else "en"
        today = today or date.today()

        try:
            settings = (
                self.notification_feed_service
                .settings_service
                .get_notification_settings()
            )
            if not include_overdue:
                settings["include_overdue_tasks"] = False
            items = self.notification_feed_service.build_feed(
                today=today,
                settings=settings,
            )
            top_items = self._top_items(
                items,
                DETAIL_LIMITS.get(detail_level, DETAIL_LIMITS["balanced"]),
                today,
                language,
            )

            digest = {
                "date": today,
                "language": language,
                "title": TEXT[language]["title"],
                "subject": TEXT[language]["subject"],
                "summary": self._summary_counts(items, today),
                "due_today": self._summaries(
                    items,
                    today,
                    False,
                    language,
                ),
                "overdue": (
                    self._summaries(items, today, True, language)
                    if include_overdue
                    else []
                ),
                "top_items": top_items,
                "detail_groups": self._detail_groups(items, today),
                "items": items,
            }
            digest["is_empty"] = not (
                digest["due_today"]
                or digest["overdue"]
                or digest["top_items"]
                or digest["detail_groups"]
            )
            digest["text"] = self.render_text(digest)
            return digest
        except Exception:
            logger.exception("Failed to build daily digest")
            return self._empty_digest(today, language)

    def render_text(self, digest):
        language = digest.get("language", "en")
        text = TEXT.get(language, TEXT["en"])
        lines = [digest.get("title") or text["title"], ""]

        if digest.get("is_empty"):
            lines.append(text["empty"])
            return "\n".join(lines).strip()

        summary = digest.get("summary") or {}
        lines.append(
            "Summary: "
            f"{summary.get('critical', 0)} critical, "
            f"{summary.get('overdue', 0)} overdue, "
            f"{summary.get('due_today', 0)} due today, "
            f"{summary.get('total', 0)} total due items"
        )
        lines.append("")

        if digest.get("due_today"):
            lines.append(f"{text['due_today']}:")
            lines.extend(f"- {item}" for item in digest["due_today"])
            lines.append("")

        if digest.get("overdue"):
            lines.append(f"{text['overdue']}:")
            lines.extend(f"- {item}" for item in digest["overdue"])
            lines.append("")

        if digest.get("top_items"):
            lines.append(f"{text['top_items']}:")
            lines.extend(f"- {item['text']}" for item in digest["top_items"])
            lines.append("")

        if digest.get("detail_groups"):
            lines.append("Who needs what:")
            for group in digest["detail_groups"]:
                lines.append(f"{group['title']} ({group['count']}):")
                for item in group["items"]:
                    lines.append(
                        "- "
                        f"{item['who']}: {item['action']} "
                        f"({item['timing']})"
                    )
                lines.append("")

        return "\n".join(lines).strip()

    def _empty_digest(self, today, language):
        digest = {
            "date": today,
            "language": language,
            "title": TEXT[language]["title"],
            "subject": TEXT[language]["subject"],
            "due_today": [],
            "overdue": [],
            "top_items": [],
            "summary": {
                "critical": 0,
                "overdue": 0,
                "due_today": 0,
                "total": 0,
            },
            "detail_groups": [],
            "is_empty": True,
        }
        digest["text"] = self.render_text(digest)
        return digest

    @staticmethod
    def _load_tasks(session, today, include_overdue):
        query = session.query(SecretaryTask).filter(
            SecretaryTask.status.in_(VISIBLE_TASK_STATUSES),
            SecretaryTask.due_date.isnot(None),
            SecretaryTask.due_date <= today,
        )
        if not include_overdue:
            query = query.filter(SecretaryTask.due_date == today)
        return query.all()

    @staticmethod
    def _load_appointments(session, today, include_overdue):
        query = (
            session.query(Appointment, Missionary)
            .join(Missionary, Appointment.missionary_id == Missionary.id)
            .filter(
                Appointment.status == APPOINTMENT_STATUS_SCHEDULED,
                Appointment.scheduled_date <= today,
                Missionary.status == "ACTIVE",
            )
        )
        if not include_overdue:
            query = query.filter(Appointment.scheduled_date == today)
        return query.all()

    def _summaries(self, items, today, overdue, language):
        text = TEXT[language]
        lines = []
        due_items = [
            item for item in items
            if bool(item.get("days", 9999) < 0) == overdue
            and (overdue or item.get("days") == 0)
        ]

        task_counts = Counter(
            self._task_category(item, language)
            for item in due_items
            if item.get("type") == "secretary_task"
        )
        for label, count in sorted(task_counts.items()):
            template = text["task_overdue"] if overdue else text["task_due"]
            lines.append(template.format(count=count, label=label))

        appointment_counts = Counter(
            self._appointment_label(item)
            for item in due_items
            if item.get("type") == "appointment_due"
        )
        for label, count in sorted(appointment_counts.items()):
            template = text["appt_overdue"] if overdue else text["appt_due"]
            lines.append(template.format(count=count, label=label))

        if not overdue:
            week_counts = Counter(
                self._appointment_label(item)
                for item in items
                if item.get("type") == "appointment_due"
                and item.get("days", 9999) > 0
            )
            for label, count in sorted(week_counts.items()):
                lines.append(text["appt_week"].format(count=count, label=label))

            transfer_count = sum(
                1 for item in due_items
                if item.get("type") == "transfer_reminder"
            )
            if transfer_count:
                lines.append(text["transfer"].format(count=transfer_count))

            doc_count = sum(
                1 for item in items
                if item.get("type") == "document_expiration"
            )
            if doc_count:
                lines.append(text["doc_expiring"].format(count=doc_count))

            missing_count = sum(
                1 for item in items
                if item.get("type") == "missing_document"
            )
            if missing_count:
                lines.append(text["missing_docs"].format(count=missing_count))

        return lines

    @staticmethod
    def _summary_counts(items, today):
        task_count = sum(
            1 for item in items
            if item.get("type") in {"secretary_task", "transfer_reminder"}
        )
        appointment_count = sum(
            1 for item in items
            if item.get("type") == "appointment_due"
        )
        critical = sum(
            1
            for item in items
            if item.get("severity") == "critical"
            and (
                item.get("type") != "secretary_task"
                or item.get("priority") == "CRITICAL"
            )
        )
        overdue = sum(
            1
            for item in items
            if item.get("days", 9999) < 0
            and item.get("type") != "missing_document"
        )
        due_today = sum(
            1
            for item in items
            if item.get("days") == 0
            and item.get("type") in {
                "secretary_task",
                "transfer_reminder",
                "appointment_due",
            }
        )
        return {
            "critical": critical,
            "overdue": overdue,
            "due_today": due_today,
            "total": len(items),
            "tasks": task_count,
            "appointments": appointment_count,
        }

    def _detail_groups(self, items, today):
        grouped = defaultdict(list)

        for item in items:
            grouped[self._item_group_key(item)].append(
                self._detail_item(item, today)
            )

        groups = []
        for group_key, items in grouped.items():
            sorted_items = sorted(
                items,
                key=lambda item: (
                    item["severity_rank"],
                    item["days"],
                    item["who"],
                    item["action"],
                ),
            )
            groups.append({
                "key": group_key,
                "title": GROUP_LABELS.get(group_key, GROUP_LABELS["other"]),
                "count": len(sorted_items),
                "items": sorted_items,
            })

        return sorted(
            groups,
            key=lambda group: (
                min(item["severity_rank"] for item in group["items"]),
                group["title"],
            ),
        )

    @staticmethod
    def _task_category(task, language):
        text = TEXT[language]
        title = (task.get("title") or "").casefold()
        appointment_field = (task.get("appointment_field") or "").casefold()
        if "prorroga" in title or "prórroga" in title or "prorroga" in appointment_field:
            return text["prorrogas"]
        if task.get("missionary_id") or task.get("group_id"):
            return text["tasks"]
        return text["office_tasks"]

    @staticmethod
    def _item_group_key(item):
        item_type = item.get("type")
        if item_type == "appointment_due":
            return "appointment"
        if item_type == "document_expiration":
            return "document"
        if item_type == "missing_document":
            return "missing"
        if item_type == "transfer_reminder":
            return "transfer"
        title = (item.get("title") or "").casefold()
        automation_key = (item.get("automation_key") or "").casefold()
        appointment_field = (item.get("appointment_field") or "").casefold()
        if "prorroga" in title or "prorroga" in automation_key:
            return "prorroga"
        if "gvm" in title or "travel connect" in title or automation_key.startswith("gvm:"):
            return "gvm"
        if appointment_field:
            return "appointment"
        if item.get("missionary_id") or item.get("group_id"):
            return "other"
        return "office"

    def _detail_item(self, item, today):
        _ = today
        days = item.get("days", 9999)
        who = item.get("who") or self._item_who(item)
        priority = (item.get("priority") or "NORMAL").upper()
        return {
            "kind": item.get("type"),
            "task_id": item.get("task_id"),
            "appointment_id": item.get("appointment_id"),
            "group_id": item.get("group_id"),
            "missionary_id": item.get("missionary_id"),
            "missionary_count": item.get("missionary_count", 0),
            "who": who,
            "action": item.get("action") or item.get("title") or "Item",
            "detail": item.get("detail") or "",
            "priority": priority,
            "due_date": item.get("target_date"),
            "days": days,
            "timing": self._timing_label(days),
            "severity": item.get("severity") or self._severity(priority, days),
            "severity_rank": self._severity_rank(
                priority,
                days,
                item.get("severity"),
            ),
        }

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
        names = []
        missionary = getattr(task, "missionary", None)
        if missionary is not None and missionary.full_name:
            names.append(missionary.full_name)
        if names:
            return ", ".join(names)
        if task.missionary_id:
            return "Missionary record"
        if task.group_id:
            return task.group_scope_label or "Missionary group"
        return "Office"

    @staticmethod
    def _item_who(item):
        for key in ("who", "missionary_name", "name"):
            value = item.get(key)
            if value:
                return value
        if item.get("missionary_id"):
            return "Missionary record"
        return "Office"

    @staticmethod
    def _appointment_detail_item(appointment, missionary, today):
        days = (appointment.scheduled_date - today).days
        label = appointment.appointment_type or "Appointment"
        return {
            "kind": "appointment",
            "who": missionary.full_name or "Missionary",
            "action": f"{label} appointment",
            "detail": "",
            "priority": "CRITICAL" if days < 0 else "IMPORTANT",
            "due_date": appointment.scheduled_date,
            "days": days,
            "timing": DailyDigestService._timing_label(days),
            "severity": "critical" if days < 0 else "warning",
            "severity_rank": 0 if days < 0 else 1,
        }

    @staticmethod
    def _severity(priority, days):
        if priority == "CRITICAL" or days < 0:
            return "critical"
        if days == 0 or priority == "IMPORTANT":
            return "warning"
        return "info"

    @staticmethod
    def _severity_rank(priority, days, severity=None):
        if severity == "critical":
            return 0
        if severity == "warning":
            return 1
        if priority == "CRITICAL" or days < 0:
            return 0
        if days == 0 or priority == "IMPORTANT":
            return 1
        return 2

    @staticmethod
    def _timing_label(days):
        if days < 0:
            return f"{abs(days)} day(s) overdue"
        if days == 0:
            return "Today"
        if days == 9999:
            return "No due date"
        return f"In {days} day(s)"

    def _top_items(self, items, limit, today, language):
        if limit <= 0:
            return []

        ranked_items = []
        text = TEXT[language]
        for item in items:
            item_type = item.get("type")
            priority = item.get("priority") or "NORMAL"
            days = item.get("days", 9999)
            if item_type == "secretary_task":
                if priority not in {"CRITICAL", "IMPORTANT"} and days >= 0:
                    continue
                label = text["task_item"].format(
                    priority=priority.title(),
                    title=item.get("title"),
                )
            elif item_type == "appointment_due":
                if days >= 0:
                    continue
                label = text["appt_item"].format(
                    type=self._appointment_label(item),
                    name=item.get("who") or self._item_who(item),
                )
            elif item.get("severity") == "critical":
                label = item.get("title", "")
            else:
                continue
            ranked_items.append({
                "rank": (
                    PRIORITY_RANK.get(priority, 9),
                    0 if days < 0 else 1,
                    days,
                    item.get("title") or "",
                ),
                "text": label,
            })

        return [
            {"text": item["text"]}
            for item in sorted(ranked_items, key=lambda item: item["rank"])[:limit]
        ]

    @staticmethod
    def _appointment_label(item):
        title = item.get("title") or "Appointment"
        suffix = " appointment"
        if title.casefold().endswith(suffix):
            return title[:-len(suffix)]
        return title
