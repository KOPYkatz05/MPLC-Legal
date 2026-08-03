import os
import re
import stat
import shutil

from datetime import datetime
from pathlib import Path

from database.db import SessionLocal

from database.models.missionary import (
    Missionary,
)

from database.models.document import (
    Document,
)
from database.models.stage_history import (
    StageHistory,
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
from utils.nationalities import normalize_nationality

from utils.logger import logger
from utils.passport_numbers import normalize_passport_number
from services.api_client import MissionLegalApiClient, RemoteRecord, json_value


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
    ROW_COLORS = {
        "teal", "blue", "purple", "amber", "green", "red", "gray",
    }
    def __init__(self):
        self.api_client = MissionLegalApiClient.from_environment()
        if self.api_client is not None:
            self.onedrive_service = None
            self.workflow_service = None
            return
        self.onedrive_service = (
            OneDriveService()
        )

        self.workflow_service = (
            WorkflowService()
        )

    def get_all_missionaries(self):
        if self.api_client is not None:
            payload = self.api_client.get(
                "/v1/missionaries", params={"status_filter": "ACTIVE"}
            )
            return [RemoteRecord(item) for item in payload["items"]]
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

    def get_missionary(self, missionary_id):
        if self.api_client is not None:
            payload = self.api_client.get(f"/v1/missionaries/{missionary_id}")
            return RemoteRecord(payload)
        session = SessionLocal()
        try:
            return session.query(Missionary).filter_by(id=missionary_id).first()
        finally:
            session.close()

    def get_archived_missionaries(self):
        if self.api_client is not None:
            payload = self.api_client.get(
                "/v1/missionaries", params={"status_filter": "ARCHIVED"}
            )
            return [RemoteRecord(item) for item in payload["items"]]
        session = SessionLocal()

        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ARCHIVED")
                .all()
            )

            archive_reasons = self._archive_reasons_for_session(
                session,
                [missionary.id for missionary in missionaries],
            )
            for missionary in missionaries:
                missionary.archive_reason = archive_reasons.get(
                    missionary.id,
                    "",
                )

            logger.info("Loaded archived missionaries")

            return missionaries

        except Exception:
            logger.exception("Failed to load archived missionaries")
            return []

        finally:
            session.close()

    def _archive_reasons_for_session(self, session, missionary_ids):
        if not missionary_ids:
            return {}

        rows = (
            session.query(StageHistory)
            .filter(StageHistory.missionary_id.in_(missionary_ids))
            .filter(StageHistory.to_stage == "ARCHIVED")
            .order_by(
                StageHistory.missionary_id,
                StageHistory.created_at.desc(),
                StageHistory.id.desc(),
            )
            .all()
        )

        reasons = {}
        for row in rows:
            if row.missionary_id in reasons:
                continue
            reasons[row.missionary_id] = row.notes or ""

        return reasons

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
        passport_number = normalize_passport_number(passport_number)
        nationality = normalize_nationality(nationality)
        if self.api_client is not None:
            payload = self.api_client.post(
                "/v1/missionaries",
                json={
                    "full_name": full_name,
                    "missionary_code": missionary_code,
                    "preferred_name": preferred_name,
                    "nationality": nationality,
                    "passport_number": passport_number,
                    "arrival_date": json_value(arrival_date),
                    "visa_expiration": json_value(visa_expiration),
                },
            )
            return RemoteRecord(payload)
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
        field_updates = dict(field_updates)
        if "passport_number" in field_updates:
            field_updates["passport_number"] = normalize_passport_number(
                field_updates["passport_number"]
            )
        if "nationality" in field_updates:
            field_updates["nationality"] = normalize_nationality(
                field_updates["nationality"]
            )
        if "dni_number" in field_updates:
            dni_number = re.sub(
                r"\D", "", str(field_updates["dni_number"] or "")
            )[:8]
            field_updates["dni_number"] = (
                dni_number if len(dni_number) == 8 else None
            )
        if self.api_client is not None:
            payload = self.api_client.patch(
                f"/v1/missionaries/{missionary_id}",
                json={
                    "fields": {
                        key: json_value(value) for key, value in field_updates.items()
                    }
                },
            )
            return payload["updated"]
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
            return True

        except Exception:
            session.rollback()

            logger.exception(
                f"Failed to update fields for "
                f"missionary ID {missionary_id}"
            )

            raise

        finally:
            session.close()

    def set_missionary_row_color(self, missionary_id, color):
        color = (color or "").strip().lower()
        if color not in self.ROW_COLORS:
            raise ValueError("Unsupported missionary row color")
        if self.api_client is not None:
            return RemoteRecord(self.api_client.patch(
                f"/v1/missionaries/{missionary_id}/row-color",
                json={"color": color},
            ))
        return self._save_missionary_row_color(missionary_id, color)

    def clear_missionary_row_color(self, missionary_id):
        if self.api_client is not None:
            return RemoteRecord(self.api_client.delete(
                f"/v1/missionaries/{missionary_id}/row-color"
            ))
        return self._save_missionary_row_color(missionary_id, None)

    def _save_missionary_row_color(self, missionary_id, color):
        session = SessionLocal()
        try:
            missionary = session.query(Missionary).filter_by(id=missionary_id).first()
            if missionary is None:
                return None
            missionary.row_color = color
            session.commit()
            session.refresh(missionary)
            return missionary
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_missionary(
        self,
        missionary_id
    ):
        if self.api_client is not None:
            return self.api_client.post(
                f"/v1/missionaries/{missionary_id}/trash"
            )["trashed"]
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
            return True

        except Exception:
            session.rollback()

            logger.exception(
                f"Failed to delete missionary "
                f"ID {missionary_id}"
            )

            raise

        finally:
            session.close()

    def archive_missionary(
        self,
        missionary_id,
        archive_group_name=None,
        archive_reason=None,
    ):
        if self.api_client is not None:
            return self.api_client.post(
                f"/v1/missionaries/{missionary_id}/archive",
                json={"reason": archive_reason},
            )["archived"]
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
                    f"not found for archive"
                )
                return

            current_stage = missionary.current_stage
            archive_reason = (archive_reason or "").strip() or None

            if missionary.folder_path:
                destination_folder = (
                    self.onedrive_service
                    .archive_missionary_folder(
                        missionary.folder_path,
                        group_name=archive_group_name,
                    )
                )
                missionary.folder_path = str(destination_folder)

            missionary.status = "ARCHIVED"

            if current_stage or archive_reason:
                session.add(
                    StageHistory(
                        missionary_id=missionary.id,
                        from_stage=current_stage,
                        to_stage="ARCHIVED",
                        notes=archive_reason,
                    )
                )

            session.commit()

            logger.info(
                f"Archived missionary: "
                f"{missionary.full_name}"
            )
            return True

        except Exception:
            session.rollback()

            logger.exception(
                f"Failed to archive missionary "
                f"ID {missionary_id}"
            )

            raise

        finally:
            session.close()

    def archive_missionaries(self, missionary_ids):
        for missionary_id in missionary_ids:
            self.archive_missionary(missionary_id)

    def archive_missionaries_as_group(
        self,
        missionary_ids,
        group_name,
    ):
        if self.api_client is not None:
            payload = self.api_client.post(
                "/v1/missionaries/archive-group",
                json={"missionary_ids": missionary_ids, "group_name": group_name},
            )
            return Path(payload["package_path"])
        group_name = (group_name or "").strip()

        if not group_name:
            raise ValueError("Archive group name is required.")

        missionaries = self._load_missionaries_for_archive(missionary_ids)

        if not missionaries:
            return None

        package_path = self._archive_group_package_path(group_name)

        from services.group_package_export_service import (
            GroupPackageExportService,
        )

        GroupPackageExportService().export_missionaries_package(
            group_name,
            missionaries,
            package_path,
        )

        for missionary in missionaries:
            self.archive_missionary(
                missionary.id,
                archive_group_name=group_name,
            )

        return package_path

    def _load_missionaries_for_archive(self, missionary_ids):
        ids = list(dict.fromkeys(missionary_ids or []))
        if not ids:
            return []

        session = SessionLocal()

        try:
            missionaries = (
                session.query(Missionary)
                .filter(Missionary.id.in_(ids))
                .all()
            )

            by_id = {
                missionary.id: missionary
                for missionary in missionaries
            }

            ordered = [
                by_id[missionary_id]
                for missionary_id in ids
                if missionary_id in by_id
            ]

            for missionary in ordered:
                session.expunge(missionary)

            return ordered

        finally:
            session.close()

    def _archive_group_package_path(self, group_name):
        archive_year = str(datetime.now().year)
        archive_folder = (
            self.onedrive_service.archive_root
            / archive_year
        )
        archive_folder.mkdir(parents=True, exist_ok=True)

        safe_name = self._safe_archive_group_name(group_name)
        package_path = archive_folder / f"{safe_name}.zip"

        counter = 1
        while package_path.exists():
            package_path = archive_folder / f"{safe_name}_{counter}.zip"
            counter += 1

        return package_path

    @staticmethod
    def _safe_archive_group_name(value):
        value = (value or "").strip() or "Archived Group"
        value = re.sub(r'[<>:"/\\|?*]+', "-", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip(" .") or "Archived Group"

    def get_trashed(self):
        if self.api_client is not None:
            payload = self.api_client.get(
                "/v1/missionaries", params={"status_filter": "TRASH"}
            )
            return [RemoteRecord(item) for item in payload["items"]]
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
        if self.api_client is not None:
            return self.api_client.post(
                f"/v1/missionaries/{missionary_id}/restore"
            )["restored"]
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
            return True

        except Exception:
            session.rollback()

            logger.exception(
                "Failed to restore missionary"
            )

            raise

        finally:
            session.close()

    def hard_delete(self, missionary_id):
        if self.api_client is not None:
            return self.api_client.delete(
                f"/v1/missionaries/{missionary_id}"
            )["deleted"]
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
            from database.models.residency_event import (
                ResidencyEvent,
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

            (
                session.query(ResidencyEvent)
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
            return True

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
