import subprocess
import sys
from pathlib import Path


TASK_NAME = "Mission Legal Daily Digest"


class SchedulerService:
    def install_daily_digest_task(self, digest_time):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        python_path = Path(sys.executable).resolve()
        command = f'"{python_path}" "{main_path}" --send-daily-digest'
        result = subprocess.run(
            [
                "schtasks",
                "/Create",
                "/TN",
                TASK_NAME,
                "/TR",
                command,
                "/SC",
                "DAILY",
                "/ST",
                digest_time,
                "/F",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(message or "Failed to install scheduled task.")
        return True
