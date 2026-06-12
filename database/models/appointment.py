from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String

from sqlalchemy.sql import func

from database.db import Base


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
