import os
import re
import runpy
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


CLIENT_HIDDEN_IMPORTS = [
    "PIL.ImageQt",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "cryptography",
    "bs4",
    "docx",
    "fire",
    "fontTools",
    "imgaug",
    "keyring.backends.Windows",
    "lmdb",
    "openpyxl",
    "paddle",
    "paddleocr",
    "pyclipper",
    "rapidfuzz",
    "requests",
    "scipy",
    "services.ocr_worker",
    "services.lan_discovery",
    "services.pairing_package",
    "services.server_update_service",
    "shapely",
    "skimage",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "tqdm",
    "velopack",
    "win32cred",
    "winotify",
    "yaml",
]

SERVER_HIDDEN_IMPORTS = [
    "keyring.backends.Windows",
    "server.app",
    "server.networking",
    "server.tls",
    "server.trusted_networks",
    "services.lan_discovery",
    "services.pairing_package",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "win32cred",
    "win32serviceutil",
    "win32timezone",
]


def windows_version_info(repo_root, *, description, original_filename):
    """Create deterministic Windows version metadata from ``version.py``."""

    repo_root = Path(repo_root).resolve()
    app_version = str(
        runpy.run_path(str(repo_root / "version.py"))["APP_VERSION"]
    ).strip()
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", app_version)
    if match is None:
        raise ValueError(
            "APP_VERSION must begin with three numeric components for Windows "
            f"version metadata: {app_version}"
        )
    numeric_version = tuple(int(value) for value in match.groups()) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numeric_version,
            prodvers=numeric_version,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Mission Legal"),
                            StringStruct("FileDescription", description),
                            StringStruct("FileVersion", app_version),
                            StringStruct("InternalName", Path(original_filename).stem),
                            StringStruct("LegalCopyright", "Mission Legal"),
                            StringStruct("OriginalFilename", original_filename),
                            StringStruct("ProductName", "Mission Legal"),
                            StringStruct("ProductVersion", app_version),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


def application_datas(repo_root):
    repo_root = Path(repo_root)
    return [
        (str(repo_root / "assets" / "styles" / "theme.qss"), "assets/styles"),
        (
            str(repo_root / "assets" / "icons" / "lucide_icon_map.json"),
            "assets/icons",
        ),
        (
            str(repo_root / "assets" / "icons" / "mission_legal" / "mission_legal_icon.png"),
            "assets/icons/mission_legal",
        ),
        (
            str(repo_root / "assets" / "icons" / "mission_legal" / "mission_legal_splash.png"),
            "assets/icons/mission_legal",
        ),
        (
            str(repo_root / "data" / "country_names_by_code.json"),
            "data",
        ),
    ]


def ocr_model_datas():
    configured_root = os.environ.get("MISSION_LEGAL_BUILD_OCR_MODEL_ROOT")
    if not configured_root:
        configured_root = r"C:\Local Apps\paddle_models\.paddleocr\whl"
    root = Path(configured_root).expanduser().resolve()
    sources = {
        "det": root / "det" / "en" / "en_PP-OCRv3_det_infer",
        "rec": root / "rec" / "en" / "en_PP-OCRv4_rec_infer",
        "cls": root / "cls" / "ch_ppocr_mobile_v2.0_cls_infer",
    }
    missing = [str(path) for path in sources.values() if not path.is_dir()]
    if missing:
        raise FileNotFoundError(
            "Required PaddleOCR model directories are missing: "
            + ", ".join(missing)
        )
    return [
        (str(source), f"ocr_models/{role}")
        for role, source in sources.items()
    ]
