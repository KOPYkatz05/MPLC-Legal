"""Server-side generation and caching of lightweight document thumbnails."""

from pathlib import Path

from database.runtime import get_app_data_dir


THUMBNAIL_SIZE = (120, 160)


class DocumentThumbnailService:
    def __init__(self, cache_root=None):
        self.cache_root = Path(cache_root or get_app_data_dir() / "Thumbnails")

    def get_thumbnail(self, document):
        source = Path(getattr(document, "file_path", "") or "")
        if not source.is_file():
            return None

        stat = source.stat()
        cache_dir = self.cache_root / str(document.missionary_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{document.id}-{stat.st_mtime_ns}-{stat.st_size}.jpg"
        if cache_path.is_file() and cache_path.stat().st_size:
            return cache_path

        image = self._render(source)
        if image is None:
            return None
        image.save(cache_path, format="JPEG", quality=78, optimize=True)
        return cache_path

    @staticmethod
    def _render(source):
        from PIL import Image

        if source.suffix.lower() == ".pdf":
            import fitz

            with fitz.open(str(source)) as pdf:
                if not pdf.page_count:
                    return None
                pixmap = pdf[0].get_pixmap(matrix=fitz.Matrix(0.75, 0.75), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        else:
            image = Image.open(source).convert("RGB")

        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        return image
