"""Extract a reviewable missionary portrait from a passport scan."""

from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile

import cv2
import fitz
import numpy as np
from PIL import Image, ImageOps

from utils.logger import logger


@dataclass(frozen=True)
class PassportPhotoCandidate:
    path: Path
    page_index: int
    score: float


class PassportPhotoService:
    """Choose a likely passport page and export the complete page for review."""

    MAX_PDF_PAGES = 4
    MAX_REVIEW_SIZE = (2800, 2800)

    def __init__(self, cascade_path=None):
        if cascade_path is None:
            cascade_path = (
                Path(cv2.data.haarcascades)
                / "haarcascade_frontalface_default.xml"
            )
            if not cascade_path.is_file() and getattr(sys, "frozen", False):
                cascade_path = (
                    Path(getattr(sys, "_MEIPASS", ""))
                    / "cv2"
                    / "data"
                    / "haarcascade_frontalface_default.xml"
                )
        self._cascade = cv2.CascadeClassifier(str(cascade_path))

    def extract(self, source_file):
        source_path = Path(source_file)
        detector_available = not self._cascade.empty()
        if not detector_available:
            logger.warning("PASSPORT_PHOTO_SKIPPED face detector unavailable")

        best = None
        fallback = None
        for page_index, image in self._source_images(source_path):
            if fallback is None:
                fallback = (0.0, page_index, image.copy())
            candidate = (
                self._best_crop(image, page_index)
                if detector_available
                else None
            )
            if candidate is not None and (
                best is None or candidate[0] > best[0]
            ):
                best = (candidate[0], page_index, image.copy())

        if best is None:
            best = fallback
            logger.info(
                "PASSPORT_PHOTO_FACE_NOT_FOUND_USING_FIRST_PAGE source=%s",
                source_path,
            )
        if best is None:
            logger.info("PASSPORT_PHOTO_PAGE_NOT_FOUND source=%s", source_path)
            return None

        score, page_index, full_page = best
        output = tempfile.NamedTemporaryFile(
            prefix="missionary-passport-photo-",
            suffix=".jpg",
            delete=False,
        )
        output_path = Path(output.name)
        output.close()
        full_page = ImageOps.exif_transpose(full_page).convert("RGB")
        full_page.thumbnail(self.MAX_REVIEW_SIZE, Image.Resampling.LANCZOS)
        full_page.save(output_path, format="JPEG", quality=94, optimize=True)
        logger.info(
            "PASSPORT_PHOTO_PAGE_EXPORTED source=%s page=%s score=%.3f output=%s",
            source_path,
            page_index,
            score,
            output_path,
        )
        return PassportPhotoCandidate(output_path, page_index, score)

    def _source_images(self, source_path):
        if source_path.suffix.lower() == ".pdf":
            with fitz.open(str(source_path)) as document:
                for page_index in range(min(len(document), self.MAX_PDF_PAGES)):
                    pix = document.load_page(page_index).get_pixmap(
                        dpi=220,
                        alpha=False,
                    )
                    yield page_index, Image.frombytes(
                        "RGB",
                        (pix.width, pix.height),
                        pix.samples,
                    )
            return

        with Image.open(source_path) as opened:
            yield 0, ImageOps.exif_transpose(opened).convert("RGB").copy()

    def _best_crop(self, image, page_index):
        best = None
        for rotation in (0, 90, 270):
            rotated = image if rotation == 0 else image.rotate(rotation, expand=True)
            rgb = np.asarray(rotated)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            min_side = max(40, int(min(gray.shape[:2]) * 0.055))
            faces = self._cascade.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=6,
                minSize=(min_side, min_side),
            )
            for x, y, width, height in faces:
                score = self._face_score(
                    x,
                    y,
                    width,
                    height,
                    rotated.width,
                    rotated.height,
                )
                crop = self._portrait_crop(rotated, x, y, width, height)
                if crop is not None and (best is None or score > best[0]):
                    best = (score, page_index, crop)
        return best

    @staticmethod
    def _face_score(x, y, width, height, image_width, image_height):
        area_ratio = (width * height) / float(image_width * image_height)
        size_score = min(area_ratio / 0.025, 1.0)
        edge_margin = min(
            x,
            y,
            image_width - (x + width),
            image_height - (y + height),
        )
        margin_score = max(0.0, min(edge_margin / max(width, height), 1.0))
        return (size_score * 0.8) + (margin_score * 0.2)

    @staticmethod
    def _portrait_crop(image, x, y, width, height):
        left = max(0, int(x - width * 0.70))
        top = max(0, int(y - height * 0.72))
        right = min(image.width, int(x + width * 1.70))
        bottom = min(image.height, int(y + height * 2.25))
        if right - left < 80 or bottom - top < 100:
            return None
        return image.crop((left, top, right, bottom))
