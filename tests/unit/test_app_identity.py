import sys

import app_identity


def test_windows_app_identity_uses_release_package_id(monkeypatch):
    calls = []

    class Shell32:
        @staticmethod
        def SetCurrentProcessExplicitAppUserModelID(value):
            calls.append(value)
            return 0

    class Windll:
        shell32 = Shell32()

    monkeypatch.setattr(sys, "platform", "win32")
    import ctypes

    monkeypatch.setattr(ctypes, "windll", Windll(), raising=False)

    assert app_identity.configure_windows_app_identity() is True
    assert calls == ["MissionLegal.MissionLegalTracker"]


def test_windows_app_identity_is_skipped_outside_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert app_identity.configure_windows_app_identity() is False


def test_windows_shell_icon_cache_refresh_notifies_executable_and_associations(
    monkeypatch,
):
    calls = []

    class Shell32:
        @staticmethod
        def SHChangeNotify(*args):
            calls.append(args)

    class Windll:
        shell32 = Shell32()

    import ctypes

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\App\current\MissionLegal.exe")
    monkeypatch.setattr(ctypes, "windll", Windll(), raising=False)

    assert app_identity.refresh_windows_shell_icon_cache() is True
    assert len(calls) == 2
    assert calls[0][0:2] == (0x00002000, 0x0005 | 0x1000)
    assert calls[0][2].value == r"C:\App\current\MissionLegal.exe"
    assert calls[1] == (0x08000000, 0x1000, None, None)
