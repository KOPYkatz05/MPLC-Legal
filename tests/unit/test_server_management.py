import json
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.management import (
    ManagementCommandError,
    MissionLegalManagement,
    validate_command_arguments,
)
from server.security import DeviceCredentialStore, PairingCodeStore
from services.database_backup_service import DatabaseBackupService
from services.pairing_package import decode_pairing_package


class FakeTrustedNetworkStore:
    def __init__(self, *, trusted=True):
        self.trusted = trusted

    def current_status(self, *, refresh=False):
        _ = refresh
        return {
            "available": True,
            "trusted": self.trusted,
            "network_id": "office123456",
            "name": "Mission Office",
            "addresses": ["192.168.108.50"],
        }

    def trust_current(self):
        self.trusted = True
        return self.current_status()

    def forget_current(self):
        self.trusted = False
        return self.current_status()

    def is_current_trusted(self):
        return self.trusted


@pytest.fixture
def management_tmp_path():
    """Avoid pytest's Windows 0o700 base-temp ACL under restricted test tokens."""

    temp_root = Path(tempfile.gettempdir()).resolve()
    path = temp_root / f"mission-legal-management-{uuid.uuid4().hex}"
    # Python 3.12 gives mode 0o700 directories a private Windows ACL. Restricted
    # test tokens cannot subsequently traverse that ACL, so inherit the temp
    # root's access policy and remove the directory in the same test process.
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        resolved = path.resolve(strict=False)
        if resolved.parent != temp_root or not resolved.name.startswith(
            "mission-legal-management-"
        ):
            raise RuntimeError(f"Refusing to clean unexpected test path: {resolved}")
        shutil.rmtree(resolved)


def _create_database(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO records (value) VALUES ('ready')")
        connection.commit()


def _management(tmp_path, **overrides):
    database_path = tmp_path / "app.db"
    if not database_path.exists():
        _create_database(database_path)
    defaults = {
        "pairing_store": PairingCodeStore(tmp_path / "pairing.json"),
        "device_store": DeviceCredentialStore(tmp_path / "devices.json"),
        "backup_service": DatabaseBackupService(
            database_path=database_path,
            local_backup_dir=tmp_path / "Backups",
        ),
        "configuration_provider": lambda: {"host": "0.0.0.0", "port": 8765},
        "pid_provider": lambda: 4242,
        "hostname_provider": lambda: "mission-server",
        "lan_address_provider": lambda: ("192.168.108.50",),
        "ca_certificate_provider": lambda: (
            "-----BEGIN CERTIFICATE-----\nPUBLIC CA\n-----END CERTIFICATE-----\n"
        ),
        "metrics_provider": lambda: {
            "server_process_cpu_percent": 4.5,
            "server_process_memory_bytes": 120_000_000,
            "system_cpu_percent": 23.25,
            "system_memory_used_bytes": 8_000_000_000,
            "system_memory_total_bytes": 16_000_000_000,
        },
        "trusted_network_store": FakeTrustedNetworkStore(),
    }
    defaults.update(overrides)
    return MissionLegalManagement(**defaults)


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        ("get_status", {"path": r"C:\Windows"}),
        ("create_pairing_code", {"lifetime_minutes": 1440}),
        ("create_verified_backup", {"destination": r"C:\Temp"}),
        ("restart_server", {"shell": "cmd.exe /c whoami"}),
        ("get_support_summary", {"include_file": "server.json"}),
    ],
)
def test_management_commands_reject_all_extra_path_and_shell_arguments(
    command, arguments
):
    with pytest.raises(ManagementCommandError) as error:
        validate_command_arguments(command, arguments)

    assert error.value.code == "invalid_arguments"


@pytest.mark.parametrize(
    "device_id",
    [
        "",
        "a" * 31,
        "a" * 33,
        "g" * 32,
        "../" + "a" * 29,
        "a" * 31 + "&",
        123,
    ],
)
def test_revoke_requires_exactly_32_hexadecimal_characters(device_id):
    with pytest.raises(ManagementCommandError) as error:
        validate_command_arguments("revoke_device", {"device_id": device_id})

    assert error.value.code == "invalid_device_id"


def test_pairing_command_returns_code_without_persisting_plaintext(
    management_tmp_path,
):
    management = _management(management_tmp_path)

    result = management.execute("create_pairing_code", {})

    assert result["code"].isdigit()
    assert len(result["code"]) == 6
    assert result["code"] not in (management_tmp_path / "pairing.json").read_text(
        encoding="utf-8"
    )
    persisted = json.loads(
        (management_tmp_path / "pairing.json").read_text(encoding="utf-8")
    )
    assert set(persisted) == {"code_hash", "expires_at", "attempts_remaining"}
    package = decode_pairing_package(result["setup_code"])
    assert package.server_url == "https://192.168.108.50:8765"
    assert package.pairing_code == result["code"]


