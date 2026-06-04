import os
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
        logger.info("Initializing PaddleOCR")

        try:
            from paddleocr import PaddleOCR

            self.ocr = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                det_model_dir=self._resolve_model_dir(
                    "PADDLEOCR_DET_MODEL_DIR",
                    DEFAULT_PADDLE_MODEL_DIRS["det_model_dir"],
                ),
                rec_model_dir=self._resolve_model_dir(
                    "PADDLEOCR_REC_MODEL_DIR",
                    DEFAULT_PADDLE_MODEL_DIRS["rec_model_dir"],
                ),
                cls_model_dir=self._resolve_model_dir(
                    "PADDLEOCR_CLS_MODEL_DIR",
                    DEFAULT_PADDLE_MODEL_DIRS["cls_model_dir"],
                ),
                show_log=False,
            )

            logger.info("PaddleOCR initialized successfully")

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
        logger.info(
            f"Running OCR on: "
            f"{image_path}"
        )

        try:
            result = self.ocr.ocr(
                str(image_path),
                cls=True,
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
                f"OCR extraction complete. "
                f"Extracted "
                f"{len(extracted_text)} "
                f"text blocks."
            )

            return final_text

        except Exception:
            logger.exception(
                f"OCR extraction failed "
                f"for {image_path}"
            )

            raise
