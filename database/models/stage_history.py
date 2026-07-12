from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import ForeignKey
from sqlalchemy import DateTime

from sqlalchemy.sql import func

from database.base import Base


class StageHistory(Base):
    __tablename__ = "stage_history"

    id = Column(
        Integer,
        primary_key=True,
    )

    missionary_id = Column(
        Integer,
        ForeignKey("missionaries.id"),
        nullable=False,
    )

    from_stage = Column(
        String,
    )

    to_stage = Column(
        String,
        nullable=False,
    )

    notes = Column(
        String,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
