import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from server.security import DeviceCredentialStore, PairingCodeStore


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / f"mission-legal-server-security-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_pairing_code_is_one_time(tmp_path):
    store = PairingCodeStore(tmp_path / "pairing.json")
    pairing = store.create()

    assert store.consume(pairing["code"]) is True
    assert store.consume(pairing["code"]) is False


def test_pairing_code_locks_after_five_bad_attempts(tmp_path):
    path = tmp_path / "pairing.json"
    store = PairingCodeStore(path)
    pairing = store.create()

    for _ in range(5):
        assert store.consume("000000") is False

    assert json.loads(path.read_text(encoding="utf-8"))["attempts_remaining"] == 0
    assert store.consume(pairing["code"]) is False


def test_pairing_code_allows_only_one_concurrent_claim(tmp_path):
    store = PairingCodeStore(tmp_path / "pairing.json")
    pairing = store.create()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(store.consume, [pairing["code"]] * 8))

    assert results.count(True) == 1
    assert results.count(False) == 7


def test_pairing_code_survives_failed_registration_action(tmp_path):
    store = PairingCodeStore(tmp_path / "pairing.json")
    pairing = store.create()

    def fail():
        raise OSError("device store unavailable")

    try:
        store.consume_and_execute(pairing["code"], fail)
    except OSError:
        pass
    else:
        raise AssertionError("The injected registration failure did not escape")

    assert store.consume(pairing["code"]) is True


def test_device_credentials_can_be_authenticated_and_revoked(tmp_path):
    path = tmp_path / "devices.json"
    store = DeviceCredentialStore(path)
    registered = store.register("Reception computer")

    authenticated = store.authenticate(
        registered["device_id"], registered["credential"]
    )
    assert authenticated["device_name"] == "Reception computer"
    assert registered["credential"] not in path.read_text(encoding="utf-8")

    assert store.revoke(registered["device_id"]) is True
    assert store.authenticate(
        registered["device_id"], registered["credential"]
    ) is None
    listed = store.list_devices()
    assert listed[0]["device_name"] == "Reception computer"
    assert listed[0]["revoked_at"]
    assert "credential_hash" not in listed[0]


def test_unreturned_device_registration_can_be_removed(tmp_path):
    store = DeviceCredentialStore(tmp_path / "devices.json")
    registered = store.register("Interrupted pairing")

    assert store.remove(registered["device_id"]) is True
    assert store.authenticate(
        registered["device_id"], registered["credential"]
    ) is None


def test_pending_device_cannot_authenticate_until_confirmed(tmp_path):
    store = DeviceCredentialStore(tmp_path / "devices.json")
    registered = store.register("Pending client", pending_confirmation=True)

    assert store.authenticate(
        registered["device_id"], registered["credential"]
    ) is None
    assert store.authenticate(
        registered["device_id"],
        registered["credential"],
        allow_pending=True,
    ) is not None
    assert store.list_devices()[0]["pending_confirmation"] is True
    assert store.confirm(registered["device_id"]) is True
    assert store.authenticate(
        registered["device_id"], registered["credential"]
    )["device_name"] == "Pending client"
    assert store.remove_pending(registered["device_id"]) is False
    assert store.list_devices()[0]["pending_confirmation"] is False
    assert store.authenticate(
        registered["device_id"], registered["credential"]
    ) is not None


def test_device_registration_is_serialized_across_processes(tmp_path):
    path = tmp_path / "devices.json"
    gate = tmp_path / "start"
    script = (
        "import sys,time; from pathlib import Path; "
        "from server.security import DeviceCredentialStore; "
        "gate=Path(sys.argv[2]); "
        "deadline=time.monotonic()+20; "
        "\nwhile not gate.exists():\n"
        "    assert time.monotonic() < deadline\n"
        "    time.sleep(0.01)\n"
        "DeviceCredentialStore(sys.argv[1]).register(sys.argv[3])"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(gate), f"Client {index}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(6)
    ]
    gate.write_text("go", encoding="utf-8")
    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            failures.append(stderr or stdout)

    assert failures == []
    assert {device["device_name"] for device in DeviceCredentialStore(path).list_devices()} == {
        f"Client {index}" for index in range(6)
    }
