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

import shutil

from pathlib import Path

from utils.logger import logger


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
        preferred_name,
        nationality,
        passport_number,
        arrival_date,
        visa_expiration,
    ):
        session = SessionLocal()

        try:
            folder_path = (
                self.onedrive_service
                .create_missionary_folders(
                    full_name
                )
            )

            missionary = Missionary(
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
                current_folder = Path(
                    missionary.folder_path
                )

                trash_root = (
                    current_folder.parent.parent
                    / "TRASH PILE"
                )

                trash_root.mkdir(
                    exist_ok=True
                )

                destination_folder = (
                    trash_root
                    / current_folder.name
                )

                counter = 1

                while destination_folder.exists():
                    destination_folder = (
                        trash_root
                        / f"{current_folder.name}_{counter}"
                    )

                    counter += 1

                if current_folder.exists():
                    shutil.move(
                        str(current_folder),
                        str(destination_folder),
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