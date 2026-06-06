from pathlib import Path

import fitz
import cv2

from utils.logger import logger


class ImageProcessingService:

    def process_upload(
        self,
        file_path,
        output_folder,
    ):
        file_path = Path(file_path)

        output_folder = Path(output_folder)

        output_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        logger.info(
            f"Processing upload: "
            f"{file_path}"
        )

        if file_path.suffix.lower() == ".pdf":
            return self.process_pdf(
                file_path,
                output_folder,
            )

        logger.warning(
            f"Unsupported file type: "
            f"{file_path.suffix}"
        )

        return []

    def process_pdf(
        self,
        pdf_path,
        output_folder,
    ):
        output_files = []

        pdf_document = fitz.open(
            pdf_path
        )

        try:
            for page_index in range(
                len(pdf_document)
            ):
                page = pdf_document.load_page(
                    page_index
                )

                pix = page.get_pixmap(
                    dpi=300
                )

                output_path = (
                    output_folder
                    / f"page_{page_index + 1}.png"
                )

                pix.save(
                    str(output_path)
                )

                self.clean_image_for_ocr(
                    output_path
                )

                output_files.append(
                    output_path
                )

                logger.info(
                    f"Saved processed page: "
                    f"{output_path}"
                )

        finally:
            pdf_document.close()

        return output_files

    def clean_image_for_ocr(
        self,
        image_path,
    ):
        image = cv2.imread(
            str(image_path)
        )

        if image is None:
            logger.warning(
                f"Could not load image: "
                f"{image_path}"
            )

            return

        logger.info(
            "OCR_IMAGE_CLEAN_BEGIN path=%s shape=%s dtype=%s",
            image_path,
            getattr(image, "shape", None),
            getattr(image, "dtype", None),
        )

        # =====================================
        # Preserve original color image
        # =====================================

        # Optional:
        # Very light sharpening to improve text
        sharpen_kernel = [
            [0, -1, 0],
            [-1, 5, -1],
            [0, -1, 0]
        ]

        import numpy as np

        sharpened = cv2.filter2D(
            image,
            -1,
            np.array(sharpen_kernel)
        )

        cv2.imwrite(
            str(image_path),
            sharpened
        )

        logger.info(
            "OCR_IMAGE_CLEAN_DONE path=%s shape=%s",
            image_path,
            getattr(sharpened, "shape", None),
        )
