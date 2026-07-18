import os
from pathlib import Path


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
    "sqlalchemy.dialects.sqlite.pysqlite",
    "win32cred",
    "win32serviceutil",
    "win32timezone",
]


def application_datas(repo_root):
    repo_root = Path(repo_root)
    return [
        (str(repo_root / "assets" / "styles" / "theme.qss"), "assets/styles"),
        (
            str(repo_root / "assets" / "icons" / "lucide_icon_map.json"),
            "assets/icons",
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
