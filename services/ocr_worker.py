import argparse
import faulthandler
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MISSION_LEGAL_LOG_ROLE", "ocr-worker")

from utils.logger import logger
from utils.runtime_paths import runtime_logs_dir
from services.ocr_service import OCRService


def _enable_fault_log():
    logs_dir = runtime_logs_dir()
    fault_path = logs_dir / f"ocr_worker_fault_{os.getpid()}.log"
    fault_file = fault_path.open("a", encoding="utf-8")
    faulthandler.enable(file=fault_file, all_threads=True)
    logger.info(
        "OCR_WORKER_FAULT_LOG pid=%s path=%s",
        os.getpid(),
        fault_path,
    )
    return fault_file


def _image_summary(image_path):
    path = Path(image_path)
    exists = path.exists()
    size = path.stat().st_size if exists else None
    dimensions = None
    if exists:
        try:
            from PIL import Image

            with Image.open(str(path)) as image:
                dimensions = image.size
        except Exception as exc:
            dimensions = f"unreadable:{exc}"
    return {
        "path": str(path),
        "exists": exists,
        "bytes": size,
        "dimensions": dimensions,
    }


def main(argv=None):
    fault_file = _enable_fault_log()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("images", nargs="+")
    args = parser.parse_args(argv)

    logger.info(
        "OCR_WORKER_START pid=%s output=%s image_count=%s images=%s",
        os.getpid(),
        args.output,
        len(args.images),
        [_image_summary(path) for path in args.images],
    )
    try:
        logger.info("OCR_WORKER_INIT_SERVICE_BEGIN pid=%s", os.getpid())
        service = OCRService()
        logger.info("OCR_WORKER_INIT_SERVICE_DONE pid=%s", os.getpid())

        pages = []
        for index, image_path in enumerate(args.images):
            logger.info(
                "OCR_WORKER_EXTRACT_BEGIN pid=%s page=%s image=%s",
                os.getpid(),
                index,
                _image_summary(image_path),
            )
            page_result = service.extract_page(image_path)
            text = page_result.get("text", "")
            logger.info(
                "OCR_WORKER_EXTRACT_DONE pid=%s page=%s chars=%s",
                os.getpid(),
                index,
                len(text or ""),
            )
            pages.append({
                "page": index,
                "image_path": str(image_path),
                "text": text,
                "lines": page_result.get("lines", []),
            })

        output_path = Path(args.output)
        output_path.write_text(
            json.dumps({"pages": pages}, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "OCR_WORKER_DONE pid=%s output=%s pages=%s",
            os.getpid(),
            output_path,
            len(pages),
        )
        return 0
    finally:
        logger.info("OCR_WORKER_EXIT pid=%s", os.getpid())
        faulthandler.disable()
        fault_file.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
