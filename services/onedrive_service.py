from pathlib import Path

from config import MISSIONS_ROOT

from utils.constants import (
    WORKFLOW_STAGES,
)

from utils.logger import logger

import shutil

from datetime import datetime


ACTIVE_ROOT = (
    MISSIONS_ROOT / "ACTIVE"
)

ARCHIVE_ROOT = (
    MISSIONS_ROOT / "ARCHIVED"
)

TRASH_ROOT = (
    MISSIONS_ROOT / "TRASH PILE"
)


class OneDriveService:
    def __init__(self):
        try:
            ACTIVE_ROOT.mkdir(
                exist_ok=True
            )

            ARCHIVE_ROOT.mkdir(
                exist_ok=True
            )

            TRASH_ROOT.mkdir(
                exist_ok=True
            )

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

    def create_missionary_folders(
        self,
        missionary_name,
    ):
        try:
            missionary_folder = (
                ACTIVE_ROOT
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
            # System folders
            # =====================================

            system_folders = [
                "RAW_SCANS",
                "OCR_PROCESSED",
            ]

            for folder_name in system_folders:
                folder_path = (
                    missionary_folder
                    / folder_name
                )

                folder_path.mkdir(
                    exist_ok=True
                )

                logger.info(
                    f"Created system "
                    f"folder: "
                    f"{folder_path}"
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
                ARCHIVE_ROOT
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

            shutil.move(
                str(current_folder),
                str(destination_folder)
            )

            logger.info(
                f"Archived folder "
                f"{current_folder.name}"
            )

            return destination_folder

        except Exception:
            logger.exception(
                f"Failed to archive "
                f"folder: "
                f"{current_folder_path}"
            )

            raise