import hashlib
from pathlib import Path


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".jfif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
})


def document_file_dialog_filter():
    extensions = " ".join(
        f"*{extension}" for extension in sorted(SUPPORTED_DOCUMENT_EXTENSIONS)
    )
    return f"Documents ({extensions})"


def sha256_file(path, *, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def validate_document_file(path):
    """Return a user-safe rejection reason, or ``None`` for a valid document."""

    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
        return f"Unsupported file type: {path.suffix or 'no extension'}"
    try:
        if not path.is_file():
            return "The file is missing or is not a regular file."
        if path.stat().st_size <= 0:
            return "The file is empty."
        if path.suffix.lower() == ".pdf":
            import fitz

            with fitz.open(str(path)) as document:
                if document.page_count <= 0:
                    return "The PDF has no pages."
                document.load_page(0)
        else:
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
    except Exception:
        return "The file cannot be read as a valid PDF or image."
    return None
