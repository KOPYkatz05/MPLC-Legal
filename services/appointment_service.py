from datetime import datetime

from database.db import SessionLocal
from database.models.appointment import (
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
    APPOINTMENT_STATUS_SCHEDULED,
    Appointment,
)
from database.models.document import Document
from database.models.missionary import Missionary
from services.secretary_work_service import SecretaryWorkService
from utils.logger import logger


APPOINTMENT_DEFINITIONS = {
    "interpol_appointment_date": {
        "type": "Interpol",
        "follow_up_title": (
            "Get new Interpol pago and schedule new Interpol appointment"
        ),
        "stale_documents": [
            "PAGO_INTERPOL",
            "CONSTANCIA_DE_CITA_INTERPOL",
        ],
    },
    "biometric_appointment_date": {
        "type": "Biometric",
        "follow_up_title": (
            "Get new Biometric pago and schedule new Biometric appointment"
        ),
        "stale_documents": [
            "PAGO_CARNE_DE_EXTRANJERIA",
            "CONSTANCIA_DE_CITA_BIOMETRICO",
        ],
    },
    "pickup_appointment_date": {
        "type": "Pickup",
        "follow_up_title": "Get new Pickup cita and schedule new Pickup appointment",
        "stale_documents": [
            "CITA_RECOJO",
        ],
    },
}

APPOINTMENT_FIELDS = tuple(APPOINTMENT_DEFINITIONS.keys())
APPOINTMENT_HISTORY_STATUSES = (
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
)


