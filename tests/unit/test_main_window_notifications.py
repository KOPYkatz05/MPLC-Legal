import builtins
import logging

from ui.main_window import MainWindow


def test_windows_toast_missing_dependency_is_cached(monkeypatch, caplog):
    imports = []
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "winotify":
            imports.append(name)
            raise ImportError("No module named 'winotify'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(MainWindow, "_windows_toast_available", None)

    with caplog.at_level(logging.INFO):
        assert MainWindow._send_windows_toast("Title", "Body") is False
        assert MainWindow._send_windows_toast("Title", "Body") is False

    assert imports == ["winotify"]
    assert "winotify is not installed" in caplog.text
