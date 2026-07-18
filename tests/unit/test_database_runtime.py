from pathlib import Path

from database import runtime


def test_explicit_database_path_takes_precedence(monkeypatch, tmp_path):
    configured = tmp_path / "custom" / "mission.db"
    monkeypatch.setenv(runtime.DATABASE_PATH_ENV, str(configured))

    assert runtime.get_database_path() == configured.resolve()


def test_explicit_data_directory_controls_default_database(monkeypatch, tmp_path):
    monkeypatch.delenv(runtime.DATABASE_PATH_ENV, raising=False)
    monkeypatch.setenv(runtime.APP_DATA_DIR_ENV, str(tmp_path))

    assert runtime.get_database_path() == tmp_path.resolve() / "app.db"


def test_sqlite_url_uses_absolute_forward_slash_path(tmp_path):
    url = runtime.sqlite_url(tmp_path / "app.db")

    assert url.startswith("sqlite:///")
    assert Path(url.removeprefix("sqlite:///")).name == "app.db"


def test_client_data_uses_local_app_data(monkeypatch, tmp_path):
    monkeypatch.delenv(runtime.CLIENT_DATA_DIR_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert runtime.get_client_data_dir() == tmp_path / "MissionLegal"
