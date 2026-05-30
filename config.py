from pathlib import Path
import os
import sys


MISSIONS_ROOT = Path(
    os.environ.get(
        "MISSIONS_ROOT",
        str(Path.home() / "mission_data")
    )
)


if not MISSIONS_ROOT.exists():
    try:
        MISSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(
            f"Warning: Could not create mission root folder: {MISSIONS_ROOT}\n{e}",
            file=sys.stderr
        )
