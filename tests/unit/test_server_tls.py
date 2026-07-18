import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

import server_main
from server import tls


REPO_ROOT = Path(__file__).resolve().parents[2]


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
