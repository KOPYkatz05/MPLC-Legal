from pathlib import Path

import fitz

from PIL import Image

from PySide6.QtCore import QRectF


class DocumentImageExportService:

    def export_pdf_page(
        self,
        pdf_path,
        page_index,
        rotation_angle,
        crop_rect,
        output_path,
    ):

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

            pix.save(
                str(output_path)
            )

        finally:
            document.close()

        image = Image.open(
            output_path
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

        return output_path