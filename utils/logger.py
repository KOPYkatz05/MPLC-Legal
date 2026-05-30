import logging

from pathlib import Path


LOGS_FOLDER = Path("logs")

LOGS_FOLDER.mkdir(
    exist_ok=True
)

LOG_FILE = (
    LOGS_FOLDER / "app.log"
)


logging.basicConfig(
    level=logging.INFO,

    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),

    handlers=[
        logging.FileHandler(
            LOG_FILE,
            encoding="utf-8"
        ),

        logging.StreamHandler()
    ]
)


logger = logging.getLogger(
    "mission_legal_app"
)