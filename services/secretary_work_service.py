from datetime import date, datetime, timedelta

from database.db import SessionLocal
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import (
    PRIORITIES,
    PROJECT_STATUSES,
    TASK_STATUSES,
    TASK_TYPES,
    WAITING_REASONS,
    MissionaryGroup,
    MissionaryGroupMember,
    SecretaryProject,
    SecretaryTask,
    SecretaryTaskHistory,
    SecretaryTaskMissionary,
)
from utils.constants import DOCUMENTS, WORKFLOW_STAGES
from utils.logger import logger


VISIBLE_TASK_STATUSES = ("OPEN", "READY", "WAITING")
VISIBLE_PROJECT_STATUSES = ("ACTIVE", "WAITING")
TASK_BOARD_LANES = ("not_started", "in_progress", "completed")
TASK_GROUPS = [
    ("overdue", "Overdue"),
    ("follow_up_due", "Follow Up Due"),
    ("needs_follow_up", "Needs Follow-Up"),
    ("scheduled_follow_up", "Scheduled Follow-Ups"),
    ("today", "Today"),
    ("ready_to_review", "Ready to Review"),
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
TASK_TYPE_LABELS = {
    "DOCUMENT": "Document",
    "PAYMENT": "Payment",
    "APPOINTMENT": "Appointment",
    "FOLLOW_UP": "Follow-up",
    "LEGAL_REVIEW": "Legal Review",
    "SUBMISSION": "Submission",
    "STAGE_ADVANCE": "Stage Advance",
    "GVM_UPDATE": "GVM Update",
    "CUSTOM": "Custom",
}
TEMPORARY_GROUP_TYPE = "TEMPORARY_AUTOMATION"


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


def _normalize_waiting_follow_up_date(status, waiting_follow_up_date):
    if status != "WAITING":
        return None
    return waiting_follow_up_date


def _normalize_task_type(task_type):
    return _normalize_choice(task_type, TASK_TYPES, "CUSTOM")


def _normalize_related_stage(related_stage):
    stage = _clean_text(related_stage).upper()
    if not stage:
        return None
    if stage not in WORKFLOW_STAGES:
        raise SecretaryWorkError(f"Unsupported related stage: {stage}")
    return stage


def _normalize_related_document_type(related_document_type):
    document_type = _clean_text(related_document_type).upper()
    if not document_type:
        return None
    if document_type not in DOCUMENTS:
        raise SecretaryWorkError(
            f"Unsupported related document type: {document_type}"
        )
    return document_type


def document_label(document_type):
    if not document_type:
        return ""
    return DOCUMENTS.get(document_type, {}).get("label", document_type)


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
        task_type="CUSTOM",
        related_stage=None,
        related_document_type=None,
        automation_key=None,
        automation_source=None,
        waiting_reason=None,
        waiting_follow_up_date=None,
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
                board_lane=None,
                board_position=None,
                project_id=project_id,
                missionary_id=linked_ids[0] if len(linked_ids) == 1 else None,
                group_id=group_id,
                group_scope_label=group_label,
                appointment_field=_clean_text(appointment_field) or None,
                task_type=_normalize_task_type(task_type),
                related_stage=_normalize_related_stage(related_stage),
                related_document_type=_normalize_related_document_type(
                    related_document_type,
                ),
                automation_key=_clean_text(automation_key) or None,
                automation_source=_clean_text(automation_source) or None,
                waiting_reason=_normalize_waiting_reason(
                    normalized_status,
                    waiting_reason,
                ),
                waiting_follow_up_date=_normalize_waiting_follow_up_date(
                    normalized_status,
                    waiting_follow_up_date,
                ),
            )
            session.add(task)
            session.flush()
            self._add_task_history(
                session,
                task.id,
                "STATUS",
                None,
                task.status,
                "Task created",
            )
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

            old_status = task.status
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
            if "waiting_follow_up_date" in updates or "status" in updates:
                task.waiting_follow_up_date = _normalize_waiting_follow_up_date(
                    task.status,
                    updates.get(
                        "waiting_follow_up_date",
                        task.waiting_follow_up_date,
                    ),
                )
            if "priority" in updates:
                task.priority = _normalize_choice(
                    updates["priority"],
                    PRIORITIES,
                    task.priority,
                )
            for field in (
                "due_date",
                "work_date",
                "project_id",
                "board_lane",
                "board_position",
            ):
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
            if "task_type" in updates:
                task.task_type = _normalize_task_type(updates["task_type"])
            if "related_stage" in updates:
                task.related_stage = _normalize_related_stage(
                    updates["related_stage"]
                )
            if "related_document_type" in updates:
                task.related_document_type = _normalize_related_document_type(
                    updates["related_document_type"]
                )
            if "automation_key" in updates:
                task.automation_key = _clean_text(
                    updates["automation_key"]
                ) or None
            if "automation_source" in updates:
                task.automation_source = _clean_text(
                    updates["automation_source"]
                ) or None
            if "automation_status_reason" in updates:
                task.automation_status_reason = _clean_text(
                    updates["automation_status_reason"]
                ) or None

            task.updated_at = _now()
            if task.status in {"DONE", "ARCHIVED"} and task.completed_at is None:
                task.completed_at = _now()
            elif task.status in VISIBLE_TASK_STATUSES:
                task.completed_at = None
            if old_status != task.status:
                self._add_task_history(
                    session,
                    task.id,
                    "STATUS",
                    old_status,
                    task.status,
                )

            session.commit()
            session.refresh(task)
            return self._task_snapshot(task, session)
        except Exception:
            session.rollback()
            logger.exception("Failed to update secretary task")
            raise
        finally:
            session.close()

    def save_task_board_orders(self, lane_orders):
        session = SessionLocal()
        try:
            task_ids = [
                task_id
                for ordered_ids in lane_orders.values()
                for task_id in ordered_ids
            ]
            tasks = {}
            if task_ids:
                rows = (
                    session.query(SecretaryTask)
                    .filter(SecretaryTask.id.in_(task_ids))
                    .all()
                )
                tasks = {task.id: task for task in rows}

            for lane, ordered_ids in lane_orders.items():
                if lane not in TASK_BOARD_LANES:
                    continue
                for index, task_id in enumerate(ordered_ids):
                    task = tasks.get(task_id)
                    if task is None:
                        continue
                    task.board_lane = lane
                    task.board_position = index * 1000
                    task.updated_at = _now()

            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to save secretary task board order")
            raise
        finally:
            session.close()

    def complete_task(self, task_id):
        snapshot = self.update_task(task_id, status="DONE")
        self._cleanup_completed_temporary_group(task_id)
        return self._snapshot_for_task_id(task_id)

    def mark_task_ready(self, task_id):
        return self.update_task(task_id, status="READY")

    def reopen_task(self, task_id):
        return self.update_task(task_id, status="OPEN")

    def archive_task(self, task_id):
        snapshot = self.update_task(task_id, status="ARCHIVED")
        self._cleanup_completed_temporary_group(task_id)
        return self._snapshot_for_task_id(task_id)

    def delete_task(self, task_id):
        self._cleanup_completed_temporary_group(task_id)
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

    def get_task_workspace(self, task_id, today=None):
        today = today or date.today()
        session = SessionLocal()
        try:
            task = session.query(SecretaryTask).filter_by(id=task_id).first()
            if task is None:
                raise SecretaryWorkError("Task not found.")

            snapshot = self._task_snapshot(task, session)
            days = (
                (task.due_date - today).days
                if task.due_date is not None
                else None
            )
            affected = self._workspace_missionaries(task, session, today)
            classification = self._workspace_classification_context(
                snapshot,
                affected,
            )
            history = self._task_history_items(task.id, session)
            workspace = dict(snapshot)
            workspace.update({
                "days": days,
                "timing": self._workspace_timing(days),
                "due_date_text": self._format_workspace_date(task.due_date),
                "work_date_text": self._format_workspace_date(task.work_date),
                "classification": classification,
                "brief_text": self._workspace_brief_text(
                    snapshot,
                    affected,
                    days,
                    classification,
                ),
                "why_text": self._workspace_why_text(
                    snapshot,
                    affected,
                    days,
                    classification,
                ),
                "why_points": self._workspace_why_points(
                    snapshot,
                    affected,
                    days,
                    classification,
                ),
                "key_facts": self._workspace_key_facts(
                    snapshot,
                    affected,
                    days,
                    classification,
                ),
                "evidence": self._workspace_evidence(snapshot, history),
                "status_history": history,
                "affected_missionaries": affected,
                "recommended_steps": self._workspace_recommended_steps(
                    snapshot,
                    classification,
                ),
            })
            return workspace
        finally:
            session.close()

    def get_task_status_history(self, task_id, limit=6):
        session = SessionLocal()
        try:
            task = session.query(SecretaryTask).filter_by(id=task_id).first()
            if task is None:
                raise SecretaryWorkError("Task not found.")
            return self._task_history_items(task.id, session, limit=limit)
        finally:
            session.close()

    def archive_obsolete_automatic_tasks(
        self,
        *,
        active_keys,
        source,
        prefixes,
        reason,
    ):
        active_keys = set(active_keys or [])
        prefixes = tuple(prefixes or ())
        session = SessionLocal()
        archived = 0
        try:
            tasks = (
                session.query(SecretaryTask)
                .filter(
                    SecretaryTask.automation_source == source,
                    SecretaryTask.status.in_(VISIBLE_TASK_STATUSES),
                )
                .all()
            )
            for task in tasks:
                key = task.automation_key or ""
                if key in active_keys:
                    continue
                if prefixes and not key.startswith(prefixes):
                    continue
                old_status = task.status
                task.status = "ARCHIVED"
                task.completed_at = task.completed_at or _now()
                task.automation_status_reason = reason
                self._add_task_history(
                    session,
                    task.id,
                    "STATUS",
                    old_status,
                    task.status,
                    reason,
                )
                self._cleanup_temporary_group_in_session(session, task)
                archived += 1
            session.commit()
            return archived
        except Exception:
            session.rollback()
            logger.exception("Failed to archive obsolete automatic tasks")
            raise
        finally:
            session.close()

    def create_or_update_automatic_task(
        self,
        *,
        automation_key,
        automation_source,
        title,
        description="",
        priority="NORMAL",
        due_date=None,
        work_date=None,
        missionary_id=None,
        missionary_ids=None,
        group_id=None,
        appointment_field=None,
        task_type=None,
        related_stage=None,
        related_document_type=None,
        waiting_reason=None,
        waiting_follow_up_date=None,
    ):
        automation_key = _clean_text(automation_key)
        if not automation_key:
            raise SecretaryWorkError("Automation key is required.")

        session = SessionLocal()
        try:
            task = (
                session.query(SecretaryTask)
                .filter_by(automation_key=automation_key)
                .first()
            )
            existing_task_id = task.id if task is not None else None
            existing_status = task.status if task is not None else None
        finally:
            session.close()

        if existing_task_id is None:
            group_id = self._ensure_temporary_group_for_automatic_task(
                automation_key=automation_key,
                automation_source=automation_source,
                title=title,
                missionary_ids=missionary_ids,
                explicit_group_id=group_id,
            )
            snapshot = self.create_task(
                title,
                description=description,
                priority=priority,
                due_date=due_date,
                work_date=work_date,
                missionary_id=missionary_id,
                missionary_ids=missionary_ids,
                group_id=group_id,
                appointment_field=appointment_field,
                task_type=task_type or "CUSTOM",
                related_stage=related_stage,
                related_document_type=related_document_type,
                automation_key=automation_key,
                automation_source=automation_source,
                waiting_reason=waiting_reason,
                waiting_follow_up_date=waiting_follow_up_date,
            )
            snapshot["automation_result"] = "created"
            return snapshot

        if existing_status in {"DONE", "ARCHIVED"}:
            snapshot = self._snapshot_for_task_id(existing_task_id)
            snapshot["automation_result"] = "skipped"
            return snapshot

        group_id = self._ensure_temporary_group_for_automatic_task(
            automation_key=automation_key,
            automation_source=automation_source,
            title=title,
            missionary_ids=missionary_ids,
            explicit_group_id=group_id,
        )

        updates = {
            "title": title,
            "description": description,
            "priority": priority,
            "due_date": due_date,
            "work_date": work_date,
            "missionary_id": missionary_id,
            "missionary_ids": missionary_ids,
            "group_id": group_id,
            "appointment_field": appointment_field,
            "automation_source": automation_source,
            "waiting_reason": waiting_reason,
        }
        if waiting_follow_up_date is not None:
            updates["waiting_follow_up_date"] = waiting_follow_up_date
        if task_type is not None:
            updates["task_type"] = task_type
        if related_stage is not None:
            updates["related_stage"] = related_stage
        if related_document_type is not None:
            updates["related_document_type"] = related_document_type

        snapshot = self.update_task(existing_task_id, **updates)
        snapshot["automation_result"] = "updated"
        return snapshot

    def _ensure_temporary_group_for_automatic_task(
        self,
        *,
        automation_key,
        automation_source,
        title,
        missionary_ids=None,
        explicit_group_id=None,
    ):
        if explicit_group_id:
            return explicit_group_id
        linked_ids = _unique_ids(missionary_ids)
        if len(linked_ids) <= 1:
            return None

        group_name = f"Temporary - {title}"
        session = SessionLocal()
        try:
            group = (
                session.query(MissionaryGroup)
                .filter_by(
                    automation_key=automation_key,
                    group_type=TEMPORARY_GROUP_TYPE,
                )
                .first()
            )
            if group is None:
                group = MissionaryGroup(
                    name=group_name,
                    description=(
                        "Temporary group created for an automatic process task. "
                        "It will be removed when the task is completed."
                    ),
                    group_type=TEMPORARY_GROUP_TYPE,
                    automation_key=automation_key,
                )
                session.add(group)
                session.flush()
            else:
                group.name = group_name
                group.description = (
                    "Temporary group created for an automatic process task. "
                    "It will be removed when the task is completed."
                )
            self._replace_group_members(session, group.id, linked_ids)
            session.commit()
            return group.id
        except Exception:
            session.rollback()
            logger.exception("Failed to create temporary automation group")
            raise
        finally:
            session.close()

    def _cleanup_completed_temporary_group(self, task_id):
        session = SessionLocal()
        try:
            task = session.query(SecretaryTask).filter_by(id=task_id).first()
            if task is None or task.group_id is None:
                return

            group = (
                session.query(MissionaryGroup)
                .filter_by(id=task.group_id)
                .first()
            )
            if group is None or group.group_type != TEMPORARY_GROUP_TYPE:
                return

            other_visible_tasks = (
                session.query(SecretaryTask)
                .filter(
                    SecretaryTask.id != task.id,
                    SecretaryTask.group_id == group.id,
                    SecretaryTask.status.in_(VISIBLE_TASK_STATUSES),
                )
                .count()
            )
            if other_visible_tasks:
                return

            self._cleanup_temporary_group_in_session(session, task, group)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to clean up temporary automation group")
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
        task_type=None,
        related_stage=None,
        related_document_type=None,
        automation_state=None,
        waiting_follow_up=None,
        waiting_reason=None,
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
            if task_type and task_type != "ALL":
                if task_type == "APPOINTMENT":
                    query = query.filter(
                        (SecretaryTask.task_type == "APPOINTMENT")
                        | (SecretaryTask.appointment_field.is_not(None))
                    )
                else:
                    query = query.filter(SecretaryTask.task_type == task_type)
            if related_stage and related_stage != "ALL":
                query = query.filter(SecretaryTask.related_stage == related_stage)
            if related_document_type and related_document_type != "ALL":
                query = query.filter(
                    SecretaryTask.related_document_type
                    == _normalize_related_document_type(related_document_type)
                )
            if automation_state == "AUTO":
                query = query.filter(
                    SecretaryTask.automation_source.is_not(None),
                    SecretaryTask.automation_source != "",
                )
            elif automation_state == "MANUAL":
                query = query.filter(
                    (SecretaryTask.automation_source.is_(None))
                    | (SecretaryTask.automation_source == "")
                )
            if project_id:
                query = query.filter(SecretaryTask.project_id == project_id)
            if waiting_follow_up == "due":
                query = query.filter(
                    SecretaryTask.status == "WAITING",
                    SecretaryTask.waiting_follow_up_date.is_not(None),
                    SecretaryTask.waiting_follow_up_date <= date.today(),
                )
            elif waiting_follow_up == "upcoming":
                query = query.filter(
                    SecretaryTask.status == "WAITING",
                    SecretaryTask.waiting_follow_up_date.is_not(None),
                    SecretaryTask.waiting_follow_up_date > date.today(),
                )
            elif waiting_follow_up == "missing":
                query = query.filter(
                    SecretaryTask.status == "WAITING",
                    SecretaryTask.waiting_follow_up_date.is_(None),
                )
            if waiting_reason and waiting_reason != "ALL":
                query = query.filter(
                    SecretaryTask.status == "WAITING",
                    SecretaryTask.waiting_reason == waiting_reason,
                )
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
            snapshot_context = self._task_snapshot_context(session, tasks)
            snapshots = [
                self._task_snapshot(task, session, snapshot_context)
                for task in tasks
            ]
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
                    or needle in task["waiting_follow_up_label"].casefold()
                    or needle in task["waiting_follow_up_status_label"].casefold()
                    or needle in task["task_type_label"].casefold()
                    or needle in (task["related_stage"] or "").casefold()
                    or needle in task["related_document_label"].casefold()
                ]
            if due_range and due_range != "all":
                snapshots = [
                    task for task in snapshots
                    if task["due_group"] == due_range
                ]
            if waiting_follow_up in {"due", "upcoming"}:
                snapshots = self._sort_by_waiting_follow_up(snapshots)
            return snapshots
        finally:
            session.close()

    def _task_snapshot_context(self, session, tasks):
        task_ids = [task.id for task in tasks]
        project_ids = sorted({
            task.project_id for task in tasks if task.project_id
        })
        group_ids = sorted({task.group_id for task in tasks if task.group_id})
        missionary_ids = sorted({
            task.missionary_id for task in tasks if task.missionary_id
        })

        project_titles = {}
        if project_ids:
            project_titles = {
                project.id: project.title
                for project in session.query(SecretaryProject)
                .filter(SecretaryProject.id.in_(project_ids))
                .all()
            }

        group_types = {}
        if group_ids:
            group_types = {
                group.id: group.group_type or ""
                for group in session.query(MissionaryGroup)
                .filter(MissionaryGroup.id.in_(group_ids))
                .all()
            }

        task_missionary_scope = {task_id: ([], []) for task_id in task_ids}
        missionary_name_by_id = {}
        if task_ids:
            rows = (
                session.query(
                    SecretaryTaskMissionary.task_id,
                    Missionary.id,
                    Missionary.full_name,
                )
                .join(
                    Missionary,
                    SecretaryTaskMissionary.missionary_id == Missionary.id,
                )
                .filter(SecretaryTaskMissionary.task_id.in_(task_ids))
                .order_by(SecretaryTaskMissionary.task_id, Missionary.full_name)
                .all()
            )
            for task_id, missionary_id, missionary_name in rows:
                missionary_name_by_id[missionary_id] = missionary_name
                ids, names = task_missionary_scope.get(task_id, ([], []))
                task_missionary_scope[task_id] = (
                    [*ids, missionary_id],
                    [*names, missionary_name],
                )

        fallback_missionary_ids = [
            missionary_id
            for missionary_id in missionary_ids
            if missionary_id not in missionary_name_by_id
        ]
        if fallback_missionary_ids:
            for missionary in (
                session.query(Missionary)
                .filter(Missionary.id.in_(fallback_missionary_ids))
                .all()
            ):
                missionary_name_by_id[missionary.id] = missionary.full_name

        for task in tasks:
            if task_missionary_scope[task.id][0]:
                continue
            if task.missionary_id and task.missionary_id in missionary_name_by_id:
                task_missionary_scope[task.id] = (
                    [task.missionary_id],
                    [missionary_name_by_id[task.missionary_id]],
                )

        return {
            "project_titles": project_titles,
            "group_types": group_types,
            "task_missionary_scope": task_missionary_scope,
        }

    def grouped_tasks(self, **filters):
        grouped = {key: [] for key, _label in TASK_GROUPS}
        due_range = filters.get("due_range")
        for task in self.list_tasks(**filters):
            group_key = task["due_group"]
            if self._is_waiting_follow_up_due(task) and due_range in (None, "all"):
                group_key = "follow_up_due"
            elif (
                self._is_waiting_missing_follow_up(task)
                and due_range in (None, "all")
            ):
                group_key = "needs_follow_up"
            elif (
                self._is_waiting_follow_up_upcoming(task)
                and due_range in (None, "all")
            ):
                group_key = "scheduled_follow_up"
            elif (
                task["status"] == "READY"
                and due_range in (None, "all")
            ):
                group_key = "ready_to_review"
            grouped.setdefault(group_key, []).append(task)
        grouped["follow_up_due"] = self._sort_by_waiting_follow_up(
            grouped.get("follow_up_due", [])
        )
        grouped["scheduled_follow_up"] = self._sort_by_waiting_follow_up(
            grouped.get("scheduled_follow_up", [])
        )
        for key in grouped:
            if key in {"follow_up_due", "scheduled_follow_up"}:
                continue
            grouped[key] = self._sort_by_board_order(grouped.get(key, []))
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
                "ready": sum(1 for task in tasks if task.status == "READY"),
                "waiting": sum(1 for task in tasks if task.status == "WAITING"),
                "follow_up": sum(
                    1 for task in tasks
                    if task.status == "WAITING"
                    and task.waiting_follow_up_date is not None
                    and task.waiting_follow_up_date <= today
                ),
                "missing_follow_up": sum(
                    1 for task in tasks
                    if task.status == "WAITING"
                    and task.waiting_follow_up_date is None
                ),
                "upcoming_follow_up": sum(
                    1 for task in tasks
                    if task.status == "WAITING"
                    and task.waiting_follow_up_date is not None
                    and task.waiting_follow_up_date > today
                ),
                "overdue": sum(
                    1 for task in tasks
                    if task.due_date is not None and task.due_date < today
                ),
                "due_today": sum(1 for task in tasks if task.due_date == today),
            }
        finally:
            session.close()

    @staticmethod
    def _is_waiting_follow_up_due(task, today=None):
        today = today or date.today()
        follow_up = task.get("waiting_follow_up_date")
        return (
            task.get("status") == "WAITING"
            and follow_up is not None
            and follow_up <= today
        )

    @staticmethod
    def _is_waiting_missing_follow_up(task):
        return (
            task.get("status") == "WAITING"
            and task.get("waiting_follow_up_date") is None
        )

    @staticmethod
    def _is_waiting_follow_up_upcoming(task, today=None):
        today = today or date.today()
        follow_up = task.get("waiting_follow_up_date")
        return (
            task.get("status") == "WAITING"
            and follow_up is not None
            and follow_up > today
        )

    @staticmethod
    def _sort_by_waiting_follow_up(tasks):
        return sorted(
            tasks,
            key=lambda task: (
                task.get("waiting_follow_up_date") or date.max,
                task["title"].casefold(),
            ),
        )

    @staticmethod
    def _sort_by_board_order(tasks):
        return sorted(
            tasks,
            key=lambda task: (
                task.get("board_position") is None,
                task.get("board_position") if task.get("board_position") is not None else 0,
                task.get("due_date") or date.max,
                task.get("title", "").casefold(),
                task.get("id") or 0,
            ),
        )

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
                    "name": self._group_display_name(group),
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
            "todo_tasks": counts["todo"],
            "ready_tasks": counts["ready"],
            "waiting_tasks": counts["waiting"],
            "done_tasks": done,
            "total_tasks": total,
            "progress": f"{done}/{total} done" if total else "0/0 done",
        }

    def _task_snapshot(self, task, session, context=None):
        context = context or {}
        project_title = context.get("project_titles", {}).get(task.project_id, "")
        missionary_ids = []
        missionary_names = []
        cached_scope = context.get("task_missionary_scope", {}).get(task.id)
        if cached_scope is not None:
            missionary_ids, missionary_names = cached_scope
        else:
            missionary_ids, missionary_names = self._task_missionary_scope(task, session)
        missionary_name = missionary_names[0] if len(missionary_names) == 1 else ""
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
            "group_type": (
                context.get("group_types", {}).get(task.group_id, "")
                if task.group_id
                else self._task_group_type(task, session)
            ),
            "scope_label": scope_label,
            "is_group_task": len(missionary_ids) > 1,
            "appointment_field": task.appointment_field,
            "task_type": task.task_type or "CUSTOM",
            "task_type_label": TASK_TYPE_LABELS.get(
                task.task_type or "CUSTOM",
                (task.task_type or "Custom").title(),
            ),
            "board_lane": task.board_lane or "",
            "board_position": task.board_position,
            "related_stage": task.related_stage or "",
            "related_document_type": task.related_document_type,
            "related_document_label": document_label(
                task.related_document_type,
            ),
            "automation_key": task.automation_key,
            "automation_source": task.automation_source,
            "automation_status_reason": task.automation_status_reason or "",
            "appointment_label": APPOINTMENT_FIELD_LABELS.get(
                task.appointment_field,
                "",
            ),
            "waiting_reason": task.waiting_reason,
            "waiting_reason_label": WAITING_REASON_LABELS.get(
                task.waiting_reason,
                "",
            ),
            "waiting_follow_up_date": task.waiting_follow_up_date,
            "waiting_follow_up_label": self._waiting_follow_up_label(
                task.waiting_follow_up_date,
            ),
            "waiting_follow_up_status_label": (
                self._waiting_follow_up_status_label(
                    task.status,
                    task.waiting_follow_up_date,
                )
            ),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "completed_at": task.completed_at,
        }

    def _workspace_missionaries(self, task, session, today):
        missionary_ids, _names = self._task_missionary_scope(task, session)
        if not missionary_ids:
            return []

        document_state = self._related_document_state(
            session,
            missionary_ids,
            task.related_document_type,
        )

        missionaries = (
            session.query(Missionary)
            .filter(Missionary.id.in_(missionary_ids))
            .order_by(Missionary.full_name)
            .all()
        )
        return [
            self._workspace_missionary_snapshot(
                missionary,
                task,
                today,
                document_state.get(missionary.id),
            )
            for missionary in missionaries
        ]

    def _workspace_missionary_snapshot(
        self,
        missionary,
        task,
        today,
        related_document_state=None,
    ):
        flags = self._workspace_missionary_flags(
            missionary,
            task,
            today,
            related_document_state,
        )
        related_stage = task.related_stage or ""
        related_stage_matches = None
        if related_stage:
            related_stage_matches = (
                (missionary.current_stage or "").casefold()
                == related_stage.casefold()
            )
        document_uploaded = None
        document_verified = None
        document_status = ""
        if task.related_document_type:
            document_uploaded = bool(
                related_document_state
                and related_document_state.get("uploaded")
            )
            document_verified = bool(
                related_document_state
                and related_document_state.get("verified")
            )
            label = document_label(task.related_document_type)
            if document_uploaded:
                document_status = (
                    f"{label} uploaded and verified"
                    if document_verified
                    else f"{label} uploaded"
                )
            else:
                document_status = f"{label} missing"
        return {
            "id": missionary.id,
            "name": missionary.full_name,
            "current_stage": missionary.current_stage or "",
            "nationality": missionary.nationality or "",
            "passport_number": missionary.passport_number or "",
            "carnet_number": missionary.carnet_number or "",
            "visa_expiration": missionary.visa_expiration,
            "visa_expiration_text": self._format_workspace_date(
                missionary.visa_expiration
            ),
            "residency_expiration": missionary.residency_expiration,
            "residency_expiration_text": self._format_workspace_date(
                missionary.residency_expiration
            ),
            "prorroga_expiration": missionary.prorroga_expiration,
            "prorroga_expiration_text": self._format_workspace_date(
                missionary.prorroga_expiration
            ),
            "related_stage": related_stage,
            "related_stage_matches": related_stage_matches,
            "related_document_type": task.related_document_type,
            "related_document_label": document_label(task.related_document_type),
            "related_document_uploaded": document_uploaded,
            "related_document_verified": document_verified,
            "related_document_status": document_status,
            "issue_flags": flags,
            "issue_summary": ", ".join(flags) if flags else "Review record",
        }

    def _workspace_missionary_flags(
        self,
        missionary,
        task,
        today,
        related_document_state=None,
    ):
        title = (task.title or "").casefold()
        key = (task.automation_key or "").casefold()
        flags = []

        if "prorroga" in title or "prorroga" in key:
            if missionary.residency_expiration:
                days = (missionary.residency_expiration - today).days
                if days < 0:
                    flags.append("Residency expired")
                elif days <= 30:
                    flags.append("Residency expires soon")
            else:
                flags.append("Missing residency date")
            if not missionary.prorroga_expiration:
                flags.append("Missing Prorroga confirmation")

        if "gvm" in title or "travel connect" in title or key.startswith("gvm:"):
            flags.append("Needs GVM update")

        if task.appointment_field:
            flags.append("Appointment follow-up")

        if task.related_stage:
            if (
                (missionary.current_stage or "").casefold()
                == task.related_stage.casefold()
            ):
                flags.append(f"Stage: {task.related_stage.title()}")
            else:
                flags.append(
                    "Stage mismatch: "
                    f"{missionary.current_stage or 'Not set'}"
                )

        if task.related_document_type:
            label = document_label(task.related_document_type)
            if related_document_state and related_document_state.get("uploaded"):
                flags.append(f"{label} uploaded")
            else:
                flags.append(f"Missing {label}")

        return flags

    @staticmethod
    def _related_document_state(session, missionary_ids, related_document_type):
        if not related_document_type or not missionary_ids:
            return {}
        rows = (
            session.query(Document.missionary_id, Document.verified)
            .filter(
                Document.missionary_id.in_(missionary_ids),
                Document.document_type == related_document_type,
                Document.status == "ACTIVE",
            )
            .all()
        )
        state = {}
        for missionary_id, verified in rows:
            existing = state.setdefault(
                missionary_id,
                {"uploaded": False, "verified": False},
            )
            existing["uploaded"] = True
            existing["verified"] = existing["verified"] or bool(verified)
        return state

    @staticmethod
    def _workspace_classification_context(snapshot, affected):
        related_document_label = snapshot.get("related_document_label") or ""
        related_stage = snapshot.get("related_stage") or ""
        count = len(affected)

        uploaded_count = sum(
            1 for item in affected
            if item.get("related_document_uploaded") is True
        )
        missing_count = sum(
            1 for item in affected
            if item.get("related_document_uploaded") is False
        )
        stage_match_count = sum(
            1 for item in affected
            if item.get("related_stage_matches") is True
        )
        stage_mismatch_count = sum(
            1 for item in affected
            if item.get("related_stage_matches") is False
        )

        document_summary = ""
        if related_document_label:
            if count:
                document_summary = (
                    f"{related_document_label}: {uploaded_count}/{count} "
                    "uploaded"
                )
            else:
                document_summary = related_document_label

        stage_summary = ""
        if related_stage:
            if count:
                stage_summary = (
                    f"{stage_match_count}/{count} in {related_stage.title()}"
                )
            else:
                stage_summary = related_stage.title()

        return {
            "task_type": snapshot.get("task_type") or "CUSTOM",
            "task_type_label": snapshot.get("task_type_label") or "Custom",
            "related_stage": related_stage,
            "related_document_label": related_document_label,
            "document_uploaded_count": uploaded_count,
            "document_missing_count": missing_count,
            "stage_match_count": stage_match_count,
            "stage_mismatch_count": stage_mismatch_count,
            "document_summary": document_summary,
            "stage_summary": stage_summary,
        }

    def _workspace_evidence(self, snapshot, history=None):
        history = history or []
        evidence = [
            ("Task type", snapshot.get("task_type_label")),
            ("Related stage", snapshot.get("related_stage")),
            ("Related document", snapshot.get("related_document_label")),
            (
                "Waiting follow-up",
                snapshot.get("waiting_follow_up_status_label"),
            ),
            (
                "Last status change",
                history[0]["summary"] if history else "",
            ),
            ("Automation source", snapshot.get("automation_source")),
            ("Automation key", snapshot.get("automation_key")),
            ("Automation status", snapshot.get("automation_status_reason")),
            ("Created", snapshot.get("created_at")),
            ("Updated", snapshot.get("updated_at")),
        ]
        return [
            {
                "label": label,
                "value": self._format_workspace_value(value),
            }
            for label, value in evidence
            if value
        ]

    @staticmethod
    def _waiting_follow_up_label(value):
        if not value:
            return ""
        return f"Follow up {value.strftime('%b %d, %Y')}"

    @classmethod
    def _waiting_follow_up_status_label(cls, status, value):
        if status != "WAITING":
            return ""
        return cls._waiting_follow_up_label(value) or "No follow-up date"

    @staticmethod
    def _add_task_history(
        session,
        task_id,
        event_type,
        old_value,
        new_value,
        note=None,
    ):
        session.add(
            SecretaryTaskHistory(
                task_id=task_id,
                event_type=event_type,
                old_value=old_value,
                new_value=new_value,
                note=note,
            )
        )

    def _task_history_items(self, task_id, session, limit=6):
        rows = (
            session.query(SecretaryTaskHistory)
            .filter_by(task_id=task_id)
            .order_by(
                SecretaryTaskHistory.created_at.desc(),
                SecretaryTaskHistory.id.desc(),
            )
            .limit(limit)
            .all()
        )
        return [
            {
                "id": row.id,
                "event_type": row.event_type,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "note": row.note or "",
                "created_at": row.created_at,
                "created_at_text": self._format_workspace_value(row.created_at),
                "summary": self._task_history_summary(row),
            }
            for row in rows
        ]

    def _task_history_summary(self, row):
        if row.event_type == "STATUS":
            old_label = self._status_label(row.old_value)
            new_label = self._status_label(row.new_value)
            if row.old_value:
                return f"{old_label} -> {new_label}"
            return f"Created as {new_label}"
        return row.note or row.event_type.title()

    @staticmethod
    def _status_label(status):
        return {
            "OPEN": "To Do",
            "READY": "Ready",
            "WAITING": "Waiting",
            "DONE": "Done",
            "ARCHIVED": "Archived",
        }.get(status or "", status or "")

    def _workspace_brief_text(
        self,
        snapshot,
        affected,
        days,
        classification=None,
    ):
        classification = classification or {}
        count = len(affected)
        timing = self._workspace_timing(days).lower()
        title = (snapshot.get("title") or "task").casefold()
        key = (snapshot.get("automation_key") or "").casefold()

        if snapshot.get("status") == "READY":
            document_summary = classification.get("document_summary")
            if document_summary:
                return f"Ready to review: {document_summary}."
            return (
                "Ready to review: this task has been marked ready for "
                "secretary action."
            )

        if "prorroga" in title or "prorroga" in key:
            return (
                f"Prorroga follow-up is {timing} for "
                f"{count or 'the linked'} missionary record"
                f"{'s' if count != 1 else ''}."
            )

        if "gvm" in title or "travel connect" in title or key.startswith("gvm:"):
            return (
                f"Travel Connect/GVM needs an update for "
                f"{count or 'the linked'} missionary record"
                f"{'s' if count != 1 else ''}."
            )

        if snapshot.get("automation_source"):
            linked = (
                f" for {count} linked missionary record"
                f"{'s' if count != 1 else ''}"
                if count
                else ""
            )
            return f"Process automation found a task that is {timing}{linked}."

        if days is not None:
            return f"This task is {timing}."
        return "This task needs review."

    def _workspace_why_text(
        self,
        snapshot,
        affected,
        days,
        classification=None,
    ):
        classification = classification or {}
        title = snapshot.get("title") or "This task"
        description = snapshot.get("description") or ""
        count = len(affected)
        title_key = title.casefold()
        automation_key = (snapshot.get("automation_key") or "").casefold()

        if snapshot.get("status") == "READY":
            parts = [
                "This task is marked Ready, so the needed pieces should be "
                "available and it needs secretary review or action."
            ]
            if classification.get("document_summary"):
                parts.append(classification["document_summary"] + ".")
            if classification.get("stage_summary"):
                parts.append(classification["stage_summary"] + ".")
            if description:
                parts.append(description)
            return " ".join(parts)

        if "prorroga" in title_key or "prorroga" in automation_key:
            return (
                "The system is asking for attention because Prorroga follow-up "
                "is due or overdue and the linked records still need "
                "confirmation."
            )

        if "gvm" in title_key or "travel connect" in title_key:
            return (
                "The system is asking for attention because a missionary "
                "record has information that should be reflected in Travel "
                "Connect/GVM."
            )

        if snapshot.get("automation_source"):
            scope = (
                f" for {count} missionaries"
                if count != 1
                else " for 1 missionary"
            ) if count else ""
            timing = (
                f" It is {abs(days)} day(s) overdue."
                if days is not None and days < 0
                else " It is due today."
                if days == 0
                else ""
            )
            return (
                f"This alert was created by process automation{scope}. "
                f"{title}{timing}"
            )

        if description:
            return description

        if days is not None and days < 0:
            return (
                "This task was created manually and is overdue based on its "
                "due date."
            )
        if days == 0:
            return (
                "This task was created manually and is due today based on its "
                "due date."
            )
        return (
            "This task was created manually. Review the task details, resolve "
            "the needed work, then mark it done."
        )

    def _workspace_why_points(
        self,
        snapshot,
        affected,
        days,
        classification=None,
    ):
        classification = classification or {}
        points = []
        if snapshot.get("status") == "READY":
            points.append("Ready to review")
        if classification.get("task_type_label"):
            points.append(classification["task_type_label"])
        if classification.get("document_summary"):
            points.append(classification["document_summary"])
        if classification.get("stage_summary"):
            points.append(classification["stage_summary"])
        if snapshot.get("waiting_follow_up_status_label"):
            points.append(snapshot["waiting_follow_up_status_label"])
        if days is not None:
            points.append(self._workspace_timing(days))
        if affected:
            points.append(
                f"{len(affected)} linked missionary record"
                f"{'s' if len(affected) != 1 else ''}"
            )
        if snapshot.get("group_scope_label"):
            points.append(snapshot["group_scope_label"])
        if snapshot.get("automation_source"):
            points.append("Created by process automation")
        elif snapshot.get("description"):
            points.append("Manual task with notes")
        return points

    def _workspace_key_facts(
        self,
        snapshot,
        affected,
        days,
        classification=None,
    ):
        classification = classification or {}
        facts = [
            {
                "label": "Due",
                "value": self._workspace_timing(days),
                "color": "#DC2626"
                if days is not None and days < 0
                else "#2563EB",
            },
            {
                "label": "Affected",
                "value": str(len(affected)),
                "color": "#0F766E",
            },
            {
                "label": "Status",
                "value": (snapshot.get("status") or "").title(),
                "color": "#2563EB",
            },
            {
                "label": "Priority",
                "value": (snapshot.get("priority") or "").title(),
                "color": (
                    "#DC2626"
                    if snapshot.get("priority") == "CRITICAL"
                    else "#D97706"
                    if snapshot.get("priority") == "IMPORTANT"
                    else "#71717A"
                ),
            },
        ]
        if snapshot.get("group_scope_label"):
            facts.append({
                "label": "Group",
                "value": snapshot["group_scope_label"],
                "color": "#71717A",
            })
        if snapshot.get("waiting_follow_up_status_label"):
            facts.append({
                "label": "Follow-up",
                "value": snapshot["waiting_follow_up_status_label"],
                "color": "#D97706",
            })
        if classification.get("document_summary"):
            facts.append({
                "label": "Document",
                "value": classification["document_summary"],
                "color": "#059669"
                if classification.get("document_missing_count") == 0
                else "#D97706",
            })
        if classification.get("stage_summary"):
            facts.append({
                "label": "Stage",
                "value": classification["stage_summary"],
                "color": "#059669"
                if classification.get("stage_mismatch_count") == 0
                else "#D97706",
            })
        return facts

    @staticmethod
    def _workspace_recommended_steps(snapshot, classification=None):
        classification = classification or {}
        title = (snapshot.get("title") or "").casefold()
        key = (snapshot.get("automation_key") or "").casefold()
        related_document = classification.get("related_document_label")
        related_stage = classification.get("related_stage")

        if snapshot.get("status") == "WAITING":
            steps = ["Check what this task is waiting on."]
            if snapshot.get("waiting_follow_up_label"):
                steps.append(
                    f"Use the waiting follow-up date: "
                    f"{snapshot['waiting_follow_up_label']}."
                )
            else:
                steps.append(
                    "Set a waiting follow-up date so this task is checked again."
                )
            steps.extend([
                "Update the waiting reason or notes if the situation changed.",
                "Mark Ready when the needed pieces are available.",
            ])
            return steps

        if snapshot.get("status") == "READY" and (
            related_document or related_stage
        ):
            steps = ["Review the ready task and confirm the linked records."]
            if related_document:
                steps.append(
                    f"Open and verify the {related_document} for each "
                    "affected missionary."
                )
                if classification.get("document_missing_count"):
                    steps.append(
                        "If the document is still missing, move the task to "
                        "Waiting and choose the right waiting reason."
                    )
            if related_stage:
                steps.append(
                    f"Confirm each affected missionary is in the "
                    f"{related_stage.title()} stage or update the task scope."
                )
            steps.append("Mark this task done after review/action is complete.")
            return steps

        if "prorroga" in title or "prorroga" in key:
            return [
                "Review each affected missionary record.",
                "Confirm whether Prorroga was submitted or approved.",
                "Upload or update Prorroga confirmation if available.",
                "Mark this alert done when the records are resolved.",
            ]

        if "gvm" in title or "travel connect" in title or key.startswith("gvm:"):
            return [
                "Open the affected missionary record.",
                "Confirm the latest document information is available.",
                "Update Travel Connect/GVM as needed.",
                "Mark this task done after the external system is updated.",
            ]

        if snapshot.get("appointment_label"):
            return [
                "Open the affected missionary record.",
                "Confirm the appointment outcome and related documents.",
                "Upload or update any missing follow-up information.",
                "Mark this task done when the follow-up is complete.",
            ]

        return [
            "Review the task details and affected records.",
            "Complete the needed follow-up work.",
            "Add notes or edit the task if more context is needed.",
            "Mark this task done when the work is resolved.",
        ]

    @staticmethod
    def _workspace_timing(days):
        if days is None:
            return "No due date"
        if days < 0:
            return f"{abs(days)} day(s) overdue"
        if days == 0:
            return "Due today"
        return f"Due in {days} day(s)"

    @staticmethod
    def _format_workspace_date(value):
        if not value:
            return "Not set"
        return value.strftime("%b %d, %Y")

    def _format_workspace_value(self, value):
        if hasattr(value, "strftime"):
            return self._format_workspace_date(value)
        return str(value)

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

    @staticmethod
    def _group_display_name(group):
        name = group.name or ""
        if group.group_type == TEMPORARY_GROUP_TYPE:
            return f"{name} [Temporary]"
        return name

    @staticmethod
    def _task_group_type(task, session):
        if not task.group_id:
            return ""
        group = session.query(MissionaryGroup).filter_by(id=task.group_id).first()
        return group.group_type if group else ""

    def _replace_task_missionaries(self, session, task_id, missionary_ids):
        session.query(SecretaryTaskMissionary).filter_by(task_id=task_id).delete()
        for missionary_id in _unique_ids(missionary_ids):
            session.add(
                SecretaryTaskMissionary(
                    task_id=task_id,
                    missionary_id=missionary_id,
                )
            )

    def _replace_group_members(self, session, group_id, missionary_ids):
        session.query(MissionaryGroupMember).filter_by(group_id=group_id).delete()
        for missionary_id in _unique_ids(missionary_ids):
            session.add(
                MissionaryGroupMember(
                    group_id=group_id,
                    missionary_id=missionary_id,
                )
            )

    def _cleanup_temporary_group_in_session(self, session, task, group=None):
        if task.group_id is None:
            return
        group = group or session.query(MissionaryGroup).filter_by(
            id=task.group_id
        ).first()
        if group is None or group.group_type != TEMPORARY_GROUP_TYPE:
            return
        task.group_scope_label = task.group_scope_label or group.name
        task.group_id = None
        session.query(MissionaryGroupMember).filter_by(group_id=group.id).delete()
        session.delete(group)

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
        todo = sum(1 for task in tasks if task.status == "OPEN")
        ready = sum(1 for task in tasks if task.status == "READY")
        waiting = sum(1 for task in tasks if task.status == "WAITING")
        open_count = todo + ready + waiting
        return {
            "done": done,
            "open": open_count,
            "todo": todo,
            "ready": ready,
            "waiting": waiting,
            "total": len([task for task in tasks if task.status != "ARCHIVED"]),
        }

    def _snapshot_for_task_id(self, task_id):
        session = SessionLocal()
        try:
            task = session.query(SecretaryTask).filter_by(id=task_id).first()
            if task is None:
                raise SecretaryWorkError("Task not found.")
            return self._task_snapshot(task, session)
        finally:
            session.close()
