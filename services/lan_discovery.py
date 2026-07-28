"""Small UDP discovery protocol for trusted local Mission Legal networks."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import httpx


DISCOVERY_PROTOCOL = 1
DISCOVERY_PORT = 43876
MAX_DISCOVERY_PACKET_BYTES = 16 * 1024
_QUERY_TYPE = "mission-legal-discover"
_RESPONSE_TYPE = "mission-legal-server"


@dataclass(frozen=True)
class DiscoveredServer:
    server_id: str
    name: str
    server_url: str
    ca_certificate_pem: str
    ca_sha256: str
    local: bool = False


@dataclass(frozen=True)
class _DiscoveredOffer:
    server_id: str
    name: str
    server_url: str
    ca_sha256: str


def _certificate_bytes(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("The discovery response did not contain a certificate.")
    try:
        certificate = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("The discovery certificate is invalid.") from exc
    if (
        not certificate
        or len(certificate) > 8 * 1024
        or b"-----BEGIN CERTIFICATE-----" not in certificate
        or b"-----END CERTIFICATE-----" not in certificate
        or b"PRIVATE KEY" in certificate
    ):
        raise ValueError("The discovery certificate is invalid.")
    return certificate


def certificate_sha256(value: object) -> str:
    return hashlib.sha256(_certificate_bytes(value)).hexdigest()


def _server_id(certificate_pem: str) -> str:
    return certificate_sha256(certificate_pem)


def _local_server_candidate() -> DiscoveredServer | None:
    """Return the installed server on this machine when its public CA is readable."""

    if os.name != "nt":
        return None
    try:
        import winreg

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\MissionLegal\Server",
            0,
            access,
        ):
            pass
    except OSError:
        return None
    program_data = os.environ.get("PROGRAMDATA")
    if not program_data:
        return None
    ca_path = Path(program_data) / "MissionLegal" / "Public" / "mission-legal-ca.pem"
    try:
        certificate = ca_path.read_text(encoding="ascii")
        fingerprint = certificate_sha256(certificate)
    except (OSError, ValueError):
        return None
    return DiscoveredServer(
        server_id=fingerprint,
        name=f"{socket.gethostname()} (this computer)",
        server_url="https://localhost:8765",
        ca_certificate_pem=certificate,
        ca_sha256=fingerprint,
        local=True,
    )


def _broadcast_targets(addresses: Iterable[str] | None = None) -> tuple[str, ...]:
    targets = ["255.255.255.255"]
    if addresses is None:
        try:
            from server.networking import discover_lan_ipv4_addresses

            addresses = discover_lan_ipv4_addresses()
        except Exception:
            addresses = ()
    for value in addresses:
        try:
            address = ipaddress.ip_address(str(value))
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address) or not address.is_private:
            continue
        broadcast = str(
            ipaddress.ip_network(f"{address}/24", strict=False).broadcast_address
        )
        if broadcast not in targets:
            targets.append(broadcast)
    return tuple(targets)


def _parse_response(
    packet: bytes,
    source_address: str,
    nonce: str,
) -> _DiscoveredOffer | None:
    if not packet or len(packet) > MAX_DISCOVERY_PACKET_BYTES:
        return None
    try:
        payload = json.loads(packet.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("type") != _RESPONSE_TYPE
        or payload.get("protocol") != DISCOVERY_PROTOCOL
        or payload.get("nonce") != nonce
    ):
        return None
    try:
        address = ipaddress.ip_address(source_address)
        port = int(payload.get("port"))
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(address, ipaddress.IPv4Address)
        or not (address.is_private or address.is_loopback)
        or not 1 <= port <= 65535
    ):
        return None
    name = str(payload.get("name") or "").strip()
    claimed_fingerprint = str(payload.get("ca_sha256") or "").lower()
    if (
        not name
        or len(name) > 200
        or len(claimed_fingerprint) != 64
        or any(c not in "0123456789abcdef" for c in claimed_fingerprint)
        or payload.get("server_id") != claimed_fingerprint
    ):
        return None
    return _DiscoveredOffer(
        server_id=claimed_fingerprint,
        name=name,
        server_url=f"https://{address}:{port}",
        ca_sha256=claimed_fingerprint,
    )


def _fetch_pairing_certificate(
    offer: _DiscoveredOffer,
    *,
    timeout: float,
) -> DiscoveredServer | None:
    """Bootstrap the public CA, then bind it to the advertised fingerprint."""

    try:
        with httpx.Client(
            base_url=offer.server_url,
            verify=False,
            trust_env=False,
            timeout=max(0.2, float(timeout)),
        ) as client:
            response = client.get("/pair/bootstrap")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    certificate = payload.get("ca_certificate_pem")
    try:
        fingerprint = certificate_sha256(certificate)
    except ValueError:
        return None
    if (
        fingerprint != offer.ca_sha256
        or payload.get("ca_sha256") != fingerprint
        or payload.get("server_id") != fingerprint
    ):
        return None
    return DiscoveredServer(
        server_id=fingerprint,
        name=offer.name,
        server_url=offer.server_url,
        ca_certificate_pem=str(certificate),
        ca_sha256=fingerprint,
    )


def discover_servers(
    timeout: float = 2.0,
    *,
    include_local=True,
    targets: Iterable[str] | None = None,
) -> tuple[DiscoveredServer, ...]:
    """Discover trusted-LAN servers, preferring an installed local server."""

    found: dict[str, DiscoveredServer] = {}
    if include_local:
        local = _local_server_candidate()
        if local is not None:
            found[local.server_id] = local

    nonce = uuid.uuid4().hex
    query = json.dumps(
        {
            "type": _QUERY_TYPE,
            "protocol": DISCOVERY_PROTOCOL,
            "nonce": nonce,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))
        for target in tuple(targets or _broadcast_targets()):
            try:
                sock.sendto(query, (str(target), DISCOVERY_PORT))
            except OSError:
                continue
        deadline = time.monotonic() + max(0.05, float(timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                packet, source = sock.recvfrom(MAX_DISCOVERY_PACKET_BYTES + 1)
            except socket.timeout:
                break
            except OSError:
                break
            offer = _parse_response(packet, source[0], nonce)
            candidate = (
                _fetch_pairing_certificate(
                    offer,
                    timeout=max(0.2, deadline - time.monotonic()),
                )
                if offer is not None
                else None
            )
            if candidate is not None and candidate.server_id not in found:
                found[candidate.server_id] = candidate
    finally:
        sock.close()
    return tuple(found.values())


class LanDiscoveryResponder:
    """Respond to client broadcasts only while the active network is trusted."""

    def __init__(
        self,
        *,
        enabled_provider: Callable[[], bool],
        ca_certificate_provider: Callable[[], str],
        port_provider: Callable[[], int],
        name_provider: Callable[[], str] = socket.gethostname,
        network_addresses_provider: Callable[[], Iterable[str]] | None = None,
        network_changed_callback: Callable[[tuple[str, ...]], None] | None = None,
    ):
        self.enabled_provider = enabled_provider
        self.ca_certificate_provider = ca_certificate_provider
        self.port_provider = port_provider
        self.name_provider = name_provider
        self.network_addresses_provider = network_addresses_provider
        self.network_changed_callback = network_changed_callback
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._last_addresses: tuple[str, ...] | None = None

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _network_addresses(self) -> tuple[str, ...]:
        if self.network_addresses_provider is not None:
            provider = self.network_addresses_provider
        else:
            from server.networking import discover_lan_ipv4_addresses

            provider = discover_lan_ipv4_addresses
        try:
            return tuple(sorted({str(value) for value in provider()}))
        except Exception:
            return ()

    def _check_network_change(self) -> None:
        addresses = self._network_addresses()
        previous = self._last_addresses
        self._last_addresses = addresses
        if (
            previous is not None
            and addresses != previous
            and self.network_changed_callback is not None
        ):
            self.network_changed_callback(addresses)

    @staticmethod
    def _query_nonce(packet: bytes) -> str | None:
        if not packet or len(packet) > 1024:
            return None
        try:
            payload = json.loads(packet.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        nonce = payload.get("nonce")
        if (
            payload.get("type") != _QUERY_TYPE
            or payload.get("protocol") != DISCOVERY_PROTOCOL
            or not isinstance(nonce, str)
            or len(nonce) != 32
            or any(character not in "0123456789abcdef" for character in nonce)
        ):
            return None
        return nonce

    def serve_forever(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket = sock
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(1.0)
            while not self._stop.is_set():
                self._check_network_change()
                try:
                    packet, source = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    continue
                nonce = self._query_nonce(packet)
                if nonce is None:
                    continue
                try:
                    if not self.enabled_provider():
                        continue
                    certificate = self.ca_certificate_provider()
                    fingerprint = certificate_sha256(certificate)
                    port = int(self.port_provider())
                    name = str(self.name_provider()).strip()
                except Exception:
                    continue
                if not 1 <= port <= 65535 or not name or len(name) > 200:
                    continue
                response = json.dumps(
                    {
                        "type": _RESPONSE_TYPE,
                        "protocol": DISCOVERY_PROTOCOL,
                        "nonce": nonce,
                        "server_id": fingerprint,
                        "name": name,
                        "port": port,
                        "ca_sha256": fingerprint,
                    },
                    separators=(",", ":"),
                ).encode("utf-8")
                if len(response) > MAX_DISCOVERY_PACKET_BYTES:
                    continue
                try:
                    sock.sendto(response, source)
                except OSError:
                    continue
        finally:
            self._socket = None
            try:
                sock.close()
            except OSError:
                pass
