from datetime import date, datetime, timedelta

from database.db import SessionLocal
from database.models.missionary import Missionary
from database.models.secretary_work import (
    PRIORITIES,
    PROJECT_STATUSES,
    TASK_STATUSES,
    WAITING_REASONS,
    MissionaryGroup,
    MissionaryGroupMember,
    SecretaryProject,
    SecretaryTask,
    SecretaryTaskMissionary,
)
from utils.logger import logger


VISIBLE_TASK_STATUSES = ("OPEN", "WAITING")
VISIBLE_PROJECT_STATUSES = ("ACTIVE", "WAITING")
TASK_GROUPS = [
    ("overdue", "Overdue"),
    ("today", "Today"),
    ("this_week", "This Week"),
    ("later", "Later"),
    ("no_due_date", "No Due Date"),
]

APPOINTMENT_FIELD_LABELS = {
    "interpol_appointment_date": "Interpol",
    "biometric_appointment_date": "Biometric",
    "pickup_appointment_date": "Pickup",
}
WAITING_REASON_LABELS = {
    "MISSIONARY": "Waiting on missionary",
    "GOVERNMENT_SITE": "Waiting on government site",
    "PAYMENT": "Waiting on payment",
    "DOCUMENT": "Waiting on document",
    "APPOINTMENT_DATE": "Waiting on appointment date",
    "OTHER": "Other waiting reason",
}


class SecretaryWorkError(ValueError):
    pass


def _clean_text(value):
    return (value or "").strip()


def _normalize_choice(value, allowed, default):
    value = _clean_text(value).upper()
    if not value:
        return default
    if value not in allowed:
        raise SecretaryWorkError(f"Unsupported value: {value}")
    return value


def _now():
    return datetime.now()


def _normalize_waiting_reason(status, waiting_reason):
    if status != "WAITING":
        return None

    reason = _normalize_choice(
        waiting_reason,
        WAITING_REASONS,
        "",
    )
    if not reason:
        raise SecretaryWorkError("Waiting reason is required.")
    return reason


def _unique_ids(values):
    ids = []
    for value in values or []:
        if value is None:
            continue
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if item_id not in ids:
            ids.append(item_id)
    return ids


def task_due_group(due_date, today=None):
    if due_date is None:
        return "no_due_date"

    today = today or date.today()
    week_end = today + timedelta(days=6 - today.weekday())

    if due_date < today:
        return "overdue"
    if due_date == today:
        return "today"
    if due_date <= week_end:
        return "this_week"
    return "later"


