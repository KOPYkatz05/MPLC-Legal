import re
import shutil
import tempfile
import zipfile

from pathlib import Path

from database.db import SessionLocal
from database.models.missionary import Missionary
from database.models.secretary_work import MissionaryGroup, MissionaryGroupMember
from services.export_service import ExportService
from services.missionary_service import missionary_display_id
from utils.logger import logger


IGNORED_EXPORT_FOLDER_NAMES = {
    "OCR_PROCESSED",
    "RAW_SCANS",
}


class GroupPackageExportError(ValueError):
    pass


class GroupPackageExportResult:
    def __init__(self, group_name, missionary_count, skipped_folders=None):
        self.group_name = group_name
        self.missionary_count = missionary_count
        self.skipped_folders = skipped_folders or []


class GroupPackageExportService:
    def __init__(self, export_service=None):
        self.export_service = export_service or ExportService()

    def export_group_package(self, group_id, output_zip_path):
        group_name, missionaries = self._load_group_missionaries(group_id)
        return self.export_missionaries_package(
            group_name,
            missionaries,
            output_zip_path,
        )

    def export_missionaries_package(self, group_name, missionaries, output_zip_path):
        if not missionaries:
            raise GroupPackageExportError("Selected group has no missionaries.")

        missionaries = list(missionaries)
        output_zip_path = Path(output_zip_path)
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="mission_group_export_",
            dir=output_zip_path.parent,
        ) as tmp:
            package_root = Path(tmp) / self._safe_name(group_name)
            documents_root = package_root / "documents"
            documents_root.mkdir(parents=True, exist_ok=True)

            excel_path = package_root / "missionaries.xlsx"
            ok = self.export_service.export_missionaries_to_excel(
                missionaries,
                excel_path,
                columns=self.export_service.full_export_columns(),
            )
            if not ok:
                raise GroupPackageExportError("Could not create Excel export.")

            skipped_folders = self._copy_document_folders(
                missionaries,
                documents_root,
            )

            self._write_zip(package_root, output_zip_path)

        logger.info(
            "Exported full group package for %s missionaries to %s",
            len(missionaries),
            output_zip_path,
        )
        return GroupPackageExportResult(
            group_name=group_name,
            missionary_count=len(missionaries),
            skipped_folders=skipped_folders,
        )

    def _load_group_missionaries(self, group_id):
        session = SessionLocal()
        try:
            group = session.query(MissionaryGroup).filter_by(id=group_id).first()
            if group is None:
                raise GroupPackageExportError("Group not found.")

            missionaries = (
                session.query(Missionary)
                .join(
                    MissionaryGroupMember,
                    MissionaryGroupMember.missionary_id == Missionary.id,
                )
                .filter(MissionaryGroupMember.group_id == group.id)
                .order_by(Missionary.full_name)
                .all()
            )

            for missionary in missionaries:
                session.expunge(missionary)

            return group.name, missionaries
        finally:
            session.close()

    def _copy_document_folders(self, missionaries, documents_root):
        skipped = []

        for missionary in missionaries:
            folder_path = (
                Path(missionary.folder_path)
                if missionary.folder_path
                else None
            )
            folder_name = self._missionary_folder_name(missionary)
            destination = documents_root / folder_name

            if (
                folder_path is None
                or not folder_path.exists()
                or not folder_path.is_dir()
            ):
                destination.mkdir(parents=True, exist_ok=True)
                skipped.append(missionary.full_name or missionary_display_id(missionary))
                continue

            shutil.copytree(
                folder_path,
                destination,
                ignore=self._ignore_legacy_ocr_folders,
            )

        return skipped

    @staticmethod
    def _write_zip(source_root, output_zip_path):
        if output_zip_path.exists():
            output_zip_path.unlink()

        with zipfile.ZipFile(
            output_zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in source_root.rglob("*"):
                relative_path = path.relative_to(source_root)
                if path.is_dir():
                    archive.write(path, f"{relative_path}/")
                elif path.is_file():
                    archive.write(path, relative_path)

    def _missionary_folder_name(self, missionary):
        display_id = missionary_display_id(missionary)
        name = missionary.full_name or "Missionary"
        return self._safe_name(f"{display_id} - {name}")

    @staticmethod
    def _ignore_legacy_ocr_folders(_directory, names):
        return {
            name
            for name in names
            if name.upper() in IGNORED_EXPORT_FOLDER_NAMES
        }

    @staticmethod
    def _safe_name(value):
        value = (value or "").strip() or "Export"
        value = re.sub(r'[<>:"/\\|?*]+', "-", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip(" .") or "Export"