class AppointmentService:
    def __init__(self):
        self.secretary_work_service = SecretaryWorkService()

    def sync_from_missionary_dates(self, missionary_id, fields=None):
        fields = [
            field
            for field in (fields or APPOINTMENT_FIELDS)
            if field in APPOINTMENT_DEFINITIONS
        ]
        if not fields:
            return []

        session = SessionLocal()
        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )
            if missionary is None:
                return []

            created = []
            for field in fields:
                scheduled_date = getattr(missionary, field, None)
                if scheduled_date is None:
                    continue

                now = datetime.now()
                (
                    session.query(Appointment)
                    .filter(
                        Appointment.missionary_id == missionary.id,
                        Appointment.appointment_field == field,
                        Appointment.status == APPOINTMENT_STATUS_SCHEDULED,
                        Appointment.scheduled_date != scheduled_date,
                    )
                    .update(
                        {
                            Appointment.status: APPOINTMENT_STATUS_MISSED,
                            Appointment.marked_at: now,
                            Appointment.closed_at: now,
                            Appointment.updated_at: now,
                            Appointment.status_reason: (
                                "Replaced by updated missionary appointment date"
                            ),
                        },
                        synchronize_session=False,
                    )
                )

                existing = (
                    session.query(Appointment)
                    .filter_by(
                        missionary_id=missionary.id,
                        appointment_field=field,
                        scheduled_date=scheduled_date,
                        status=APPOINTMENT_STATUS_SCHEDULED,
                    )
                    .first()
                )
                if existing is not None:
                    continue

                appointment = Appointment(
                    missionary_id=missionary.id,
                    appointment_field=field,
                    appointment_type=APPOINTMENT_DEFINITIONS[field]["type"],
                    scheduled_date=scheduled_date,
                    status=APPOINTMENT_STATUS_SCHEDULED,
                )
                session.add(appointment)
                created.append(appointment)

            session.commit()
            return created
        except Exception:
            session.rollback()
            logger.exception("Failed to sync appointment dates")
            raise
        finally:
            session.close()

    def list_scheduled_appointments(self):
        return self._list_appointments_by_statuses(
            (APPOINTMENT_STATUS_SCHEDULED,),
        )

    def list_history_appointments(self):
        return self._list_appointments_by_statuses(
            APPOINTMENT_HISTORY_STATUSES,
            newest_first=True,
        )

    def _list_appointments_by_statuses(self, statuses, newest_first=False):
        session = SessionLocal()
        try:
            query = (
                session.query(Appointment, Missionary)
                .join(Missionary, Appointment.missionary_id == Missionary.id)
                .filter(
                    Appointment.status.in_(tuple(statuses)),
                    Missionary.status == "ACTIVE",
                )
            )
            if newest_first:
                query = query.order_by(
                    Appointment.scheduled_date.desc(),
                    Appointment.appointment_type,
                    Missionary.full_name,
                )
            else:
                query = query.order_by(
                    Appointment.scheduled_date,
                    Appointment.appointment_type,
                    Missionary.full_name,
                )

            return [
                self._appointment_snapshot(appointment, missionary)
                for appointment, missionary in query.all()
            ]
        finally:
            session.close()

    def backfill_all(self):
        session = SessionLocal()
        try:
            missionary_ids = [
                row[0]
                for row in session.query(Missionary.id)
                .filter_by(status="ACTIVE")
                .all()
            ]
        finally:
            session.close()

        for missionary_id in missionary_ids:
            self.sync_from_missionary_dates(missionary_id)

    def complete_appointment(self, appointment_id):
        return self._mark_appointment(
            appointment_id,
            APPOINTMENT_STATUS_COMPLETED,
        )

    def miss_appointment(self, appointment_id):
        return self._mark_appointment(
            appointment_id,
            APPOINTMENT_STATUS_MISSED,
            create_follow_up=True,
            invalidate_documents=True,
        )

    def _mark_appointment(
        self,
        appointment_id,
        status,
        create_follow_up=False,
        invalidate_documents=False,
        status_reason=None,
    ):
        session = SessionLocal()
        try:
            appointment = (
                session.query(Appointment)
                .filter_by(id=appointment_id)
                .first()
            )
            if appointment is None:
                raise ValueError("Appointment not found.")

            missionary = (
                session.query(Missionary)
                .filter_by(id=appointment.missionary_id)
                .first()
            )
            if missionary is None:
                raise ValueError("Missionary not found.")

            if appointment.status != APPOINTMENT_STATUS_SCHEDULED:
                raise ValueError("Appointment is already closed.")

            now = datetime.now()
            appointment.status = status
            appointment.marked_at = now
            appointment.closed_at = now
            appointment.updated_at = now
            appointment.status_reason = status_reason

            if (
                hasattr(missionary, appointment.appointment_field)
                and getattr(missionary, appointment.appointment_field)
                == appointment.scheduled_date
            ):
                setattr(missionary, appointment.appointment_field, None)

            if invalidate_documents:
                self._invalidate_documents(
                    session,
                    appointment,
                )

            session.commit()

            if create_follow_up:
                self._create_follow_up_task(
                    missionary,
                    appointment,
                )

            return appointment
        except Exception:
            session.rollback()
            logger.exception("Failed to mark appointment")
            raise
        finally:
            session.close()

    def _invalidate_documents(self, session, appointment):
        definition = APPOINTMENT_DEFINITIONS.get(
            appointment.appointment_field,
            {},
        )
        stale_documents = definition.get("stale_documents", [])
        if not stale_documents:
            return

        now = datetime.now()
        reason = (
            f"{appointment.appointment_type} appointment missed on "
            f"{appointment.scheduled_date.isoformat()}"
        )
        (
            session.query(Document)
            .filter(
                Document.missionary_id == appointment.missionary_id,
                Document.document_type.in_(stale_documents),
                Document.status == "ACTIVE",
            )
            .update(
                {
                    Document.status: "STALE",
                    Document.invalidated_at: now,
                    Document.invalidated_reason: reason,
                },
                synchronize_session=False,
            )
        )

    def _create_follow_up_task(self, missionary, appointment):
        definition = APPOINTMENT_DEFINITIONS.get(
            appointment.appointment_field,
            {},
        )
        title = definition.get("follow_up_title") or (
            f"Schedule new {appointment.appointment_type} appointment"
        )
        description = (
            f"{appointment.appointment_type} appointment for "
            f"{missionary.full_name} was missed on "
            f"{appointment.scheduled_date.strftime('%B %d, %Y')}. "
            "Upload the replacement pago/cita and schedule a new appointment."
        )
        self.secretary_work_service.create_task(
            title,
            description=description,
            priority="IMPORTANT",
            missionary_id=missionary.id,
            appointment_field=appointment.appointment_field,
        )

    def _appointment_snapshot(self, appointment, missionary):
        return {
            "id": appointment.id,
            "appointment_uid": appointment.appointment_uid,
            "missionary_id": missionary.id,
            "full_name": missionary.full_name or "",
            "current_stage": missionary.current_stage or "",
            "appointment_field": appointment.appointment_field,
            "appointment_type": appointment.appointment_type,
            "scheduled_date": appointment.scheduled_date,
            "status": appointment.status,
            "marked_at": appointment.marked_at,
            "closed_at": appointment.closed_at,
            "status_reason": appointment.status_reason or "",
            "superseded_by_uid": appointment.superseded_by_uid,
        }
