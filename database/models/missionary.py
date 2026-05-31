from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Date
from sqlalchemy import DateTime

from sqlalchemy.sql import func

from database.db import Base


class Missionary(Base):
    __tablename__ = "missionaries"

    # ======================================
    # Primary Identity
    # ======================================

    id = Column(
        Integer,
        primary_key=True
    )

    status = Column(
        String,
        default="ACTIVE"
    )

    # ======================================
    # Basic Information
    # ======================================

    full_name = Column(
        String,
        nullable=False
    )

    preferred_name = Column(
        String
    )

    nationality = Column(
        String
    )

    passport_number = Column(
        String
    )

    # ======================================
    # Process Tracking
    # ======================================

    current_stage = Column(
        String,
        default="INTERPOL"
    )

    notes = Column(
        String
    )

    # ======================================
    # Date Tracking
    # ======================================

    arrival_date = Column(
        Date
    )

    visa_expiration = Column(
        Date
    )

    residency_expiration = Column(
        Date
    )

    prorroga_expiration = Column(
        Date
    )

    carnet_issue_date = Column(
        Date
    )

    cancelacion_date = Column(
        Date
    )

    passport_expiration = Column(
        Date
    )

    # ======================================
    # File System
    # ======================================

    folder_path = Column(
        String
    )

    # ======================================
    # Audit
    # ======================================

    deleted_at = Column(
        DateTime(timezone=True),
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )