import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from server.trusted_networks import TrustedNetworkStore, current_network_identity


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / f"mission-legal-trusted-networks-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_windows_profile_is_primary_network_identity_across_dhcp_changes():
    first = current_network_identity(
        addresses=["192.168.10.20"],
        profile_names=["Mission Office"],
    )
    moved = current_network_identity(
        addresses=["10.44.0.18"],
        profile_names=["Mission Office"],
    )

    assert first["fingerprint"] == moved["fingerprint"]
    assert first["network_id"] == moved["network_id"]


def test_private_prefix_is_fail_closed_identity_fallback():
    first = current_network_identity(
        addresses=["192.168.10.20"],
        profile_names=[],
    )
    other = current_network_identity(
        addresses=["192.168.11.20"],
        profile_names=[],
    )

    assert first["fingerprint"] != other["fingerprint"]


def test_trusted_network_store_round_trip(tmp_path):
    identity = current_network_identity(
        addresses=["192.168.108.50"],
        profile_names=["Mission Office"],
    )
    store = TrustedNetworkStore(
        tmp_path / "trusted-networks.json",
        identity_provider=lambda: identity,
        cache_seconds=0,
    )

    assert store.current_status()["trusted"] is False
    assert store.trust_current()["trusted"] is True
    assert store.current_status()["trusted"] is True
    assert store.forget_current()["trusted"] is False
