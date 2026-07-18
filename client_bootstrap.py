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

    velopack.App().set_auto_apply_on_startup(False).run()
    return True
