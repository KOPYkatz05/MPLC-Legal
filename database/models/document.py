from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index

from sqlalchemy.sql import func

from database.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("uq_documents_upload_id", "upload_id", unique=True),
    )

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

    # Portable path beneath the server-authoritative mission storage root.
    storage_relative_path = Column(
        String,
        nullable=True,
    )

    upload_id = Column(
        String,
        nullable=True,
    )

    content_sha256 = Column(
        String,
        nullable=True,
    )

    file_size = Column(
        Integer,
        nullable=True,
    )

    supersedes_document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ======================================
    # Notes
    # ======================================

    notes = Column(
        String,
        nullable=True,
    )

    status = Column(
        String,
        default="ACTIVE",
        nullable=False,
    )

    invalidated_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    invalidated_reason = Column(
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

    post_processing_status = Column(
        String,
        default="NOT_REQUIRED",
        nullable=False,
    )

    post_processing_error = Column(
        String,
        nullable=True,
    )

    post_processing_updated_fields = Column(
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
