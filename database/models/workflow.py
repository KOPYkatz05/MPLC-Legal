from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import ForeignKey

from database.db import Base


class WorkflowStage(Base):
    __tablename__ = "workflow_stages"

    # ======================================
    # Primary Identity
    # ======================================

    id = Column(
        Integer,
        primary_key=True
    )

    # ======================================
    # Relationships
    # ======================================

    missionary_id = Column(
        Integer,
        ForeignKey("missionaries.id"),
        nullable=False,
    )

    # ======================================
    # Workflow Information
    # ======================================

    stage_name = Column(
        String,
        nullable=False,
    )

    status = Column(
        String,
        default="NOT STARTED"
    )