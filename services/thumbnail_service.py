from pathlib import Path

from utils.logger import logger


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
}


class ThumbnailService:

    THUMB_W = 60
    THUMB_H = 75
    MAX_CACHE_ITEMS = 256

    def __init__(self):
        self._pixmap_cache = {}

    def get_pixmap(self, file_path):
        try:
            path = Path(file_path)

            if not path.exists():
                self._discard_path(path)
                return None

            stat = path.stat()
            cache_key = (
                str(path.resolve()),
                stat.st_mtime_ns,
                stat.st_size,
                self.THUMB_W,
                self.THUMB_H,
            )
            cached = self._pixmap_cache.get(cache_key)
            if cached is not None:
                return cached

            suffix = path.suffix.lower()

            if suffix == ".pdf":
                pixmap = self._pdf_pixmap(path)

            elif suffix in IMAGE_EXTENSIONS:
                pixmap = self._image_pixmap(path)

            else:
                return None

            if pixmap is not None:
                self._remember(cache_key, pixmap)

            return pixmap

        except Exception:
            logger.exception(
                f"Thumbnail failed for {file_path}"
            )

            return None

    def _remember(self, cache_key, pixmap):
        self._pixmap_cache[cache_key] = pixmap

        if len(self._pixmap_cache) <= self.MAX_CACHE_ITEMS:
            return

        oldest_key = next(iter(self._pixmap_cache), None)
        if oldest_key is not None:
            self._pixmap_cache.pop(oldest_key, None)

    def _discard_path(self, path):
        try:
            resolved = str(path.resolve())
        except Exception:
            resolved = str(path)

        stale_keys = [
            key
            for key in self._pixmap_cache
            if key and key[0] == resolved
        ]
        for key in stale_keys:
            self._pixmap_cache.pop(key, None)

    def _image_pixmap(self, path):
        try:
            import io

            from PIL import Image as PILImage

            from PySide6.QtGui import QPixmap

            img = PILImage.open(str(path))

            img.thumbnail(
                (self.THUMB_W, self.THUMB_H),
                PILImage.LANCZOS,
            )

            buf = io.BytesIO()

            img = img.convert("RGB")

            img.save(buf, format="PNG")

            buf.seek(0)

            pixmap = QPixmap()

            pixmap.loadFromData(buf.read())

            return pixmap

        except Exception:
            logger.exception(
                "Image thumbnail generation failed"
            )

            return None

    def _pdf_pixmap(self, path):
        try:
            import io

            import fitz

            from PIL import Image as PILImage

            from PySide6.QtGui import QPixmap

            doc = fitz.open(str(path))

            page = doc[0]

            mat = fitz.Matrix(0.5, 0.5)

            pix = page.get_pixmap(matrix=mat)

            img_bytes = pix.tobytes("png")

            img = PILImage.open(
                io.BytesIO(img_bytes)
            )

            img.thumbnail(
                (self.THUMB_W, self.THUMB_H),
                PILImage.LANCZOS,
            )

            buf = io.BytesIO()

            img = img.convert("RGB")

            img.save(buf, format="PNG")

            buf.seek(0)

            pixmap = QPixmap()

            pixmap.loadFromData(buf.read())

            return pixmap

        except Exception:
            logger.exception(
                "PDF thumbnail generation failed"
            )

            return None
