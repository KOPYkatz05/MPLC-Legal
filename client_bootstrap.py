"""Run Velopack's process lifecycle before normal client initialization."""

import os
import sys


def run_client_bootstrap():
    """Handle install/update command-line hooks before Qt or app imports.

    Raw source runs are intentionally skipped. A frozen PyInstaller folder can
    run before Velopack packages it; in that case Velopack reports a portable
    locator and returns without initializing the desktop application.
    """

    if not getattr(sys, "frozen", False):
        return False
    if os.environ.get("MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP") == "1":
        return False

    import velopack
    from app_identity import refresh_windows_shell_icon_cache

    def refresh_updated_icon(*_args):
        refresh_windows_shell_icon_cache()

    (
        velopack.App()
        .set_auto_apply_on_startup(False)
        .on_after_install_fast_callback(refresh_updated_icon)
        .on_after_update_fast_callback(refresh_updated_icon)
        .on_restarted(refresh_updated_icon)
        .on_first_run(refresh_updated_icon)
        .run()
    )
    return True
