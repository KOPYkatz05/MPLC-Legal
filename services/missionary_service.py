import os
import stat
import shutil

from pathlib import Path

from database.db import SessionLocal

from database.models.missionary import (
    Missionary,
)

from database.models.document import (
    Document,
)

from services.onedrive_service import (
    OneDriveService,
)

from services.workflow_service import (
    WorkflowService,
)
from services.appointment_service import (
    APPOINTMENT_FIELDS,
    AppointmentService,
)

from utils.logger import logger


class MissionaryCodeError(ValueError):
    pass


def missionary_display_id(missionary):
    code = getattr(
        missionary,
        "missionary_code",
        None,
    )

    code = (code or "").strip()

    if code:
        return code

    return str(missionary.id)


class MissionaryService:
    def __init__(self):
        self.onedrive_service = (
            OneDriveService()
        )

        self.workflow_service = (
            WorkflowService()
        )

    def get_all_missionaries(self):
        session = SessionLocal()

        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )

            logger.info(
                "Loaded active missionaries"
            )

            return missionaries

        except Exception:
            logger.exception(
                "Failed to load missionaries"
            )

            return []

        finally:
            session.close()

    def create_missionary(
        self,
        full_name,
        missionary_code,
        preferred_name=None,
        nationality=None,
        passport_number=None,
        arrival_date=None,
        visa_expiration=None,
    ):
        session = SessionLocal()

        try:
            missionary_code = (
                missionary_code or ""
            ).strip()

            if not missionary_code:
                raise MissionaryCodeError(
                    "Missionary ID is required."
                )

            if not missionary_code.isdigit():
                raise MissionaryCodeError(
                    "Missionary ID must contain numbers only."
                )

            existing = (
                session.query(Missionary)
                .filter_by(
                    missionary_code=missionary_code
                )
                .first()
            )

            if existing:
                raise MissionaryCodeError(
                    "Missionary ID is already in use."
                )

            folder_path = (
                self.onedrive_service
                .create_missionary_folders(
                    full_name
                )
            )

            missionary = Missionary(
                missionary_code=missionary_code,

                full_name=full_name,

                preferred_name=preferred_name,

                nationality=nationality,

                passport_number=passport_number,

                folder_path=str(folder_path),

                status="ACTIVE",

                arrival_date=arrival_date,

                visa_expiration=visa_expiration,
            )

            session.add(missionary)

            session.commit()

            session.refresh(missionary)

            self.workflow_service.initialize_workflows(
                missionary.id
            )

            logger.info(
                f"Created missionary: "
                f"{missionary.full_name}"
            )

            return missionary

        except MissionaryCodeError:
            session.rollback()
            raise

        except Exception:
            session.rollback()

            logger.exception(
                f"Failed to create missionary: "
                f"{full_name}"
            )

            raise

        finally:
            session.close()

    def update_fields(
        self,
        missionary_id,
        field_updates,
    ):
        session = SessionLocal()

        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )

            if not missionary:
                logger.warning(
                    f"Missionary ID "
                    f"{missionary_id} "
                    f"not found for field update"
                )

                return

            for field, value in field_updates.items():
                if (
                    hasattr(missionary, field)
                    and value is not None
                    and value != ""
                ):
                    setattr(missionary, field, value)

                    logger.info(
                        f"Updated {field} = {value} "
                        f"for {missionary.full_name}"
                    )

            session.commit()

            appointment_fields = (
                set(field_updates)
                & set(APPOINTMENT_FIELDS)
            )
            if appointment_fields:
                AppointmentService().sync_from_missionary_dates(
                    missionary_id,
                    appointment_fields,
                )

            logger.info(
                f"Saved field updates for "
                f"{missionary.full_name}: "
                f"{list(field_updates.keys())}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                f"Failed to update fields for "
                f"missionary ID {missionary_id}"
            )

            raise

        finally:
            session.close()

    def delete_missionary(
        self,
        missionary_id
    ):
        session = SessionLocal()

        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )

            if not missionary:
                logger.warning(
                    f"Missionary ID "
                    f"{missionary_id} "
                    f"not found for deletion"
                )

                return

            # ======================================
            # Move Folder To Trash
            # ======================================

            if missionary.folder_path:
                destination_folder = (
                    self.onedrive_service
                    .trash_missionary_folder(
                        missionary.folder_path
                    )
                )

                missionary.folder_path = str(
                    destination_folder
                )

                logger.info(
                    f"Moved missionary folder "
                    f"to trash: "
                    f"{destination_folder}"
                )

            # ======================================
            # Soft Delete
            # ======================================

            missionary.status = "TRASH"

            from datetime import datetime

            missionary.deleted_at = datetime.now()

            session.commit()

            logger.info(
                f"Soft deleted missionary: "
                f"{missionary.full_name}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                f"Failed to delete missionary "
                f"ID {missionary_id}"
            )

            raise

        finally:
            session.close()

    def get_trashed(self):
        session = SessionLocal()

        try:
            return (
                session.query(Missionary)
                .filter_by(status="TRASH")
                .order_by(Missionary.deleted_at.desc())
                .all()
            )

        except Exception:
            logger.exception(
                "Failed to load trashed missionaries"
            )

            return []

        finally:
            session.close()

    def restore_missionary(self, missionary_id):
        session = SessionLocal()

        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )

            if not missionary:
                return

            missionary.status = "ACTIVE"

            missionary.deleted_at = None

            # Move folder back
            if missionary.folder_path:
                dest = (
                    self.onedrive_service
                    .restore_missionary_folder(
                        missionary.folder_path
                    )
                )

                missionary.folder_path = str(dest)

            session.commit()

            logger.info(
                f"Restored missionary: "
                f"{missionary.full_name}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to restore missionary"
            )

            raise

        finally:
            session.close()

    def hard_delete(self, missionary_id):
        session = SessionLocal()

        try:
            missionary = (
                session.query(Missionary)
                .filter_by(id=missionary_id)
                .first()
            )

            if not missionary:
                return

            # Delete folder
            if missionary.folder_path:
                folder = Path(
                    missionary.folder_path
                )

                if folder.exists():
                    folder_deleted = (
                        self._safe_delete_folder(folder)
                    )

                    if not folder_deleted:
                        logger.warning(
                            f"Could not fully remove folder "
                            f"for missionary ID {missionary_id}: "
                            f"{folder}"
                        )

            # Delete related records
            from database.models.document import (
                Document,
            )

            from database.models.workflow import (
                WorkflowStage,
            )

            from database.models.stage_history import (
                StageHistory,
            )

            (
                session.query(Document)
                .filter_by(
                    missionary_id=missionary_id
                )
                .delete()
            )

            (
                session.query(WorkflowStage)
                .filter_by(
                    missionary_id=missionary_id
                )
                .delete()
            )

            (
                session.query(StageHistory)
                .filter_by(
                    missionary_id=missionary_id
                )
                .delete()
            )

            session.delete(missionary)

            session.commit()

            logger.info(
                f"Permanently deleted missionary "
                f"ID {missionary_id}"
            )

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to permanently delete"
            )

            raise

        finally:
            session.close()

    def _make_writable(self, path):
        try:
            os.chmod(path, stat.S_IWRITE)
        except Exception:
            logger.debug(
                f"Could not update permissions for {path}"
            )

    def _safe_delete_folder(self, folder):
        # OneDrive and Windows can leave read-only files or directories
        # behind long enough for a plain rmtree() to fail. We first clear
        # writable flags recursively, then retry permission errors.
        try:
            for child in folder.rglob("*"):
                self._make_writable(child)

            self._make_writable(folder)

            def onerror(func, path, exc_info):
                exc = exc_info[1]

                if isinstance(exc, PermissionError):
                    self._make_writable(path)

                    try:
                        func(path)
                        return
                    except Exception:
                        pass

                raise exc

            shutil.rmtree(folder, onerror=onerror)

            return not folder.exists()

        except Exception:
            logger.exception(
                f"Failed to remove folder: {folder}"
            )

            return False
