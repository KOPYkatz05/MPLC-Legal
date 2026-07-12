import ipaddress
import os
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from database.runtime import get_app_data_dir


def tls_directory():
    return get_app_data_dir() / "Configuration" / "tls"


def default_tls_paths():
    root = tls_directory()
    return {
        "ca_cert": root / "mission-legal-ca.pem",
        "ca_key": root / "mission-legal-ca-key.pem",
        "server_cert": root / "mission-legal-server.pem",
        "server_key": root / "mission-legal-server-key.pem",
    }


def _private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _write_private_key(key, path):
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def _server_addresses(hostname):
    names = {hostname, socket.getfqdn(), "localhost"}
    values = [x509.DNSName(name) for name in sorted(names) if name]
    values.extend([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])
    try:
        for result in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = result[4][0]
            values.append(x509.IPAddress(ipaddress.ip_address(address)))
    except OSError:
        pass
    return list(dict.fromkeys(values))


def generate_local_tls(overwrite=False):
    paths = default_tls_paths()
    root = paths["server_key"].parent
    root.mkdir(parents=True, exist_ok=True)
    if not overwrite and all(path.exists() for path in paths.values()):
        return paths

    now = datetime.now(timezone.utc)
    ca_key = _private_key()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mission Legal Local CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = _private_key()
    hostname = socket.gethostname()
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(_server_addresses(hostname)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_private_key(ca_key, paths["ca_key"])
    _write_private_key(server_key, paths["server_key"])
    paths["ca_cert"].write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    paths["server_cert"].write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    _protect_keys(paths["ca_key"], paths["server_key"])
    return paths


def _protect_keys(*paths):
    if os.name != "nt":
        for path in paths:
            path.chmod(0o600)
        return
    username = os.environ.get("USERNAME")
    for path in paths:
        grants = ["SYSTEM:F", "Administrators:F"]
        if username:
            grants.append(f"{username}:R")
        command = ["icacls", str(path), "/inheritance:r", "/grant:r", *grants]
        subprocess.run(command, capture_output=True, check=False)
