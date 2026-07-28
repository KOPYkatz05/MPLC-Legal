import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from services.api_client import (
    MissionLegalApiClient,
    _installed_local_server_url,
)


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / f"mission-legal-api-localhost-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


class _RegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _InstalledRegistry:
    HKEY_LOCAL_MACHINE = object()
    KEY_READ = 1
    KEY_WOW64_64KEY = 2

    @staticmethod
    def OpenKey(root, path, reserved, access):
        assert root is _InstalledRegistry.HKEY_LOCAL_MACHINE
        assert path == r"Software\MissionLegal\Server"
        assert reserved == 0
        assert access == 3
        return _RegistryKey()


def test_matching_installed_server_ca_uses_localhost_and_preserves_port(tmp_path):
    configured_ca = tmp_path / "client-ca.pem"
    configured_ca.write_text("PUBLIC CA", encoding="ascii")
    public_root = tmp_path / "ProgramData"
    public_ca = (
        public_root
        / "MissionLegal"
        / "Public"
        / "mission-legal-ca.pem"
    )
    public_ca.parent.mkdir(parents=True)
    public_ca.write_text("PUBLIC CA", encoding="ascii")

    assert _installed_local_server_url(
        "https://192.168.108.50:18765",
        configured_ca,
        platform="win32",
        environment={"PROGRAMDATA": str(public_root)},
        registry_module=_InstalledRegistry,
    ) == "https://localhost:18765"


def test_mismatched_local_ca_does_not_override_saved_server(tmp_path):
    configured_ca = tmp_path / "client-ca.pem"
    configured_ca.write_text("EXPECTED", encoding="ascii")
    public_root = tmp_path / "ProgramData"
    public_ca = (
        public_root
        / "MissionLegal"
        / "Public"
        / "mission-legal-ca.pem"
    )
    public_ca.parent.mkdir(parents=True)
    public_ca.write_text("OTHER", encoding="ascii")

    assert (
        _installed_local_server_url(
            "https://192.168.108.50:8765",
            configured_ca,
            platform="win32",
            environment={"PROGRAMDATA": str(public_root)},
            registry_module=_InstalledRegistry,
        )
        is None
    )


def test_explicit_api_url_is_never_replaced_by_local_detection(monkeypatch):
    MissionLegalApiClient.close_environment_client()
    calls = []
    monkeypatch.delenv("MISSION_LEGAL_SERVER_PROCESS", raising=False)
    monkeypatch.setenv("MISSION_LEGAL_API_URL", "https://explicit.test:8765")
    monkeypatch.setenv("MISSION_LEGAL_API_CERT", "explicit-ca.pem")
    monkeypatch.setattr(
        "services.api_client._installed_local_server_url",
        lambda *_args, **_kwargs: calls.append(True) or "https://localhost:8765",
    )

    client = MissionLegalApiClient.from_environment()

    assert client.base_url == "https://explicit.test:8765"
    assert calls == []
    MissionLegalApiClient.close_environment_client()
