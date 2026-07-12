import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from utils.runtime_paths import runtime_logs_dir


LOGS_FOLDER = runtime_logs_dir()

LOG_ROLE = os.environ.get("MISSION_LEGAL_LOG_ROLE", "").strip().lower()
if LOG_ROLE == "ocr-worker":
    LOG_FILE = LOGS_FOLDER / "ocr-worker.log"
elif os.environ.get("MISSION_LEGAL_SERVER_PROCESS") == "1":
    LOG_FILE = LOGS_FOLDER / "server.log"
else:
    LOG_FILE = LOGS_FOLDER / "app.log"


LOG_HANDLERS = [
    RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
]
if sys.stderr is not None:
    LOG_HANDLERS.append(logging.StreamHandler())


logging.basicConfig(
    level=logging.INFO,

    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),

    handlers=LOG_HANDLERS,
)


logger = logging.getLogger(
    "mission_legal_app"
)
