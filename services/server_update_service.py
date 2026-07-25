"""Verified GitHub release updates for Mission Legal Server Manager."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version

from version import APP_VERSION


GITHUB_API = "https://api.github.com"
CONFIG_FILENAME = "server_release.json"
USER_AGENT = "MissionLegalServerManager"
MAX_METADATA_BYTES = 256 * 1024
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
SIGNATURE_SUFFIX = ".sig"


class ServerUpdateError(RuntimeError):
    pass


class ServerUpdateBusyError(ServerUpdateError):
    pass


@dataclass(frozen=True)
class ServerUpdateConfig:
    repository: str
    public_key: bytes
    channel: str = "stable"
    allow_prerelease: bool = False


@dataclass(frozen=True)
class ServerUpdate:
    version: str
    notes: str
    installer_name: str
    installer_size: int
    installer_url: str
    manifest_name: str
    manifest_url: str
    signature_url: str


@dataclass(frozen=True)
class PreparedServerUpdate:
    version: str
    installer_path: Path
    sha256: str
    notes: str = ""


def installed_binary_dir() -> Path:
    if getattr(sys, "frozen", False):
        resource_root = getattr(sys, "_MEIPASS", None)
        if resource_root:
            return Path(resource_root).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_staging_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "MissionLegal" / "ServerUpdates"


def load_server_update_config(path=None) -> ServerUpdateConfig | None:
    configured = os.environ.get("MISSION_LEGAL_SERVER_UPDATE_CONFIG")
    config_path = Path(path or configured or installed_binary_dir() / CONFIG_FILENAME)
    if (
        path is None
        and not configured
        and not getattr(sys, "frozen", False)
        and not config_path.is_file()
    ):
        config_path = installed_binary_dir() / "deployment" / CONFIG_FILENAME
    if not config_path.is_file():
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServerUpdateError("Server update configuration is unreadable.") from exc
    if not isinstance(payload, dict):
        raise ServerUpdateError("Server update configuration must be an object.")
    repository = str(payload.get("repository") or "").strip()
    if (
        repository.count("/") != 1
        or any(part in {"", ".", ".."} for part in repository.split("/"))
        or any(not (ch.isalnum() or ch in "._-/") for ch in repository)
    ):
        raise ServerUpdateError("Server update repository is invalid.")
    key_text = str(payload.get("manifestPublicKey") or "").strip()
    if not key_text:
        return None
    try:
        public_key = base64.b64decode(key_text, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key)
    except (ValueError, TypeError) as exc:
        raise ServerUpdateError("Server update verification key is invalid.") from exc
    return ServerUpdateConfig(
        repository=repository,
        public_key=public_key,
        channel=str(payload.get("channel") or "stable").strip().lower(),
        allow_prerelease=bool(payload.get("allowPrerelease", False)),
    )


def _read_url(url: str, *, limit: int, opener=urlopen) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=30) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > limit:
                raise ServerUpdateError("Update download exceeds its safety limit.")
            content = response.read(limit + 1)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise ServerUpdateError(f"Could not download update data: {exc}") from exc
    if len(content) > limit:
        raise ServerUpdateError("Update download exceeds its safety limit.")
    return content


def _asset_map(release) -> dict[str, dict]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return {}
    return {
        str(asset.get("name") or ""): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("name")
    }


class ServerUpdateService:
    def __init__(
        self,
        config=None,
        *,
        current_version=APP_VERSION,
        staging_root=None,
        opener=urlopen,
    ):
        self.config = config if config is not None else load_server_update_config()
        self.current_version = Version(str(current_version))
        self.staging_root = Path(staging_root or default_staging_root())
        self._opener = opener
        self._lock = threading.Lock()
        self._available: ServerUpdate | None = None
        self._prepared: PreparedServerUpdate | None = None

    @property
    def enabled(self):
        return self.config is not None

    @property
    def prepared_update(self):
        return self._prepared

    def check_for_update(self) -> ServerUpdate | None:
        if not self.config:
            return None
        url = f"{GITHUB_API}/repos/{self.config.repository}/releases?per_page=20"
        raw = _read_url(url, limit=MAX_METADATA_BYTES, opener=self._opener)
        try:
            releases = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServerUpdateError("GitHub returned invalid release metadata.") from exc
        if not isinstance(releases, list):
            raise ServerUpdateError("GitHub returned invalid release metadata.")

        candidates = []
        for release in releases:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            if release.get("prerelease") and not self.config.allow_prerelease:
                continue
            tag = str(release.get("tag_name") or "").strip().lstrip("v")
            try:
                version = Version(tag)
            except InvalidVersion:
                continue
            if version <= self.current_version:
                continue
            assets = _asset_map(release)
            installer_name = f"MissionLegalServerSetup-{version}.exe"
            manifest_name = f"MissionLegalServerSetup-{version}.json"
            signature_name = manifest_name + SIGNATURE_SUFFIX
            if not all(name in assets for name in (
                installer_name, manifest_name, signature_name
            )):
                continue
            installer = assets[installer_name]
            candidates.append(
                (
                    version,
                    ServerUpdate(
                        version=str(version),
                        notes=str(release.get("body") or ""),
                        installer_name=installer_name,
                        installer_size=int(installer.get("size") or 0),
                        installer_url=str(installer.get("browser_download_url") or ""),
                        manifest_name=manifest_name,
                        manifest_url=str(
                            assets[manifest_name].get("browser_download_url") or ""
                        ),
                        signature_url=str(
                            assets[signature_name].get("browser_download_url") or ""
                        ),
                    ),
                )
            )
        self._available = max(candidates, key=lambda item: item[0])[1] if candidates else None
        return self._available

    def download_update(self, update=None, progress_callback=None):
        update = update or self._available
        if update is None:
            raise ServerUpdateError("No server update is available.")
        if not self._lock.acquire(blocking=False):
            raise ServerUpdateBusyError("A server update is already being downloaded.")
        try:
            manifest_bytes = _read_url(
                update.manifest_url,
                limit=MAX_METADATA_BYTES,
                opener=self._opener,
            )
            signature_bytes = _read_url(
                update.signature_url,
                limit=4096,
                opener=self._opener,
            )
            try:
                signature = base64.b64decode(signature_bytes.strip(), validate=True)
                Ed25519PublicKey.from_public_bytes(
                    self.config.public_key
                ).verify(signature, manifest_bytes)
            except (ValueError, TypeError) as exc:
                raise ServerUpdateError(
                    "The server release manifest signature is invalid."
                ) from exc
            except Exception as exc:
                raise ServerUpdateError(
                    "The server release manifest signature is invalid."
                ) from exc
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ServerUpdateError("The server release manifest is invalid.") from exc
            expected = {
                "app_version": update.version,
                "filename": update.installer_name,
            }
            if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
                raise ServerUpdateError("The server release manifest does not match the release.")
            expected_hash = str(manifest.get("sha256") or "").lower()
            expected_size = int(manifest.get("size") or 0)
            if len(expected_hash) != 64 or any(ch not in "0123456789abcdef" for ch in expected_hash):
                raise ServerUpdateError("The server release manifest has an invalid SHA-256.")
            if expected_size <= 0 or expected_size > MAX_INSTALLER_BYTES:
                raise ServerUpdateError("The server release manifest has an invalid size.")

            target_dir = self.staging_root / update.version
            target_dir.mkdir(parents=True, exist_ok=True)
            partial = target_dir / (update.installer_name + ".partial")
            target = target_dir / update.installer_name
            request = Request(
                update.installer_url,
                headers={"User-Agent": USER_AGENT},
            )
            digest = hashlib.sha256()
            written = 0
            try:
                with self._opener(request, timeout=60) as response, partial.open("wb") as stream:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > expected_size or written > MAX_INSTALLER_BYTES:
                            raise ServerUpdateError("The server installer exceeds its declared size.")
                        digest.update(chunk)
                        stream.write(chunk)
                        if progress_callback:
                            progress_callback(min(100, int(written * 100 / expected_size)))
                if written != expected_size or digest.hexdigest() != expected_hash:
                    raise ServerUpdateError("The downloaded server installer failed verification.")
                os.replace(partial, target)
            finally:
                partial.unlink(missing_ok=True)
            self._prepared = PreparedServerUpdate(
                version=update.version,
                installer_path=target,
                sha256=expected_hash,
                notes=update.notes,
            )
            if progress_callback:
                progress_callback(100)
            return self._prepared
        finally:
            self._lock.release()

    def apply_prepared_update(self):
        prepared = self._prepared
        if prepared is None or not prepared.installer_path.is_file():
            raise ServerUpdateError("No verified server update is ready.")
        actual = hashlib.sha256(prepared.installer_path.read_bytes()).hexdigest()
        if actual != prepared.sha256:
            raise ServerUpdateError("The staged server installer changed after verification.")
        parameters = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG"
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(prepared.installer_path),
            parameters,
            str(prepared.installer_path.parent),
            1,
        )
        if int(result) <= 32:
            raise ServerUpdateError("Windows did not approve the server update.")
        return True
