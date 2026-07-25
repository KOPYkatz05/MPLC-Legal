import os
import sys
import time
import ctypes
from pathlib import Path

from utils.logger import logger
from utils.runtime_paths import is_frozen, resource_path


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

BUNDLED_PADDLE_MODEL_DIRS = {
    "det_model_dir": ("ocr_models", "det"),
    "rec_model_dir": ("ocr_models", "rec"),
    "cls_model_dir": ("ocr_models", "cls"),
}


def _windows_short_path(path):
    """Return an ASCII-safe 8.3 path when Windows provides one."""
    path = str(Path(path).resolve())
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short_path = kernel32.GetShortPathNameW
    get_short_path.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    get_short_path.restype = ctypes.c_uint32

    required = get_short_path(path, None, 0)
    if not required:
        return path
    buffer = ctypes.create_unicode_buffer(required)
    written = get_short_path(path, buffer, required)
    if not written or written >= required:
        return path
    return buffer.value


def _paddle_compatible_model_path(path):
    path = str(path)
    if os.name != "nt":
        return path
    try:
        short_path = _windows_short_path(path)
    except (AttributeError, OSError):
        logger.warning(
            "Could not resolve a Windows short path for OCR model directory %s",
            path,
            exc_info=True,
        )
        return path
    if short_path != path:
        logger.info(
            "Using Windows short path for OCR model directory original=%s resolved=%s",
            path,
            short_path,
        )
    return short_path


def default_paddle_model_dirs():
    if is_frozen():
        return {
            key: _paddle_compatible_model_path(resource_path(*parts))
            for key, parts in BUNDLED_PADDLE_MODEL_DIRS.items()
        }
    return dict(DEFAULT_PADDLE_MODEL_DIRS)


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

            defaults = default_paddle_model_dirs()
            model_dirs = {
                "det_model_dir": self._resolve_model_dir(
                    "PADDLEOCR_DET_MODEL_DIR",
                    defaults["det_model_dir"],
                ),
                "rec_model_dir": self._resolve_model_dir(
                    "PADDLEOCR_REC_MODEL_DIR",
                    defaults["rec_model_dir"],
                ),
                "cls_model_dir": self._resolve_model_dir(
                    "PADDLEOCR_CLS_MODEL_DIR",
                    defaults["cls_model_dir"],
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
        return self.extract_page(image_path).get("text", "")

    def extract_page(
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
            extracted_lines = []

            if not result:
                logger.warning(
                    f"No OCR text found in "
                    f"{image_path}"
                )

                return {
                    "text": "",
                    "lines": [],
                }

            for page in result:
                if not page:
                    continue

                for line in page:
                    try:
                        text = line[1][0]
                        confidence = line[1][1] if len(line[1]) > 1 else None

                        extracted_text.append(
                            text
                        )
                        extracted_lines.append(
                            self._line_payload(line, text, confidence)
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

            return {
                "text": final_text,
                "lines": extracted_lines,
            }

        except Exception:
            logger.exception(
                f"OCR extraction failed "
                f"for {image_path}"
            )

            raise

    @staticmethod
    def _line_payload(line, text, confidence):
        bbox = line[0] if line else []
        xs = []
        ys = []
        for point in bbox or []:
            try:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
            except Exception:
                continue

        payload = {
            "text": text,
            "bbox": bbox,
        }
        if xs and ys:
            payload.update({
                "x0": min(xs),
                "y0": min(ys),
                "x1": max(xs),
                "y1": max(ys),
            })
        if confidence is not None:
            payload["confidence"] = confidence
        return payload
