"""Discover stable, client-reachable addresses for the local server."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable


_ROUTE_PROBES = (
    ("192.0.2.1", 9),
    ("198.51.100.1", 9),
    ("203.0.113.1", 9),
)
_RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def _rfc1918_address(value: object) -> str | None:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return None
    if not isinstance(address, ipaddress.IPv4Address):
        return None
    if not any(address in network for network in _RFC1918_NETWORKS):
        return None
    return str(address)


def _append_address(items: list[str], value: object) -> None:
    normalized = _rfc1918_address(value)
    if normalized and normalized not in items:
        items.append(normalized)


def discover_lan_ipv4_addresses(
    hostname: str | None = None,
    *,
    route_probe: Callable[[tuple[str, int]], str | None] | None = None,
    resolver: Callable[..., Iterable[tuple]] | None = None,
) -> tuple[str, ...]:
    """Return active RFC1918 addresses in preferred connection order.

    A UDP ``connect`` only asks Windows which interface it would use; it does
    not transmit application data. Hostname resolution is retained as a second
    source because multi-homed servers can expose more than the default route.
    """

    if route_probe is None:

        def route_probe(target):
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(target)
                return probe.getsockname()[0]
            except OSError:
                return None
            finally:
                probe.close()

    if resolver is None:
        resolver = socket.getaddrinfo

    addresses: list[str] = []
    for target in _ROUTE_PROBES:
        _append_address(addresses, route_probe(target))

    names = []
    for value in (hostname, socket.gethostname(), socket.getfqdn()):
        value = str(value or "").strip()
        if value and value not in names:
            names.append(value)
    for name in names:
        try:
            results = resolver(name, None, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            continue
        for result in results:
            try:
                value = result[4][0]
            except (IndexError, TypeError):
                continue
            _append_address(addresses, value)
    return tuple(addresses)


def preferred_server_url(
    port: int,
    *,
    hostname: str | None = None,
    addresses: Iterable[str] | None = None,
) -> str:
    """Return the LAN-IP URL clients should copy from Server Manager."""

    if not 1 <= int(port) <= 65535:
        raise ValueError("port must be between 1 and 65535")
    hostname = str(hostname or socket.gethostname()).strip()
    discovered = (
        tuple(addresses)
        if addresses is not None
        else discover_lan_ipv4_addresses(hostname)
    )
    for value in discovered:
        normalized = _rfc1918_address(value)
        if normalized:
            return f"https://{normalized}:{int(port)}"
    if not hostname:
        raise RuntimeError("Windows did not report a usable server address.")
    return f"https://{hostname}:{int(port)}"
