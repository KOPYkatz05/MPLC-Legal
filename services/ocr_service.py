from paddleocr import PaddleOCR

from utils.logger import logger


class OCRService:
    def __init__(self):
        logger.info(
            "Initializing PaddleOCR"
        )

        try:
            self.ocr = PaddleOCR(
                use_angle_cls=True,
                lang="en",

                det_model_dir=(
                    r"C:\Local Apps\paddle_models"
                    r"\.paddleocr\whl\det\en"
                    r"\en_PP-OCRv3_det_infer"
                ),

                rec_model_dir=(
                    r"C:\Local Apps\paddle_models"
                    r"\.paddleocr\whl\rec\en"
                    r"\en_PP-OCRv4_rec_infer"
                ),

                cls_model_dir=(
                    r"C:\Local Apps\paddle_models"
                    r"\.paddleocr\whl\cls"
                    r"\ch_ppocr_mobile_v2.0_cls_infer"
                ),

                show_log=False,
            )

            logger.info(
                "PaddleOCR initialized successfully"
            )

        except Exception:
            logger.exception(
                "Failed to initialize PaddleOCR"
            )

            raise

    def extract_text(
        self,
        image_path,
    ):
        logger.info(
            f"Running OCR on: {image_path}"
        )

        try:
            result = self.ocr.ocr(
                str(image_path),
                cls=True,
            )

            extracted_text = []

            if not result:
                return ""

            for page in result:
                if not page:
                    continue

                for line in page:
                    try:
                        text = line[1][0]
                        extracted_text.append(text)

                    except Exception:
                        logger.warning(
                            "Failed to parse OCR line"
                        )

            final_text = "\n".join(
                extracted_text
            )

            logger.info(
                f"Extracted {len(extracted_text)} text blocks"
            )

            return final_text

        except Exception:
            logger.exception(
                f"OCR extraction failed for {image_path}"
            )

            raise
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