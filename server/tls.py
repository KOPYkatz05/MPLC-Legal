import ipaddress
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from database.runtime import get_app_data_dir
from server.data_acl import protect_private_key_files


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
    path.chmod(0o600)


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


def generate_local_tls(overwrite=False, *, protect_keys=True):
    """Generate local TLS material and optionally enforce the production DACL.

    Private-key files always receive an owner-only portable mode. Installed
    setup/service entry points retain ``protect_keys=True`` so Windows also
    receives the verified SYSTEM/Administrators-only DACL.
    """
    paths = default_tls_paths()
    root = paths["server_key"].parent
    root.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        existing = {
            name: os.path.lexists(path)
            for name, path in paths.items()
        }
        if any(existing.values()) and not all(existing.values()):
            missing = ", ".join(
                name for name, present in existing.items() if not present
            )
            raise RuntimeError(
                "Incomplete local TLS material; refusing to rotate the local "
                f"certificate authority implicitly. Missing: {missing}. "
                "Repair the existing files or explicitly use overwrite=True."
            )
        if all(existing.values()):
            unsafe = [
                name
                for name, path in paths.items()
                if path.is_symlink() or not path.is_file()
            ]
            if unsafe:
                raise RuntimeError(
                    "Existing local TLS material contains an unsafe path: "
                    + ", ".join(unsafe)
                )
            if protect_keys:
                _protect_keys(paths["ca_key"], paths["server_key"])
            else:
                _set_owner_only_file_mode(paths["ca_key"], paths["server_key"])
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
    if protect_keys:
        _protect_keys(paths["ca_key"], paths["server_key"])
    else:
        _set_owner_only_file_mode(paths["ca_key"], paths["server_key"])
    return paths


def _set_owner_only_file_mode(*paths):
    for path in paths:
        path.chmod(0o600)


def _protect_keys(*paths):
    protect_private_key_files(*paths)
