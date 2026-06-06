from pathlib import Path

import fitz

from PIL import Image

from PySide6.QtCore import QRectF

from utils.logger import logger


class DocumentImageExportService:

    def export_pdf_page(
        self,
        pdf_path,
        page_index,
        rotation_angle,
        crop_rect,
        output_path,
    ):

        logger.info(
            "OCR_PDF_RENDER_BEGIN pdf=%s page=%s rotation=%s crop=%s output=%s",
            pdf_path,
            page_index,
            rotation_angle,
            crop_rect,
            output_path,
        )
        document = fitz.open(
            str(pdf_path)
        )

        try:

            page = document.load_page(
                page_index
            )

            pix = page.get_pixmap(
                dpi=400
            )
            logger.info(
                "OCR_PDF_RENDER_PIXMAP pdf=%s page=%s width=%s height=%s stride=%s alpha=%s",
                pdf_path,
                page_index,
                pix.width,
                pix.height,
                pix.stride,
                pix.alpha,
            )

            pix.save(
                str(output_path)
            )

        finally:
            document.close()

        image = Image.open(
            output_path
        )
        logger.info(
            "OCR_PDF_RENDER_IMAGE_OPENED output=%s mode=%s size=%s",
            output_path,
            image.mode,
            image.size,
        )

        image = image.rotate(
            -rotation_angle,
            expand=True,
        )

        if crop_rect:

            left = int(
                crop_rect.left()
            )

            top = int(
                crop_rect.top()
            )

            right = int(
                crop_rect.right()
            )

            bottom = int(
                crop_rect.bottom()
            )

            image = image.crop(
                (
                    left,
                    top,
                    right,
                    bottom,
                )
            )

        image.save(
            output_path
        )

        logger.info(
            "OCR_PDF_RENDER_DONE output=%s mode=%s size=%s",
            output_path,
            image.mode,
            image.size,
        )

        return output_path
