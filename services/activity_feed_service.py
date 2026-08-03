"""Server-authoritative missionary activity feed read model."""

from sqlalchemy import or_

from database.db import SessionLocal
from database.models.appointment import Appointment
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.residency_event import ResidencyEvent
from database.models.secretary_work import (
    SecretaryTask,
    SecretaryTaskHistory,
    SecretaryTaskMissionary,
)
from database.models.stage_history import StageHistory


class ActivityFeedService:
    """Build a normalized feed from durable records owned by the server."""

    @staticmethod
    def _event(
        category,
        event_type,
        occurred_at,
        title,
        details="",
        *,
        entity_type=None,
        entity_id=None,
        **metadata,
    ):
        event = {
            "category": category,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "title": title,
            "details": details or "",
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        event.update(metadata)
        return event

    def get_missionary_activity(self, missionary_id):
        session = SessionLocal()
        try:
            missionary = (
                session.query(Missionary)
                .filter(Missionary.id == missionary_id)
                .first()
            )
            if missionary is None:
                return {"events": [], "upcoming": []}

            events = []
            upcoming = []

            if missionary.created_at:
                events.append(self._event(
                    "workflow",
                    "missionary_created",
                    missionary.created_at,
                    "Missionary record created",
                ))

            history = (
                session.query(StageHistory)
                .filter(StageHistory.missionary_id == missionary_id)
                .all()
            )
            for row in history:
                destination = row.to_stage or ""
                source = row.from_stage or ""
                title = (
                    "Missionary archived"
                    if destination == "ARCHIVED"
                    else f"Advanced to {destination}"
                )
                details = (
                    f"{source} to {destination}" if source else destination
                )
                if row.notes:
                    details = f"{details}\n{row.notes}" if details else row.notes
                events.append(self._event(
                    "workflow",
                    "stage_changed",
                    row.created_at,
                    title,
                    details,
                    entity_type="stage_history",
                    entity_id=row.id,
                    from_stage=source,
                    to_stage=destination,
                    notes=row.notes or "",
                ))

            documents = (
                session.query(Document)
                .filter(Document.missionary_id == missionary_id)
                .all()
            )
            for document in documents:
                if document.uploaded_at:
                    events.append(self._event(
                        "documents",
                        "document_uploaded",
                        document.uploaded_at,
                        "Document uploaded",
                        document.document_type or document.file_name,
                        entity_type="document",
                        entity_id=document.id,
                        document_type=document.document_type,
                    ))
                if document.invalidated_at:
                    events.append(self._event(
                        "documents",
                        "document_invalidated",
                        document.invalidated_at,
                        "Document invalidated",
                        document.invalidated_reason or document.document_type,
                        entity_type="document",
                        entity_id=document.id,
                        document_type=document.document_type,
                    ))

            appointments = (
                session.query(Appointment)
                .filter(Appointment.missionary_id == missionary_id)
                .all()
            )
            for appointment in appointments:
                if appointment.created_at:
                    events.append(self._event(
                        "appointments",
                        "appointment_scheduled",
                        appointment.created_at,
                        "Appointment scheduled",
                        f"{appointment.appointment_type} - {appointment.scheduled_date:%b %d, %Y}",
                        entity_type="appointment",
                        entity_id=appointment.id,
                    ))
                if appointment.closed_at:
                    verb = (
                        "completed"
                        if appointment.status == "COMPLETED"
                        else "missed"
                    )
                    events.append(self._event(
                        "appointments",
                        f"appointment_{verb}",
                        appointment.closed_at,
                        f"Appointment {verb}",
                        appointment.appointment_type,
                        entity_type="appointment",
                        entity_id=appointment.id,
                    ))
                if appointment.status == "SCHEDULED":
                    upcoming.append({
                        "category": "appointments",
                        "event_type": "upcoming_appointment",
                        "scheduled_date": appointment.scheduled_date,
                        "title": f"{appointment.appointment_type} appointment",
                        "details": "Scheduled",
                        "entity_type": "appointment",
                        "entity_id": appointment.id,
                    })

            linked_task_ids = [
                row[0]
                for row in (
                session.query(SecretaryTaskMissionary.task_id)
                .filter(SecretaryTaskMissionary.missionary_id == missionary_id)
                .all()
                )
            ]
            task_filter = SecretaryTask.missionary_id == missionary_id
            if linked_task_ids:
                task_filter = or_(
                    task_filter,
                    SecretaryTask.id.in_(linked_task_ids),
                )
            tasks = (
                session.query(SecretaryTask)
                .filter(task_filter)
                .all()
            )
            for task in tasks:
                if task.created_at:
                    events.append(self._event(
                        "tasks",
                        "task_created",
                        task.created_at,
                        "Task created",
                        task.title,
                        entity_type="task",
                        entity_id=task.id,
                    ))
                if task.completed_at:
                    events.append(self._event(
                        "tasks",
                        "task_completed",
                        task.completed_at,
                        "Task completed",
                        task.title,
                        entity_type="task",
                        entity_id=task.id,
                    ))

            task_id_values = [task.id for task in tasks]
            if task_id_values:
                task_titles = {task.id: task.title for task in tasks}
                task_history = (
                    session.query(SecretaryTaskHistory)
                    .filter(SecretaryTaskHistory.task_id.in_(task_id_values))
                    .all()
                )
                for row in task_history:
                    if row.event_type in {"CREATED", "COMPLETED"}:
                        continue
                    detail_parts = [task_titles.get(row.task_id, "")]
                    if row.note:
                        detail_parts.append(row.note)
                    events.append(self._event(
                        "tasks",
                        "task_updated",
                        row.created_at,
                        "Task updated",
                        "\n".join(part for part in detail_parts if part),
                        entity_type="task",
                        entity_id=row.task_id,
                    ))

            residency_events = (
                session.query(ResidencyEvent)
                .filter(ResidencyEvent.missionary_id == missionary_id)
                .all()
            )
            for row in residency_events:
                label = (
                    "Initial residency"
                    if row.sequence_number == 0
                    else f"Prorroga {row.sequence_number}"
                )
                events.append(self._event(
                    "residency",
                    "residency_approved",
                    row.approved_at or row.created_at,
                    "Residency approved",
                    f"{label} - {row.status}",
                    entity_type="residency_event",
                    entity_id=row.id,
                ))

            events = [event for event in events if event["occurred_at"]]
            events.sort(key=lambda event: event["occurred_at"], reverse=True)
            upcoming.sort(key=lambda event: event["scheduled_date"])
            return {"events": events, "upcoming": upcoming}
        finally:
            session.close()