class SecretaryWorkService:
    def create_project(
        self,
        title,
        description="",
        status="ACTIVE",
        priority="NORMAL",
        due_date=None,
    ):
        title = _clean_text(title)
        if not title:
            raise SecretaryWorkError("Project title is required.")

        session = SessionLocal()
        try:
            project = SecretaryProject(
                title=title,
                description=_clean_text(description) or None,
                status=_normalize_choice(
                    status,
                    PROJECT_STATUSES,
                    "ACTIVE",
                ),
                priority=_normalize_choice(
                    priority,
                    PRIORITIES,
                    "NORMAL",
                ),
                due_date=due_date,
            )
            session.add(project)
            session.commit()
            session.refresh(project)
            return self._project_snapshot(project, session)
        except Exception:
            session.rollback()
            logger.exception("Failed to create secretary project")
            raise
        finally:
            session.close()

    def update_project(self, project_id, **updates):
        session = SessionLocal()
        try:
            project = session.query(SecretaryProject).filter_by(id=project_id).first()
            if project is None:
                raise SecretaryWorkError("Project not found.")

            if "title" in updates:
                title = _clean_text(updates["title"])
                if not title:
                    raise SecretaryWorkError("Project title is required.")
                project.title = title
            if "description" in updates:
                project.description = _clean_text(updates["description"]) or None
            if "status" in updates:
                project.status = _normalize_choice(
                    updates["status"],
                    PROJECT_STATUSES,
                    project.status,
                )
            if "priority" in updates:
                project.priority = _normalize_choice(
                    updates["priority"],
                    PRIORITIES,
                    project.priority,
                )
            if "due_date" in updates:
                project.due_date = updates["due_date"]

            project.updated_at = _now()
            if project.status in {"DONE", "ARCHIVED"} and project.completed_at is None:
                project.completed_at = _now()
            elif project.status in {"ACTIVE", "WAITING"}:
                project.completed_at = None

            session.commit()
            session.refresh(project)
            return self._project_snapshot(project, session)
        except Exception:
            session.rollback()
            logger.exception("Failed to update secretary project")
            raise
        finally:
            session.close()

    def complete_project(self, project_id):
        return self.update_project(project_id, status="DONE")

    def archive_project(self, project_id):
        return self.update_project(project_id, status="ARCHIVED")

    def list_projects(
        self,
        search="",
        status=None,
        priority=None,
        include_done=False,
    ):
        session = SessionLocal()
        try:
            query = session.query(SecretaryProject)
            if not include_done and not status:
                query = query.filter(SecretaryProject.status.in_(VISIBLE_PROJECT_STATUSES))
            if status and status != "ALL":
                query = query.filter(SecretaryProject.status == status)
            if priority and priority != "ALL":
                query = query.filter(SecretaryProject.priority == priority)

            projects = query.order_by(
                SecretaryProject.due_date.is_(None),
                SecretaryProject.due_date,
                SecretaryProject.title,
            ).all()

            needle = _clean_text(search).casefold()
            snapshots = [
                self._project_snapshot(project, session)
                for project in projects
            ]
            if needle:
                snapshots = [
                    project for project in snapshots
                    if needle in project["title"].casefold()
                    or needle in (project["description"] or "").casefold()
                ]
            return snapshots
        finally:
            session.close()

    def create_task(
        self,
        title,
        description="",
        status="OPEN",
        priority="NORMAL",
        due_date=None,
        work_date=None,
        project_id=None,
        missionary_id=None,
        missionary_ids=None,
        group_id=None,
        appointment_field=None,
        waiting_reason=None,
    ):
        title = _clean_text(title)
        if not title:
            raise SecretaryWorkError("Task title is required.")

        session = SessionLocal()
        try:
            normalized_status = _normalize_choice(status, TASK_STATUSES, "OPEN")
            linked_ids, group_label = self._resolve_task_scope(
                session,
                missionary_id=missionary_id,
                missionary_ids=missionary_ids,
                group_id=group_id,
            )
            task = SecretaryTask(
                title=title,
                description=_clean_text(description) or None,
                status=normalized_status,
                priority=_normalize_choice(priority, PRIORITIES, "NORMAL"),
                due_date=due_date,
                work_date=work_date,
                project_id=project_id,
                missionary_id=linked_ids[0] if len(linked_ids) == 1 else None,
                group_id=group_id,
                group_scope_label=group_label,
                appointment_field=_clean_text(appointment_field) or None,
                waiting_reason=_normalize_waiting_reason(
                    normalized_status,
                    waiting_reason,
                ),
            )
            session.add(task)
            session.flush()
            self._replace_task_missionaries(session, task.id, linked_ids)
            session.commit()
            session.refresh(task)
            return self._task_snapshot(task, session)
        except Exception:
            session.rollback()
            logger.exception("Failed to create secretary task")
            raise
        finally:
            session.close()

    def update_task(self, task_id, **updates):
        session = SessionLocal()
        try:
            task = session.query(SecretaryTask).filter_by(id=task_id).first()
            if task is None:
                raise SecretaryWorkError("Task not found.")

            if "title" in updates:
                title = _clean_text(updates["title"])
                if not title:
                    raise SecretaryWorkError("Task title is required.")
                task.title = title
            if "description" in updates:
                task.description = _clean_text(updates["description"]) or None
            if "status" in updates:
                task.status = _normalize_choice(
                    updates["status"],
                    TASK_STATUSES,
                    task.status,
                )
            if "waiting_reason" in updates or "status" in updates:
                task.waiting_reason = _normalize_waiting_reason(
                    task.status,
                    updates.get("waiting_reason", task.waiting_reason),
                )
            if "priority" in updates:
                task.priority = _normalize_choice(
                    updates["priority"],
                    PRIORITIES,
                    task.priority,
                )
            for field in ("due_date", "work_date", "project_id"):
                if field in updates:
                    setattr(task, field, updates[field])
            if (
                "missionary_ids" in updates
                or "missionary_id" in updates
                or "group_id" in updates
            ):
                incoming_group_id = updates.get("group_id")
                incoming_ids = updates.get("missionary_ids")
                if (
                    incoming_group_id
                    and incoming_group_id == task.group_id
                    and incoming_ids is not None
                ):
                    linked_ids = _unique_ids(incoming_ids)
                    group_label = task.group_scope_label
                else:
                    linked_ids, group_label = self._resolve_task_scope(
                        session,
                        missionary_id=updates.get("missionary_id"),
                        missionary_ids=incoming_ids,
                        group_id=incoming_group_id,
                    )
                task.missionary_id = linked_ids[0] if len(linked_ids) == 1 else None
                task.group_id = incoming_group_id
                task.group_scope_label = group_label
                self._replace_task_missionaries(session, task.id, linked_ids)
            if "appointment_field" in updates:
                task.appointment_field = _clean_text(
                    updates["appointment_field"]
                ) or None

            task.updated_at = _now()
            if task.status in {"DONE", "ARCHIVED"} and task.completed_at is None:
                task.completed_at = _now()
            elif task.status in {"OPEN", "WAITING"}:
                task.completed_at = None

            session.commit()
            session.refresh(task)
            return self._task_snapshot(task, session)
        except Exception:
            session.rollback()
            logger.exception("Failed to update secretary task")
            raise
        finally:
            session.close()

    def complete_task(self, task_id):
        return self.update_task(task_id, status="DONE")

    def archive_task(self, task_id):
        return self.update_task(task_id, status="ARCHIVED")

    def delete_task(self, task_id):
        session = SessionLocal()
        try:
            task = session.query(SecretaryTask).filter_by(id=task_id).first()
            if task is None:
                raise SecretaryWorkError("Task not found.")
            session.query(SecretaryTaskMissionary).filter_by(task_id=task_id).delete()
            session.delete(task)
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("Failed to delete secretary task")
            raise
        finally:
            session.close()

    def list_tasks(
        self,
        search="",
        status=None,
        priority=None,
        project_id=None,
        missionary_id=None,
        due_range=None,
        include_done=False,
    ):
        session = SessionLocal()
        try:
            query = session.query(SecretaryTask)
            if not include_done and not status:
                query = query.filter(SecretaryTask.status.in_(VISIBLE_TASK_STATUSES))
            if status and status != "ALL":
                query = query.filter(SecretaryTask.status == status)
            if priority and priority != "ALL":
                query = query.filter(SecretaryTask.priority == priority)
            if project_id:
                query = query.filter(SecretaryTask.project_id == project_id)
            if missionary_id:
                linked_task_ids = (
                    session.query(SecretaryTaskMissionary.task_id)
                    .filter(
                        SecretaryTaskMissionary.missionary_id == missionary_id
                    )
                )
                query = query.filter(
                    (SecretaryTask.id.in_(linked_task_ids))
                    | (SecretaryTask.missionary_id == missionary_id)
                )

            tasks = query.order_by(
                SecretaryTask.due_date.is_(None),
                SecretaryTask.due_date,
                SecretaryTask.title,
            ).all()

            needle = _clean_text(search).casefold()
            snapshots = [self._task_snapshot(task, session) for task in tasks]
            if needle:
                snapshots = [
                    task for task in snapshots
                    if needle in task["title"].casefold()
                    or needle in (task["description"] or "").casefold()
                    or needle in (task["project_title"] or "").casefold()
                    or needle in (task["missionary_name"] or "").casefold()
                    or needle in " ".join(task["missionary_names"]).casefold()
                    or needle in (task["group_scope_label"] or "").casefold()
                    or needle in task["appointment_label"].casefold()
                    or needle in task["waiting_reason_label"].casefold()
                ]
            if due_range and due_range != "all":
                snapshots = [
                    task for task in snapshots
                    if task["due_group"] == due_range
                ]
            return snapshots
        finally:
            session.close()

    def grouped_tasks(self, **filters):
        grouped = {key: [] for key, _label in TASK_GROUPS}
        for task in self.list_tasks(**filters):
            grouped.setdefault(task["due_group"], []).append(task)
        return grouped

    def list_calendar_tasks(self):
        tasks = [
            task
            for task in self.list_tasks(include_done=True)
            if task["status"] != "ARCHIVED" and task.get("work_date") is not None
        ]
        return sorted(
            tasks,
            key=lambda task: (
                task["work_date"],
                task["status"] == "DONE",
                task["title"].casefold(),
            ),
        )

    def summary(self):
        session = SessionLocal()
        try:
            tasks = (
                session.query(SecretaryTask)
                .filter(SecretaryTask.status.in_(VISIBLE_TASK_STATUSES))
                .all()
            )
            today = date.today()
            return {
                "open": sum(1 for task in tasks if task.status == "OPEN"),
                "waiting": sum(1 for task in tasks if task.status == "WAITING"),
                "overdue": sum(
                    1 for task in tasks
                    if task.due_date is not None and task.due_date < today
                ),
                "due_today": sum(1 for task in tasks if task.due_date == today),
            }
        finally:
            session.close()

    def missionary_options(self):
        session = SessionLocal()
        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .order_by(Missionary.full_name)
                .all()
            )
            return [
                {
                    "id": missionary.id,
                    "name": missionary.full_name,
                }
                for missionary in missionaries
            ]
        finally:
            session.close()

    def group_options(self):
        session = SessionLocal()
        try:
            groups = session.query(MissionaryGroup).order_by(MissionaryGroup.name).all()
            return [
                {
                    "id": group.id,
                    "name": group.name,
                    "missionary_ids": self._group_member_ids(session, group.id),
                    "member_count": len(self._group_member_ids(session, group.id)),
                }
                for group in groups
            ]
        finally:
            session.close()

    def project_options(self):
        return [
            {
                "id": project["id"],
                "title": project["title"],
            }
            for project in self.list_projects()
        ]

    def _project_snapshot(self, project, session):
        counts = self._project_task_counts(project.id, session)
        total = counts["total"]
        done = counts["done"]
        return {
            "id": project.id,
            "title": project.title,
            "description": project.description or "",
            "status": project.status,
            "priority": project.priority,
            "due_date": project.due_date,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "completed_at": project.completed_at,
            "open_tasks": counts["open"],
            "done_tasks": done,
            "total_tasks": total,
            "progress": f"{done}/{total} done" if total else "0/0 done",
        }

    def _task_snapshot(self, task, session):
        project_title = ""
        missionary_ids, missionary_names = self._task_missionary_scope(task, session)
        missionary_name = missionary_names[0] if len(missionary_names) == 1 else ""
        if task.project_id:
            project = session.query(SecretaryProject).filter_by(id=task.project_id).first()
            project_title = project.title if project else ""
        scope_label = ""
        if len(missionary_names) == 1:
            scope_label = missionary_names[0]
        elif missionary_names:
            scope_label = f"{len(missionary_names)} missionaries"
            if task.group_scope_label:
                scope_label = f"{scope_label} - {task.group_scope_label}"

        return {
            "id": task.id,
            "title": task.title,
            "description": task.description or "",
            "status": task.status,
            "priority": task.priority,
            "due_date": task.due_date,
            "work_date": task.work_date,
            "due_group": task_due_group(task.due_date),
            "project_id": task.project_id,
            "project_title": project_title,
            "missionary_id": missionary_ids[0] if len(missionary_ids) == 1 else None,
            "missionary_name": missionary_name,
            "missionary_ids": missionary_ids,
            "missionary_names": missionary_names,
            "missionary_count": len(missionary_ids),
            "group_id": task.group_id,
            "group_scope_label": task.group_scope_label or "",
            "scope_label": scope_label,
            "is_group_task": len(missionary_ids) > 1,
            "appointment_field": task.appointment_field,
            "appointment_label": APPOINTMENT_FIELD_LABELS.get(
                task.appointment_field,
                "",
            ),
            "waiting_reason": task.waiting_reason,
            "waiting_reason_label": WAITING_REASON_LABELS.get(
                task.waiting_reason,
                "",
            ),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "completed_at": task.completed_at,
        }

    def _resolve_task_scope(
        self,
        session,
        missionary_id=None,
        missionary_ids=None,
        group_id=None,
    ):
        if group_id:
            group = session.query(MissionaryGroup).filter_by(id=group_id).first()
            if group is None:
                raise SecretaryWorkError("Group not found.")
            return self._group_member_ids(session, group_id), group.name

        linked_ids = _unique_ids(missionary_ids)
        if missionary_id is not None and not linked_ids:
            linked_ids = _unique_ids([missionary_id])
        return linked_ids, None

    def _group_member_ids(self, session, group_id):
        rows = (
            session.query(MissionaryGroupMember.missionary_id)
            .filter_by(group_id=group_id)
            .all()
        )
        return [row[0] for row in rows]

    def _replace_task_missionaries(self, session, task_id, missionary_ids):
        session.query(SecretaryTaskMissionary).filter_by(task_id=task_id).delete()
        for missionary_id in _unique_ids(missionary_ids):
            session.add(
                SecretaryTaskMissionary(
                    task_id=task_id,
                    missionary_id=missionary_id,
                )
            )

    def _task_missionary_scope(self, task, session):
        rows = (
            session.query(Missionary)
            .join(
                SecretaryTaskMissionary,
                SecretaryTaskMissionary.missionary_id == Missionary.id,
            )
            .filter(SecretaryTaskMissionary.task_id == task.id)
            .order_by(Missionary.full_name)
            .all()
        )
        if rows:
            return (
                [missionary.id for missionary in rows],
                [missionary.full_name for missionary in rows],
            )
        if task.missionary_id:
            missionary = session.query(Missionary).filter_by(id=task.missionary_id).first()
            if missionary:
                self._replace_task_missionaries(session, task.id, [missionary.id])
                return [missionary.id], [missionary.full_name]
        return [], []

    def _project_task_counts(self, project_id, session):
        tasks = session.query(SecretaryTask).filter_by(project_id=project_id).all()
        done = sum(1 for task in tasks if task.status == "DONE")
        open_count = sum(1 for task in tasks if task.status in VISIBLE_TASK_STATUSES)
        return {
            "done": done,
            "open": open_count,
            "total": len([task for task in tasks if task.status != "ARCHIVED"]),
        }
