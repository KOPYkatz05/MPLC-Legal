import ipaddress
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

import server_main
from server import tls


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()).resolve()
    path = root / f"mission-legal-tls-{uuid.uuid4().hex}"
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_generate_local_tls_creates_ca_and_server_certificate(monkeypatch, tmp_path):
    monkeypatch.setattr(tls, "tls_directory", lambda: tmp_path)
    monkeypatch.setattr(tls, "_protect_keys", lambda *paths: None)

    paths = tls.generate_local_tls()

    ca = x509.load_pem_x509_certificate(paths["ca_cert"].read_bytes())
    server = x509.load_pem_x509_certificate(paths["server_cert"].read_bytes())
    serialization.load_pem_private_key(paths["server_key"].read_bytes(), None)
    assert ca.subject == server.issuer
    alternatives = server.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert "localhost" in alternatives.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("127.0.0.1") in alternatives.get_values_for_type(
        x509.IPAddress
    )


def test_generate_local_tls_reuses_existing_material(monkeypatch, tmp_path):
    monkeypatch.setattr(tls, "tls_directory", lambda: tmp_path)
    monkeypatch.setattr(tls, "_protect_keys", lambda *paths: None)
    first = tls.generate_local_tls()
    original = first["server_cert"].read_bytes()

    second = tls.generate_local_tls()

    assert second["server_cert"].read_bytes() == original


def test_existing_ca_is_preserved_when_lan_ip_requires_leaf_renewal(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(tls, "tls_directory", lambda: tmp_path)
    monkeypatch.setattr(tls, "_protect_keys", lambda *paths: None)
    addresses = {
        "values": [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]
    }
    monkeypatch.setattr(
        tls,
        "_server_addresses",
        lambda _hostname: list(addresses["values"]),
    )
    paths = tls.generate_local_tls()
    original_ca = paths["ca_cert"].read_bytes()
    original_ca_key = paths["ca_key"].read_bytes()
    original_server_key = paths["server_key"].read_bytes()
    original_server_cert = paths["server_cert"].read_bytes()

    lan_ip = ipaddress.ip_address("192.168.108.50")
    addresses["values"].append(x509.IPAddress(lan_ip))
    tls.generate_local_tls()

    renewed = x509.load_pem_x509_certificate(paths["server_cert"].read_bytes())
    alternatives = renewed.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert lan_ip in alternatives.get_values_for_type(x509.IPAddress)
    assert paths["ca_cert"].read_bytes() == original_ca
    assert paths["ca_key"].read_bytes() == original_ca_key
    assert paths["server_key"].read_bytes() == original_server_key
    assert paths["server_cert"].read_bytes() != original_server_cert


def test_generate_local_tls_refuses_incomplete_material_without_explicit_overwrite(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(tls, "tls_directory", lambda: tmp_path)
    existing_ca = tls.default_tls_paths()["ca_cert"]
    existing_ca.write_bytes(b"existing trust anchor")

    with pytest.raises(RuntimeError, match="Incomplete local TLS material"):
        tls.generate_local_tls(protect_keys=False)

    assert existing_ca.read_bytes() == b"existing trust anchor"
    assert not tls.default_tls_paths()["ca_key"].exists()

    paths = tls.generate_local_tls(overwrite=True, protect_keys=False)

    assert all(path.is_file() for path in paths.values())
    assert paths["ca_cert"].read_bytes() != b"existing trust anchor"


def test_generate_local_tls_can_preserve_source_caller_access(monkeypatch, tmp_path):
    protected = []
    monkeypatch.setattr(tls, "tls_directory", lambda: tmp_path)
    monkeypatch.setattr(
        tls,
        "_protect_keys",
        lambda *paths: protected.append(paths),
    )

    first = tls.generate_local_tls(protect_keys=False)
    second = tls.generate_local_tls(protect_keys=False)

    assert first == second
    assert protected == []


def test_generate_local_tls_defaults_to_strict_key_protection(monkeypatch, tmp_path):
    protected = []
    monkeypatch.setattr(tls, "tls_directory", lambda: tmp_path)
    monkeypatch.setattr(
        tls,
        "_protect_keys",
        lambda *paths: protected.append(paths),
    )

    paths = tls.generate_local_tls()
    tls.generate_local_tls()

    expected = (paths["ca_key"], paths["server_key"])
    assert protected == [expected, expected]


def test_only_frozen_server_main_enforces_the_production_key_acl():
    assert (
        server_main._should_enforce_production_tls_key_acl(frozen=False) is False
    )
    assert server_main._should_enforce_production_tls_key_acl(frozen=True) is True


def test_service_and_setup_keep_strict_tls_key_protection():
    server_entry = (REPO_ROOT / "server_main.py").read_text(encoding="utf-8")
    service_entry = (REPO_ROOT / "windows_service.py").read_text(encoding="utf-8")
    setup_entry = (REPO_ROOT / "server_setup.py").read_text(encoding="utf-8")

    assert "protect_keys=_should_enforce_production_tls_key_acl()" in server_entry
    assert "paths = generate_local_tls()" in service_entry
    assert "generate_local_tls(overwrite=args.overwrite_certificates)" in setup_entry
    assert "protect_keys=False" not in service_entry
    assert "protect_keys=False" not in setup_entry
