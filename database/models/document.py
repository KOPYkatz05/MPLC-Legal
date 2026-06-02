from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey

from sqlalchemy.sql import func

from database.db import Base


class Document(Base):
    __tablename__ = "documents"

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
    # Document Metadata
    # ======================================

    document_type = Column(
        String,
        nullable=False,
    )

    workflow_stage = Column(
        String,
        nullable=True,
    )

    verified = Column(
        Boolean,
        default=False,
    )

    # ======================================
    # File Information
    # ======================================

    file_name = Column(
        String,
        nullable=False,
    )

    file_path = Column(
        String,
        nullable=False,
    )

    # ======================================
    # Notes
    # ======================================

    notes = Column(
        String,
        nullable=True,
    )

    ocr_raw_data = Column(
        String,
        nullable=True,
    )

    ocr_confirmed_data = Column(
        String,
        nullable=True,
    )

    # ======================================
    # Audit Tracking
    # ======================================

    uploaded_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )