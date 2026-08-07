ORG = "MissionLegal"
APP = "MissionLegalTracker"
WINDOWS_APP_USER_MODEL_ID = "MissionLegal.MissionLegalTracker"


def configure_windows_app_identity() -> bool:
    """Give Windows a stable identity instead of inheriting python.exe's."""
    import sys

    if not sys.platform.startswith("win"):
        return False

    try:
        import ctypes

        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        return False
    return result == 0


def refresh_windows_shell_icon_cache() -> bool:
    """Tell Explorer that the installed executable's icon may have changed."""
    import sys

    if not sys.platform.startswith("win"):
        return False

    try:
        import ctypes

        shell32 = ctypes.windll.shell32
        # Velopack keeps shortcut targets under the stable ``current`` path.
        # Notify that item first, then invalidate cached associations so an
        # updated executable icon is picked up without reinstalling shortcuts.
        shell32.SHChangeNotify(
            0x00002000,  # SHCNE_UPDATEITEM
            0x0005 | 0x1000,  # SHCNF_PATHW | SHCNF_FLUSH
            ctypes.c_wchar_p(sys.executable),
            None,
        )
        shell32.SHChangeNotify(
            0x08000000,  # SHCNE_ASSOCCHANGED
            0x0000 | 0x1000,  # SHCNF_IDLIST | SHCNF_FLUSH
            None,
            None,
        )
    except (AttributeError, OSError):
        return False
    return True
