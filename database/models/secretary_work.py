from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String

from sqlalchemy.sql import func

from database.db import Base


TASK_STATUSES = ("OPEN", "WAITING", "DONE", "ARCHIVED")
PROJECT_STATUSES = ("ACTIVE", "WAITING", "DONE", "ARCHIVED")
PRIORITIES = ("LOW", "NORMAL", "IMPORTANT", "CRITICAL")
WAITING_REASONS = (
    "MISSIONARY",
    "GOVERNMENT_SITE",
    "PAYMENT",
    "DOCUMENT",
    "APPOINTMENT_DATE",
    "OTHER",
)


class SecretaryProject(Base):
    __tablename__ = "secretary_projects"

    id = Column(
        Integer,
        primary_key=True,
    )

    title = Column(
        String,
        nullable=False,
    )

    description = Column(
        String,
    )

    status = Column(
        String,
        default="ACTIVE",
        nullable=False,
    )

    priority = Column(
        String,
        default="NORMAL",
        nullable=False,
    )

    due_date = Column(
        Date,
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

    completed_at = Column(
        DateTime(timezone=True),
    )


class MissionaryGroup(Base):
    __tablename__ = "missionary_groups"

    id = Column(
        Integer,
        primary_key=True,
    )

    name = Column(
        String,
        nullable=False,
    )

    description = Column(
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


class MissionaryGroupMember(Base):
    __tablename__ = "missionary_group_members"

    group_id = Column(
        Integer,
        ForeignKey("missionary_groups.id"),
        primary_key=True,
    )

    missionary_id = Column(
        Integer,
        ForeignKey("missionaries.id"),
        primary_key=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class SecretaryTaskMissionary(Base):
    __tablename__ = "secretary_task_missionaries"

    task_id = Column(
        Integer,
        ForeignKey("secretary_tasks.id"),
        primary_key=True,
    )

    missionary_id = Column(
        Integer,
        ForeignKey("missionaries.id"),
        primary_key=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class SecretaryTask(Base):
    __tablename__ = "secretary_tasks"

    id = Column(
        Integer,
        primary_key=True,
    )

    title = Column(
        String,
        nullable=False,
    )

    description = Column(
        String,
    )

    status = Column(
        String,
        default="OPEN",
        nullable=False,
    )

    priority = Column(
        String,
        default="NORMAL",
        nullable=False,
    )

    due_date = Column(
        Date,
    )

    project_id = Column(
        Integer,
        ForeignKey("secretary_projects.id"),
    )

    missionary_id = Column(
        Integer,
        ForeignKey("missionaries.id"),
    )

    group_id = Column(
        Integer,
        ForeignKey("missionary_groups.id"),
    )

    group_scope_label = Column(
        String,
    )

    appointment_field = Column(
        String,
    )

    waiting_reason = Column(
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

    completed_at = Column(
        DateTime(timezone=True),
    )
