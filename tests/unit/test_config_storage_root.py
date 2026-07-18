from pathlib import Path

import config


def test_environment_storage_root_overrides_saved_qsettings(monkeypatch, tmp_path):
    saved = tmp_path / "saved"
    explicit = tmp_path / "explicit"
    monkeypatch.setattr(
        config.QSettings,
        "value",
        lambda self, key, default=None: str(saved),
    )
    monkeypatch.setenv("MISSIONS_ROOT", str(explicit))

    assert config.get_storage_root() == Path(explicit)
