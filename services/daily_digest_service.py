from collections import Counter
from datetime import date

from database.db import SessionLocal
from database.models.appointment import APPOINTMENT_STATUS_SCHEDULED, Appointment
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
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
        "appt_overdue": "{count} overdue {label} appointments",
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
        "appt_overdue": "{count} citas {label} atrasadas",
        "office_tasks": "tareas de oficina",
        "prorrogas": "prórrogas",
        "tasks": "tareas",
        "task_item": "Tarea {priority}: {title}",
        "appt_item": "Cita {type}: {name}",
        "overdue_days": "{days} día(s) atrasado",
        "today": "hoy",
    },
}


class DailyDigestService:
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

        session = SessionLocal()
        try:
            tasks = self._load_tasks(session, today, include_overdue)
            appointments = self._load_appointments(session, today, include_overdue)
            top_items = self._top_items(
                tasks,
                appointments,
                DETAIL_LIMITS.get(detail_level, DETAIL_LIMITS["balanced"]),
                today,
                language,
            )

            digest = {
                "date": today,
                "language": language,
                "title": TEXT[language]["title"],
                "subject": TEXT[language]["subject"],
                "due_today": self._summaries(
                    tasks,
                    appointments,
                    today,
                    False,
                    language,
                ),
                "overdue": (
                    self._summaries(tasks, appointments, today, True, language)
                    if include_overdue
                    else []
                ),
                "top_items": top_items,
            }
            digest["is_empty"] = not (
                digest["due_today"]
                or digest["overdue"]
                or digest["top_items"]
            )
            digest["text"] = self.render_text(digest)
            return digest
        except Exception:
            logger.exception("Failed to build daily digest")
            return self._empty_digest(today, language)
        finally:
            session.close()

    def render_text(self, digest):
        language = digest.get("language", "en")
        text = TEXT.get(language, TEXT["en"])
        lines = [digest.get("title") or text["title"], ""]

        if digest.get("is_empty"):
            lines.append(text["empty"])
            return "\n".join(lines).strip()

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

    def _summaries(self, tasks, appointments, today, overdue, language):
        text = TEXT[language]
        lines = []
        due_tasks = [
            task
            for task in tasks
            if bool(task.due_date < today) == overdue
            and (overdue or task.due_date == today)
        ]
        due_appointments = [
            row
            for row in appointments
            if bool(row[0].scheduled_date < today) == overdue
            and (overdue or row[0].scheduled_date == today)
        ]

        task_counts = Counter(self._task_category(task, language) for task in due_tasks)
        for label, count in sorted(task_counts.items()):
            template = text["task_overdue"] if overdue else text["task_due"]
            lines.append(template.format(count=count, label=label))

        appointment_counts = Counter(
            row[0].appointment_type or text["tasks"] for row in due_appointments
        )
        for label, count in sorted(appointment_counts.items()):
            template = text["appt_overdue"] if overdue else text["appt_due"]
            lines.append(template.format(count=count, label=label))

        return lines

    @staticmethod
    def _task_category(task, language):
        text = TEXT[language]
        title = (task.title or "").casefold()
        appointment_field = (task.appointment_field or "").casefold()
        if "prorroga" in title or "prórroga" in title or "prorroga" in appointment_field:
            return text["prorrogas"]
        if task.missionary_id or task.group_id:
            return text["tasks"]
        return text["office_tasks"]

    def _top_items(self, tasks, appointments, limit, today, language):
        if limit <= 0:
            return []

        items = []
        text = TEXT[language]
        for task in tasks:
            priority = task.priority or "NORMAL"
            days = (task.due_date - today).days
            if priority not in {"CRITICAL", "IMPORTANT"} and days >= 0:
                continue
            items.append({
                "rank": (
                    PRIORITY_RANK.get(priority, 9),
                    0 if days < 0 else 1,
                    days,
                    task.title or "",
                ),
                "text": text["task_item"].format(
                    priority=priority.title(),
                    title=task.title,
                ),
            })

        for appointment, missionary in appointments:
            days = (appointment.scheduled_date - today).days
            if days >= 0:
                continue
            items.append({
                "rank": (0, 0, days, missionary.full_name or ""),
                "text": text["appt_item"].format(
                    type=appointment.appointment_type,
                    name=missionary.full_name,
                ),
            })

        return [
            {"text": item["text"]}
            for item in sorted(items, key=lambda item: item["rank"])[:limit]
        ]
