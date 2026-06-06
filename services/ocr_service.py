import os
import sys
import time
from pathlib import Path

from utils.logger import logger


DEFAULT_PADDLE_MODEL_DIRS = {
    "det_model_dir": Path(
        r"C:\Local Apps\paddle_models\.paddleocr\whl\det\en"
        r"\en_PP-OCRv3_det_infer"
    ),
    "rec_model_dir": Path(
        r"C:\Local Apps\paddle_models\.paddleocr\whl\rec\en"
        r"\en_PP-OCRv4_rec_infer"
    ),
    "cls_model_dir": Path(
        r"C:\Local Apps\paddle_models\.paddleocr\whl\cls\ch_ppocr_mobile_v2.0_cls_infer"
    ),
}


class OCRService:
    def __init__(self):
        logger.info(
            "OCR_SERVICE_INIT_BEGIN pid=%s python=%s",
            os.getpid(),
            sys.version.replace("\n", " "),
        )

        try:
            logger.info("OCR_SERVICE_IMPORT_PADDLEOCR_BEGIN pid=%s", os.getpid())
            from paddleocr import PaddleOCR
            logger.info("OCR_SERVICE_IMPORT_PADDLEOCR_DONE pid=%s", os.getpid())

            model_dirs = {
                "det_model_dir": self._resolve_model_dir(
                    "PADDLEOCR_DET_MODEL_DIR",
                    DEFAULT_PADDLE_MODEL_DIRS["det_model_dir"],
                ),
                "rec_model_dir": self._resolve_model_dir(
                    "PADDLEOCR_REC_MODEL_DIR",
                    DEFAULT_PADDLE_MODEL_DIRS["rec_model_dir"],
                ),
                "cls_model_dir": self._resolve_model_dir(
                    "PADDLEOCR_CLS_MODEL_DIR",
                    DEFAULT_PADDLE_MODEL_DIRS["cls_model_dir"],
                ),
            }
            logger.info(
                "OCR_SERVICE_CONSTRUCTOR_BEGIN pid=%s model_dirs=%s",
                os.getpid(),
                {
                    key: {
                        "path": value,
                        "exists": Path(value).exists(),
                    }
                    for key, value in model_dirs.items()
                },
            )
            started_at = time.monotonic()

            self.ocr = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                det_model_dir=model_dirs["det_model_dir"],
                rec_model_dir=model_dirs["rec_model_dir"],
                cls_model_dir=model_dirs["cls_model_dir"],
                show_log=False,
            )

            logger.info(
                "OCR_SERVICE_CONSTRUCTOR_DONE pid=%s elapsed=%.2fs",
                os.getpid(),
                time.monotonic() - started_at,
            )

        except ModuleNotFoundError:
            logger.exception(
                "Failed to initialize PaddleOCR. "
                "Make sure setuptools is installed."
            )
            raise

        except Exception:
            logger.exception("Failed to initialize PaddleOCR")
            raise

    @staticmethod
    def _resolve_model_dir(env_key, default_path):
        env_path = os.environ.get(env_key)
        if env_path:
            return env_path
        return str(default_path)

    def extract_text(
        self,
        image_path,
    ):
        path = Path(image_path)
        logger.info(
            "OCR_SERVICE_EXTRACT_BEGIN pid=%s image=%s exists=%s bytes=%s",
            os.getpid(),
            path,
            path.exists(),
            path.stat().st_size if path.exists() else None,
        )

        try:
            started_at = time.monotonic()
            logger.info(
                "OCR_SERVICE_PADDLE_OCR_CALL_BEGIN pid=%s image=%s",
                os.getpid(),
                path,
            )
            result = self.ocr.ocr(
                str(image_path),
                cls=True,
            )
            logger.info(
                "OCR_SERVICE_PADDLE_OCR_CALL_DONE pid=%s image=%s elapsed=%.2fs result_pages=%s",
                os.getpid(),
                path,
                time.monotonic() - started_at,
                len(result or []),
            )

            extracted_text = []

            if not result:
                logger.warning(
                    f"No OCR text found in "
                    f"{image_path}"
                )

                return ""

            for page in result:
                if not page:
                    continue

                for line in page:
                    try:
                        text = line[1][0]

                        extracted_text.append(
                            text
                        )

                    except Exception:
                        logger.warning(
                            "Failed to parse "
                            "OCR line"
                        )

            final_text = "\n".join(
                extracted_text
            )

            logger.info(
                "OCR_SERVICE_EXTRACT_DONE pid=%s image=%s blocks=%s chars=%s",
                os.getpid(),
                path,
                len(extracted_text),
                len(final_text),
            )

            return final_text

        except Exception:
            logger.exception(
                f"OCR extraction failed "
                f"for {image_path}"
            )

            raise
