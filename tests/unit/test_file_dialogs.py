from pathlib import Path

from ui import file_dialogs


def test_downloads_folder_uses_qt_download_location(monkeypatch):
    monkeypatch.setattr(
        file_dialogs.QStandardPaths,
        "writableLocation",
        lambda _location: "C:/Users/Test/Downloads",
    )

    assert file_dialogs.downloads_folder() == "C:/Users/Test/Downloads"


def test_downloads_folder_falls_back_to_home_downloads(monkeypatch):
    monkeypatch.setattr(
        file_dialogs.QStandardPaths,
        "writableLocation",
        lambda _location: "",
    )
    monkeypatch.setattr(file_dialogs.Path, "home", lambda: Path("C:/Users/Test"))

    assert file_dialogs.downloads_folder() == "C:\\Users\\Test\\Downloads"


def test_downloads_file_path_places_suggested_filename_in_downloads(monkeypatch):
    monkeypatch.setattr(file_dialogs, "downloads_folder", lambda: "C:/Downloads")

    assert file_dialogs.downloads_file_path("export.xlsx") == "C:\\Downloads\\export.xlsx"
