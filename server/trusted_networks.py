"""Persist the small allowlist used for LAN discovery and easy pairing."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from database.runtime import get_app_data_dir
from server.networking import discover_lan_ipv4_addresses


TRUSTED_NETWORKS_VERSION = 1
_MAX_TRUSTED_NETWORKS = 50


def trusted_networks_path() -> Path:
    return get_app_data_dir() / "Configuration" / "trusted-networks.json"


def _active_windows_profile_names() -> tuple[str, ...]:
    """Return active Windows network-profile names without localized parsing."""

    if os.name != "nt":
        return ()
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    powershell = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    command = (
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
        "Get-NetConnectionProfile -ErrorAction SilentlyContinue | "
        "Where-Object { $_.IPv4Connectivity -ne 'Disconnected' } | "
        "Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if completed.returncode != 0 or not completed.stdout.strip():
        return ()
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()
    values = payload if isinstance(payload, list) else [payload]
    names = []
    for value in values:
        name = str(value or "").strip()
        if name and len(name) <= 200 and name not in names:
            names.append(name)
    return tuple(sorted(names, key=str.casefold))


def _network_prefixes(addresses: Iterable[str]) -> tuple[str, ...]:
    prefixes = []
    for value in addresses:
        try:
            address = ipaddress.ip_address(str(value))
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address) or not address.is_private:
            continue
        # A /24 is deliberately a compatibility fallback. The Windows network
        # profile name is the primary identity when Windows makes it available.
        prefix = str(ipaddress.ip_network(f"{address}/24", strict=False))
        if prefix not in prefixes:
            prefixes.append(prefix)
    return tuple(sorted(prefixes))


def current_network_identity(
    *,
    addresses: Iterable[str] | None = None,
    profile_names: Iterable[str] | None = None,
) -> dict[str, object] | None:
    """Describe the current LAN with a stable, non-secret fingerprint."""

    if addresses is None:
        try:
            addresses = discover_lan_ipv4_addresses()
        except Exception:
            addresses = ()
    normalized_addresses = tuple(
        dict.fromkeys(str(value).strip() for value in addresses if str(value).strip())
    )
    prefixes = _network_prefixes(normalized_addresses)
    if not prefixes:
        return None

    if profile_names is None:
        profile_names = _active_windows_profile_names()
    names = tuple(
        sorted(
            {
                str(value).strip()
                for value in profile_names
                if str(value).strip() and len(str(value).strip()) <= 200
            },
            key=str.casefold,
        )
    )
    # Windows' network-profile name is the primary identity and survives
    # normal DHCP/subnet changes. The prefix is only a fail-closed fallback on
    # systems where Windows does not expose a usable profile.
    fingerprint_payload = (
        {"profiles": [name.casefold() for name in names]}
        if names
        else {"prefixes": list(prefixes)}
    )
    encoded = json.dumps(
        fingerprint_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    fingerprint = hashlib.sha256(encoded).hexdigest()
    label = " / ".join(names) if names else ", ".join(prefixes)
    return {
        "fingerprint": fingerprint,
        "network_id": fingerprint[:12],
        "name": label,
        "addresses": list(normalized_addresses),
        "prefixes": list(prefixes),
    }


class TrustedNetworkStore:
    """Small atomic allowlist with a short status cache for discovery traffic."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        identity_provider: Callable[[], Mapping[str, object] | None] | None = None,
        cache_seconds: float = 3.0,
    ):
        self.path = Path(path or trusted_networks_path())
        self.identity_provider = identity_provider or current_network_identity
        self.cache_seconds = max(0.0, float(cache_seconds))
        self._lock = threading.RLock()
        self._cached_at = 0.0
        self._cached_identity: dict[str, object] | None = None

    def _identity(self, *, refresh=False) -> dict[str, object] | None:
        now = time.monotonic()
        with self._lock:
            if (
                not refresh
                and self._cached_at
                and now - self._cached_at <= self.cache_seconds
            ):
                return (
                    dict(self._cached_identity)
                    if self._cached_identity is not None
                    else None
                )
        try:
            supplied = self.identity_provider()
        except Exception:
            supplied = None
        identity = dict(supplied) if isinstance(supplied, Mapping) else None
        if identity is not None:
            fingerprint = identity.get("fingerprint")
            if (
                not isinstance(fingerprint, str)
                or len(fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in fingerprint)
            ):
                identity = None
        with self._lock:
            self._cached_identity = dict(identity) if identity is not None else None
            self._cached_at = now
        return dict(identity) if identity is not None else None

    def _load(self) -> list[dict[str, str]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if (
            not isinstance(payload, dict)
            or payload.get("version") != TRUSTED_NETWORKS_VERSION
            or not isinstance(payload.get("networks"), list)
        ):
            return []
        networks = []
        for item in payload["networks"][:_MAX_TRUSTED_NETWORKS]:
            if not isinstance(item, dict):
                continue
            fingerprint = item.get("fingerprint")
            name = item.get("name")
            trusted_at = item.get("trusted_at")
            if (
                isinstance(fingerprint, str)
                and len(fingerprint) == 64
                and all(c in "0123456789abcdef" for c in fingerprint)
                and isinstance(name, str)
                and 0 < len(name) <= 200
                and isinstance(trusted_at, str)
                and 0 < len(trusted_at) <= 80
            ):
                networks.append(
                    {
                        "fingerprint": fingerprint,
                        "name": name,
                        "trusted_at": trusted_at,
                    }
                )
        return networks

    def _save(self, networks: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        payload = {
            "version": TRUSTED_NETWORKS_VERSION,
            "networks": networks[:_MAX_TRUSTED_NETWORKS],
        }
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def current_status(self, *, refresh=False) -> dict[str, object]:
        identity = self._identity(refresh=refresh)
        if identity is None:
            return {
                "available": False,
                "trusted": False,
                "network_id": "",
                "name": "No active local network",
                "addresses": [],
            }
        networks = self._load()
        trusted = any(
            item["fingerprint"] == identity["fingerprint"] for item in networks
        )
        return {
            "available": True,
            "trusted": trusted,
            "network_id": str(identity.get("network_id") or ""),
            "name": str(identity.get("name") or "Current network"),
            "addresses": list(identity.get("addresses") or []),
        }

    def trust_current(self) -> dict[str, object]:
        identity = self._identity(refresh=True)
        if identity is None:
            raise RuntimeError("No active local network is available to trust.")
        networks = self._load()
        fingerprint = str(identity["fingerprint"])
        networks = [
            item for item in networks if item["fingerprint"] != fingerprint
        ]
        networks.insert(
            0,
            {
                "fingerprint": fingerprint,
                "name": str(identity.get("name") or "Current network")[:200],
                "trusted_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._save(networks)
        return self.current_status(refresh=True)

    def forget_current(self) -> dict[str, object]:
        identity = self._identity(refresh=True)
        if identity is None:
            raise RuntimeError("No active local network is available.")
        fingerprint = str(identity["fingerprint"])
        networks = [
            item for item in self._load() if item["fingerprint"] != fingerprint
        ]
        self._save(networks)
        return self.current_status(refresh=True)

    def is_current_trusted(self) -> bool:
        return bool(self.current_status().get("trusted"))