def test_status_devices_revoke_and_support_summary_are_sanitized(
    management_tmp_path,
):
    management = _management(
        management_tmp_path,
        clock=lambda: datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        monotonic=iter([100.0, 112.9, 112.9]).__next__,
    )
    active = management.device_store.register("Front office")
    revoked = management.device_store.register("Old computer")
    assert management.device_store.revoke(revoked["device_id"])

    status = management.execute("get_status", {})
    listed = management.execute("list_devices", {})["devices"]
    support = management.execute("get_support_summary", {})

    assert status == {
        "state": "running",
        "service_name": "MissionLegalServer",
        "pid": 4242,
        "hostname": "mission-server",
        "app_version": status["app_version"],
        "api_version": "1",
        "schema_version": 1,
        "started_at": "2026-07-24T12:00:00+00:00",
        "uptime_seconds": 12,
        "host": "0.0.0.0",
        "port": 8765,
        "server_address": "https://192.168.108.50:8765",
        "network": {
            "available": True,
            "trusted": True,
            "network_id": "office123456",
            "name": "Mission Office",
            "addresses": ["192.168.108.50"],
        },
        "database_file_present": True,
        "server_process_cpu_percent": 4.5,
        "server_process_memory_bytes": 120_000_000,
        "system_cpu_percent": 23.25,
        "system_memory_used_bytes": 8_000_000_000,
        "system_memory_total_bytes": 16_000_000_000,
    }
    assert [device["state"] for device in listed] == ["active", "revoked"]
    assert listed[0]["device_id"] == active["device_id"]
    assert all("credential" not in key for device in listed for key in device)
    assert support["device_counts"] == {
        "active": 1,
        "pending": 0,
        "revoked": 1,
        "total": 2,
    }


def test_revoke_reports_missing_or_already_revoked_device(management_tmp_path):
    management = _management(management_tmp_path)
    missing = "a" * 32

    with pytest.raises(ManagementCommandError) as error:
        management.execute("revoke_device", {"device_id": missing})

    assert error.value.code == "device_not_found"
    assert missing not in error.value.message


def test_create_verified_backup_uses_database_backup_service(management_tmp_path):
    management = _management(management_tmp_path)

    result = management.execute("create_verified_backup", {})

    backup_path = management_tmp_path / "Backups" / result["filename"]
    assert backup_path.is_file()
    assert DatabaseBackupService.verify(backup_path)
    assert result["size_bytes"] == backup_path.stat().st_size
    assert len(result["sha256"]) == 64
    assert result["mirrored"] is False


def test_restart_is_an_injected_typed_operation(management_tmp_path):
    calls = []
    management = _management(
        management_tmp_path, restart_callback=lambda: calls.append("restart")
    )

    assert management.execute("restart_server", {}) == {"accepted": True}
    assert calls == ["restart"]


def test_restart_fails_closed_when_runtime_has_no_restart_callback(
    management_tmp_path,
):
    management = _management(management_tmp_path)

    with pytest.raises(ManagementCommandError) as error:
        management.execute("restart_server", {})

    assert error.value.code == "restart_unavailable"


def test_pairing_lifetime_uses_injected_clock_without_accepting_duration(
    management_tmp_path,
):
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

    class PairingStore:
        def create(self):
            return {"code": "123456", "expires_at": now + timedelta(minutes=10)}

    management = _management(
        management_tmp_path, pairing_store=PairingStore(), clock=lambda: now
    )

    result = management.execute("create_pairing_code", {})

    assert result["lifetime_seconds"] == 600
    assert result["expires_at"] == "2026-07-24T12:10:00+00:00"


def test_typed_network_commands_change_discovery_trust(management_tmp_path):
    networks = FakeTrustedNetworkStore(trusted=False)
    management = _management(
        management_tmp_path,
        trusted_network_store=networks,
    )

    trusted = management.execute("trust_current_network", {})
    forgotten = management.execute("forget_current_network", {})

    assert trusted["network"]["trusted"] is True
    assert forgotten["network"]["trusted"] is False


def test_status_metrics_fail_to_null_without_breaking_status(management_tmp_path):
    def fail_metrics():
        raise OSError("performance counters unavailable")

    management = _management(management_tmp_path, metrics_provider=fail_metrics)

    status = management.execute("get_status", {})

    assert status["state"] == "running"
    assert status["server_process_cpu_percent"] is None
    assert status["server_process_memory_bytes"] is None
    assert status["system_cpu_percent"] is None
    assert status["system_memory_used_bytes"] is None
    assert status["system_memory_total_bytes"] is None


def test_status_reports_validated_api_runtime_state(management_tmp_path):
    current = {"state": "starting"}
    management = _management(
        management_tmp_path,
        state_provider=lambda: current["state"],
    )

    for state in (
        "starting",
        "running",
        "restarting",
        "stopping",
        "unavailable",
    ):
        current["state"] = state.upper()
        assert management.execute("get_status", {})["state"] == state

    current["state"] = "invented"
    assert management.execute("get_status", {})["state"] == "unavailable"


def test_status_fails_runtime_state_provider_closed(management_tmp_path):
    def fail_state():
        raise OSError("runtime state unavailable")

    management = _management(
        management_tmp_path,
        state_provider=fail_state,
    )

    assert management.execute("get_status", {})["state"] == "unavailable"
