from pathlib import Path
import os
import sys

from PySide6.QtCore import QSettings

ORG = "MissionLegal"
APP = "MissionLegalTracker"
STORAGE_ROOT_KEY = "storage/root"

DEFAULT_STORAGE_ROOT = Path(
    r"C:\Users\PerúLimaCentralMissi\OneDrive - Church of Jesus Christ (1)"
    r"\Sec. Visas\1. Visas Lima Central"
    r"\1 DOCUMENTOS DE LEGALIZACIÓN - IMPORTANTE"
)

ACTIVE_FOLDER_NAME = "ACTIVE"
TRASH_FOLDER_NAME = "TRASH"
ARCHIVE_FOLDER_NAME = "ARCHIVE"


def get_storage_root():
    saved_root = QSettings(ORG, APP).value(
        STORAGE_ROOT_KEY,
        None,
    )
    if saved_root:
        return Path(saved_root)

    env_root = os.environ.get("MISSIONS_ROOT")
    if env_root:
        return Path(env_root)

    return DEFAULT_STORAGE_ROOT


def set_storage_root(path):
    root = Path(path)
    QSettings(ORG, APP).setValue(STORAGE_ROOT_KEY, str(root))
    ensure_storage_root(root)
    return root


def ensure_storage_root(root=None):
    root = Path(root or get_storage_root())
    try:
        root.mkdir(parents=True, exist_ok=True)
        for folder_name in (
            ACTIVE_FOLDER_NAME,
            TRASH_FOLDER_NAME,
            ARCHIVE_FOLDER_NAME,
        ):
            (root / folder_name).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(
            f"Warning: Could not create mission root folder: {root}\n{e}",
            file=sys.stderr
        )
    return root


# Backward-compatible name. Prefer get_storage_root() for runtime lookups.
MISSIONS_ROOT = ensure_storage_root()
