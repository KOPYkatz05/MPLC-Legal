import uuid

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String

from sqlalchemy.sql import func

from database.base import Base


APPOINTMENT_STATUS_SCHEDULED = "SCHEDULED"
APPOINTMENT_STATUS_COMPLETED = "COMPLETED"
APPOINTMENT_STATUS_MISSED = "MISSED"

APPOINTMENT_STATUSES = (
    APPOINTMENT_STATUS_SCHEDULED,
    APPOINTMENT_STATUS_COMPLETED,
    APPOINTMENT_STATUS_MISSED,
)


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(
        Integer,
        primary_key=True,
    )

    appointment_uid = Column(
        String,
        default=lambda: uuid.uuid4().hex,
        unique=True,
        nullable=False,
    )

    missionary_id = Column(
        Integer,
        ForeignKey("missionaries.id"),
        nullable=False,
    )

    appointment_field = Column(
        String,
        nullable=False,
    )

    appointment_type = Column(
        String,
        nullable=False,
    )

    scheduled_date = Column(
        Date,
        nullable=False,
    )

    status = Column(
        String,
        default=APPOINTMENT_STATUS_SCHEDULED,
        nullable=False,
    )

    marked_at = Column(
        DateTime(timezone=True),
    )

    closed_at = Column(
        DateTime(timezone=True),
    )

    status_reason = Column(
        String,
    )

    superseded_by_uid = Column(
        String,
    )

    notes = Column(
        String,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


Index(
    "idx_appointments_scheduled_unique",
    Appointment.missionary_id,
    Appointment.appointment_field,
    Appointment.scheduled_date,
    unique=True,
    sqlite_where=Appointment.status == APPOINTMENT_STATUS_SCHEDULED,
)
