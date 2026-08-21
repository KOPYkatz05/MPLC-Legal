"""Shared defaults for native file dialogs."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths


def downloads_folder() -> str:
    """Return the current user's Downloads directory for file-dialog defaults."""
    downloads = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation
    )
    if downloads:
        return downloads
    return str(Path.home() / "Downloads")


def downloads_file_path(filename: str) -> str:
    """Place a suggested filename in the Downloads directory."""
    return str(Path(downloads_folder()) / filename)
