from pathlib import Path

from client_update_worker import _write_state


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_update_worker_state_write_is_atomic_and_utf8(tmp_path):
    state = tmp_path / "worker.json"

    _write_state(state, {"status": "ready", "version": "0.1.1"})

    assert state.read_text(encoding="utf-8") == (
        '{"status": "ready", "version": "0.1.1"}'
    )
    assert list(tmp_path.glob("*.tmp")) == []


def test_gui_coordinator_uses_a_process_instead_of_terminating_a_qthread():
    source = (PROJECT_ROOT / "ui" / "update_coordinator.py").read_text(
        encoding="utf-8"
    )

    assert "QProcess" in source
    assert "QThread" not in source
    assert ".terminate()" in source
    assert "thread.terminate()" not in source


def test_client_package_contains_the_isolated_update_worker():
    spec = (PROJECT_ROOT / "deployment" / "mission_legal_client.spec").read_text(
        encoding="utf-8"
    )
    build = (PROJECT_ROOT / "deployment" / "build_windows.ps1").read_text(
        encoding="utf-8"
    )

    assert "client_update_worker.py" in spec
    assert "MissionLegalUpdateWorker" in spec
    assert "MissionLegalUpdateWorker.exe" in build


def test_raw_client_smoke_skips_only_the_velopack_installation_bootstrap():
    build = (PROJECT_ROOT / "deployment" / "build_windows.ps1").read_text(
        encoding="utf-8"
    )

    assert 'MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP = "1"' in build
    assert "PreviousVelopackBootstrapSkip" in build
    assert "Remove-Item Env:MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP" in build
    assert "Wait-Process -Timeout 180" in build
    assert ".WaitForExit(" not in build
