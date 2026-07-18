"""End-to-end probe for a locally installed Velopack update."""

import json
import os
import subprocess
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

from version import APP_VERSION


UPDATE_SMOKE_ENV = "MISSION_LEGAL_ENABLE_UPDATE_SMOKE_TEST"


def _write_result(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def run_installed_update_smoke_test(expected_version, result_file):
    """Stage, apply, restart, and prove a real installed client update."""

    result_path = Path(result_file).expanduser().resolve()
    if os.environ.get(UPDATE_SMOKE_ENV) != "1":
        _write_result(
            result_path,
            {
                "status": "failed",
                "error": f"{UPDATE_SMOKE_ENV}=1 is required",
            },
        )
        return 2

    try:
        expected = Version(str(expected_version))
        installed = Version(APP_VERSION)
    except InvalidVersion as exc:
        _write_result(result_path, {"status": "failed", "error": str(exc)})
        return 2

    if installed >= expected:
        _write_result(
            result_path,
            {
                "status": "complete",
                "installed_version": str(installed),
                "expected_version": str(expected),
                "executable": str(Path(sys.executable).resolve()),
            },
        )
        return 0

    worker_state = result_path.with_name(f"{result_path.name}.worker.json")
    worker_exe = Path(sys.executable).resolve().parent / "MissionLegalUpdateWorker.exe"
    try:
        if not worker_exe.is_file():
            raise RuntimeError(f"Installed update worker is missing: {worker_exe}")

        _write_result(
            result_path,
            {
                "status": "downloading",
                "installed_version": str(installed),
                "expected_version": str(expected),
            },
        )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            [str(worker_exe), "--state-file", str(worker_state)],
            cwd=str(worker_exe.parent),
            timeout=1800,
            check=False,
            creationflags=creation_flags,
        )
        try:
            worker_payload = json.loads(worker_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Update worker did not write a valid result") from exc
        if completed.returncode != 0 or worker_payload.get("status") != "ready":
            detail = worker_payload.get("error") or (
                f"update worker exited with code {completed.returncode}"
            )
            raise RuntimeError(str(detail))

        from services.update_service import ClientUpdateService

        service = ClientUpdateService()
        prepared = service.load_pending_update()
        if prepared is None:
            raise RuntimeError("No verified update was staged")
        offered = Version(prepared.version)
        if offered < expected:
            raise RuntimeError(
                f"Update feed offered {offered}, but {expected} or newer is required"
            )

        _write_result(
            result_path,
            {
                "status": "applying",
                "installed_version": str(installed),
                "offered_version": str(offered),
                "expected_version": str(expected),
            },
        )
        service.apply_prepared_update(
            restart_args=[
                "--installed-update-smoke-test",
                str(expected),
                str(result_path),
            ]
        )
        return 0
    except Exception as exc:
        _write_result(
            result_path,
            {
                "status": "failed",
                "installed_version": str(installed),
                "expected_version": str(expected),
                "error": str(exc),
            },
        )
        return 1
    finally:
        try:
            worker_state.unlink()
        except FileNotFoundError:
            pass
