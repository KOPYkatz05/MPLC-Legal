from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Date
from sqlalchemy import DateTime

from sqlalchemy.sql import func

from database.base import Base


class Missionary(Base):
    __tablename__ = "missionaries"

    # ======================================
    # Primary Identity
    # ======================================

    id = Column(
        Integer,
        primary_key=True
    )

    missionary_code = Column(
        String,
        unique=True,
    )

    status = Column(
        String,
        default="ACTIVE"
    )

    row_color = Column(
        String
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

    tracking_profile = Column(String, default="LEGAL")
    dynamics_contact_id = Column(String)
    dynamics_row_checksum = Column(String)
    dynamics_modified_at = Column(DateTime(timezone=True))
    dynamics_status = Column(String)
    release_date = Column(Date)
    home_address = Column(String)
    father_name = Column(String)
    mother_name = Column(String)
    father_first_name_override = Column(String)
    mother_first_name_override = Column(String)

    passport_number = Column(
        String
    )

    dni_number = Column(
        String
    )

    carnet_number = Column(
        String
    )

    date_of_birth = Column(
        Date
    )

    tramite_usuario = Column(
        String
    )

    tramite_contrasena = Column(
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

    last_entry_date = Column(
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

    interpol_appointment_date = Column(
        Date
    )

    biometric_appointment_date = Column(
        Date
    )

    pickup_appointment_date = Column(
        Date
    )

    field_sources = Column(
        String
    )

    # ======================================
    # File System
    # ======================================

    folder_path = Column(
        String
    )

    # Portable path beneath the server-authoritative mission storage root.
    # ``folder_path`` remains during the schema-4 transition for compatibility.
    folder_relative_path = Column(
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


class DynamicsRosterImport(Base):
    __tablename__ = "dynamics_roster_imports"

    id = Column(Integer, primary_key=True)
    preview_id = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False, default="PREVIEW")
    filename = Column(String, nullable=False)
    filename_timestamp = Column(String)
    file_sha256 = Column(String, nullable=False)
    dynamics_modified_at = Column(DateTime(timezone=True))
    summary_json = Column(String)
    applying_device = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
