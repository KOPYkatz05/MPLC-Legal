from pathlib import Path

from config import (
    ACTIVE_FOLDER_NAME,
    ARCHIVE_FOLDER_NAME,
    TRASH_FOLDER_NAME,
    ensure_storage_root,
    get_storage_root,
)

from utils.constants import (
    WORKFLOW_STAGES,
)

from utils.logger import logger

import shutil

from datetime import datetime


class OneDriveService:
    def __init__(self):
        try:
            ensure_storage_root(self.root)

            logger.info(
                "Initialized OneDrive "
                "root folders"
            )

        except Exception:
            logger.exception(
                "Failed to initialize "
                "OneDrive folders"
            )

            raise

    @property
    def root(self):
        return get_storage_root()

    @property
    def active_root(self):
        return self.root / ACTIVE_FOLDER_NAME

    @property
    def archive_root(self):
        return self.root / ARCHIVE_FOLDER_NAME

    @property
    def trash_root(self):
        return self.root / TRASH_FOLDER_NAME

    def create_missionary_folders(
        self,
        missionary_name,
    ):
        try:
            missionary_folder = (
                self.active_root
                / missionary_name
            )

            missionary_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            logger.info(
                f"Created missionary "
                f"root folder: "
                f"{missionary_folder}"
            )

            # =====================================
            # Workflow folders
            # =====================================

            for folder_name in WORKFLOW_STAGES:
                folder_path = (
                    missionary_folder
                    / folder_name
                )

                folder_path.mkdir(
                    exist_ok=True
                )

                logger.info(
                    f"Created workflow "
                    f"folder: "
                    f"{folder_path}"
                )

            return missionary_folder

        except Exception:
            logger.exception(
                f"Failed to create "
                f"folders for "
                f"{missionary_name}"
            )

            raise

    def archive_missionary_folder(
        self,
        current_folder_path
    ):
        try:
            current_folder = Path(
                current_folder_path
            )

            archive_year = str(
                datetime.now().year
            )

            archive_folder = (
                self.archive_root
                / archive_year
            )

            archive_folder.mkdir(
                parents=True,
                exist_ok=True
            )

            destination_folder = (
                archive_folder
                / current_folder.name
            )

            counter = 1

            while destination_folder.exists():
                destination_folder = (
                    archive_folder
                    / f"{current_folder.name}_{counter}"
                )
                counter += 1

            if current_folder.exists():
                shutil.move(
                    str(current_folder),
                    str(destination_folder)
                )

            logger.info(
                f"Archived folder "
                f"{destination_folder}"
            )

            return destination_folder

        except Exception:
            logger.exception(
                f"Failed to archive "
                f"folder: "
                f"{current_folder_path}"
            )

            raise

    def trash_missionary_folder(
        self,
        current_folder_path,
    ):
        try:
            current_folder = Path(
                current_folder_path
            )

            self.trash_root.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination_folder = (
                self.trash_root
                / current_folder.name
            )

            counter = 1

            while destination_folder.exists():
                destination_folder = (
                    self.trash_root
                    / f"{current_folder.name}_{counter}"
                )
                counter += 1

            if current_folder.exists():
                shutil.move(
                    str(current_folder),
                    str(destination_folder),
                )

            logger.info(
                f"Moved folder to trash: "
                f"{destination_folder}"
            )

            return destination_folder

        except Exception:
            logger.exception(
                f"Failed to trash folder: "
                f"{current_folder_path}"
            )

            raise

    def restore_missionary_folder(
        self,
        current_folder_path,
    ):
        try:
            current_folder = Path(
                current_folder_path
            )

            self.active_root.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination_folder = (
                self.active_root
                / current_folder.name
            )

            counter = 1

            while destination_folder.exists():
                destination_folder = (
                    self.active_root
                    / f"{current_folder.name}_{counter}"
                )
                counter += 1

            if current_folder.exists():
                shutil.move(
                    str(current_folder),
                    str(destination_folder),
                )

            logger.info(
                f"Restored folder: "
                f"{destination_folder}"
            )

            return destination_folder

        except Exception:
            logger.exception(
                f"Failed to restore folder: "
                f"{current_folder_path}"
            )

            raise
