from services import onedrive_service as service_module
from services.onedrive_service import OneDriveService
from utils.constants import WORKFLOW_STAGES


def test_create_missionary_folders_skips_legacy_ocr_folders(monkeypatch, tmp_path):
    root = tmp_path / "storage"
    monkeypatch.setattr(service_module, "get_storage_root", lambda: root)
    monkeypatch.setattr(
        service_module,
        "ensure_storage_root",
        lambda path: path.mkdir(parents=True, exist_ok=True),
    )

    folder = OneDriveService().create_missionary_folders("Example Missionary")

    assert folder == root / "ACTIVE" / "Example Missionary"
    assert not (folder / "RAW_SCANS").exists()
    assert not (folder / "OCR_PROCESSED").exists()
    for stage in WORKFLOW_STAGES:
        assert (folder / stage).is_dir()
