from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String

from sqlalchemy.sql import func

from database.base import Base


class ResidencyEvent(Base):
    __tablename__ = "residency_events"
    __table_args__ = (
        Index(
            "uq_residency_event_identity",
            "missionary_id",
            "event_type",
            "sequence_number",
            unique=True,
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
    )

    missionary_id = Column(
        Integer,
        ForeignKey("missionaries.id"),
        nullable=False,
    )

    event_type = Column(
        String,
        nullable=False,
    )

    sequence_number = Column(
        Integer,
        nullable=False,
    )

    status = Column(
        String,
        default="APPROVED",
    )

    document_id = Column(
        Integer,
        ForeignKey("documents.id"),
        nullable=True,
    )

    approved_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    notes = Column(
        String,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
