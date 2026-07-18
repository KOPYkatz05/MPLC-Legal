import json

from utils.installed_update_smoke import (
    UPDATE_SMOKE_ENV,
    run_installed_update_smoke_test,
)
from version import APP_VERSION


def test_installed_update_smoke_is_explicitly_gated(monkeypatch, tmp_path):
    result = tmp_path / "result.json"
    monkeypatch.delenv(UPDATE_SMOKE_ENV, raising=False)

    exit_code = run_installed_update_smoke_test(APP_VERSION, result)

    assert exit_code == 2
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "failed"


def test_installed_update_smoke_records_completed_restarted_version(
    monkeypatch,
    tmp_path,
):
    result = tmp_path / "result.json"
    monkeypatch.setenv(UPDATE_SMOKE_ENV, "1")

    exit_code = run_installed_update_smoke_test(APP_VERSION, result)

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "complete"
    assert payload["installed_version"] == APP_VERSION
