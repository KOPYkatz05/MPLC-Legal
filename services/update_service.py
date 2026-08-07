import json
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from packaging.version import InvalidVersion, Version


logger = logging.getLogger(__name__)

UPDATE_CONFIG_FILENAME = "mission-legal-update.json"
UPDATE_CONFIG_ENV = "MISSION_LEGAL_UPDATE_CONFIG"
UPDATE_URL_ENV = "MISSION_LEGAL_UPDATE_URL"
UPDATE_PROVIDER_ENV = "MISSION_LEGAL_UPDATE_PROVIDER"
DISABLE_UPDATES_ENV = "MISSION_LEGAL_DISABLE_UPDATES"


class UpdateConfigurationError(RuntimeError):
    pass


class UpdateBusyError(RuntimeError):
    pass


class UpdateNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateSourceConfig:
    url: str
    provider: str = "http"
    prerelease: bool = False


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    notes_markdown: str = ""
    size: int = 0
    _native: object = field(default=None, repr=False, compare=False)


def installed_binary_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _validate_source_url(url, provider):
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise UpdateConfigurationError("Update source URL is invalid") from exc

    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise UpdateConfigurationError(
            "Update source URLs must not contain credentials, query tokens, or fragments"
        )

    if provider == "github":
        if parsed.scheme != "https" or not parsed.netloc:
            raise UpdateConfigurationError(
                "GitHub update sources must use a public HTTPS repository URL"
            )
        return

    if provider != "http":
        raise UpdateConfigurationError(f"Unsupported update provider: {provider}")

    if parsed.scheme in {"https", "file"}:
        return
    if parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1"}:
        return
    if not parsed.scheme and not getattr(sys, "frozen", False):
        # Local directory feeds are supported for installed-update tests.
        return
    raise UpdateConfigurationError(
        "Update sources must use HTTPS (local test feeds may use file paths or localhost)"
    )


def load_update_config(path=None):
    if os.environ.get(DISABLE_UPDATES_ENV) == "1":
        return None

    configured_path = path or os.environ.get(UPDATE_CONFIG_ENV)
    config_path = (
        Path(configured_path).expanduser().resolve()
        if configured_path
        else installed_binary_dir() / UPDATE_CONFIG_FILENAME
    )

    payload = {}
    if config_path.is_file():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UpdateConfigurationError(
                f"Update configuration is unreadable: {config_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise UpdateConfigurationError("Update configuration must be an object")

    forbidden = {"token", "password", "secret", "credential", "access_token"}
    if forbidden.intersection(str(key).lower() for key in payload):
        raise UpdateConfigurationError(
            "Update configuration must not contain embedded authentication secrets"
        )

    url = str(os.environ.get(UPDATE_URL_ENV) or payload.get("url") or "").strip()
    if not url:
        return None
    provider = str(
        os.environ.get(UPDATE_PROVIDER_ENV) or payload.get("provider") or "http"
    ).strip().lower()
    prerelease = payload.get("prerelease", False)
    if not isinstance(prerelease, bool):
        raise UpdateConfigurationError(
            "Update configuration 'prerelease' must be a JSON boolean"
        )
    _validate_source_url(url, provider)
    return UpdateSourceConfig(url=url, provider=provider, prerelease=prerelease)


def _asset_candidate(asset, native=None):
    return PreparedUpdate(
        version=str(asset.Version),
        notes_markdown=str(getattr(asset, "NotesMarkdown", "") or ""),
        size=int(getattr(asset, "Size", 0) or 0),
        _native=native if native is not None else asset,
    )


def _asset_version(asset):
    raw_version = str(getattr(asset, "Version", "") or "").strip()
    try:
        return Version(raw_version)
    except InvalidVersion as exc:
        raise UpdateConfigurationError(
            f"Update metadata contains an invalid version: {raw_version!r}"
        ) from exc


def _default_manager_factory(config):
    import velopack

    if config.provider == "github":
        source = velopack.GithubSource(
            config.url,
            access_token=None,
            prerelease=config.prerelease,
        )
    else:
        source = velopack.HttpSource(config.url)
    return velopack.UpdateManager(source)


class ClientUpdateService:
    """Thread-safe client update state around the Velopack Python API."""

    def __init__(self, config=None, manager_factory=None):
        self.config = config if config is not None else load_update_config()
        self._manager_factory = manager_factory or _default_manager_factory
        self._operation_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = "idle" if self.config else "disabled"
        self._prepared = None
        self._error = ""

    @property
    def enabled(self):
        return self.config is not None

    @property
    def state(self):
        with self._state_lock:
            return self._state

    @property
    def error(self):
        with self._state_lock:
            return self._error

    @property
    def prepared_update(self):
        with self._state_lock:
            return self._prepared

    def _set_state(self, state, *, prepared=None, error=""):
        with self._state_lock:
            self._state = state
            self._prepared = prepared
            self._error = str(error or "")

    def _manager(self):
        if not self.config:
            raise UpdateConfigurationError("Client updates are not configured")
        return self._manager_factory(self.config)

    def check_for_update(self):
        """Return lightweight release metadata without downloading a package."""

        if not self.enabled:
            return None
        if not self._operation_lock.acquire(blocking=False):
            raise UpdateBusyError("An update operation is already running")

        try:
            self._set_state("checking")
            manager = self._manager()
            pending = manager.get_update_pending_restart()
            pending_prepared = (
                _asset_candidate(pending) if pending is not None else None
            )
            try:
                update_info = manager.check_for_updates()
            except Exception:
                if pending_prepared is None:
                    raise
                logger.warning(
                    "Could not refresh the update feed; using the update already "
                    "staged for restart",
                    exc_info=True,
                )
                self._set_state("ready", prepared=pending_prepared)
                return pending_prepared

            if update_info is None:
                if pending_prepared is not None:
                    self._set_state("ready", prepared=pending_prepared)
                    return pending_prepared
                self._set_state("idle")
                return None

            target = update_info.TargetFullRelease
            if (
                pending is not None
                and _asset_version(target) <= _asset_version(pending)
            ):
                self._set_state("ready", prepared=pending_prepared)
                return pending_prepared

            available = _asset_candidate(target)
            self._set_state("available", prepared=available)
            return available
        except Exception as exc:
            self._set_state("failed", error=exc)
            logger.exception("Client update check failed")
            raise
        finally:
            self._operation_lock.release()

    def check_and_download(self, progress_callback=None):
        if not self.enabled:
            return None
        if not self._operation_lock.acquire(blocking=False):
            raise UpdateBusyError("An update operation is already running")

        try:
            self._set_state("checking")
            manager = self._manager()
            pending = manager.get_update_pending_restart()
            pending_prepared = _asset_candidate(pending) if pending is not None else None
            try:
                update_info = manager.check_for_updates()
            except Exception:
                if pending_prepared is None:
                    raise
                logger.warning(
                    "Could not refresh the update feed; using the update already "
                    "staged for restart",
                    exc_info=True,
                )
                self._set_state("ready", prepared=pending_prepared)
                return pending_prepared

            if update_info is None:
                if pending_prepared is not None:
                    self._set_state("ready", prepared=pending_prepared)
                    return pending_prepared
                self._set_state("idle")
                return None

            target = update_info.TargetFullRelease
            if pending is not None and _asset_version(target) <= _asset_version(pending):
                self._set_state("ready", prepared=pending_prepared)
                return pending_prepared

            self._set_state("downloading")
            last_progress = -1

            def report_progress(value):
                nonlocal last_progress
                progress = max(last_progress, min(100, max(0, int(value))))
                last_progress = progress
                if progress_callback is not None:
                    progress_callback(progress)

            manager.download_updates(update_info, report_progress)
            if last_progress < 100 and progress_callback is not None:
                progress_callback(100)

            pending = manager.get_update_pending_restart()
            prepared = _asset_candidate(target, native=pending or update_info)
            self._set_state("ready", prepared=prepared)
            return prepared
        except Exception as exc:
            self._set_state("failed", error=exc)
            logger.exception("Client update check/download failed")
            raise
        finally:
            self._operation_lock.release()

    def load_pending_update(self):
        """Load an update staged by the isolated update worker process."""

        if not self.enabled:
            return None
        if not self._operation_lock.acquire(blocking=False):
            raise UpdateBusyError("An update operation is already running")

        try:
            manager = self._manager()
            pending = manager.get_update_pending_restart()
            if pending is None:
                self._set_state("idle")
                return None
            prepared = _asset_candidate(pending)
            self._set_state("ready", prepared=prepared)
            return prepared
        except Exception as exc:
            self._set_state("failed", error=exc)
            logger.exception("Could not load the staged client update")
            raise
        finally:
            self._operation_lock.release()

    def apply_prepared_update(self, *, restart_args=None):
        prepared = self.prepared_update
        if self.state != "ready" or prepared is None:
            raise UpdateNotReadyError("No downloaded client update is ready")
        if not self._operation_lock.acquire(blocking=False):
            raise UpdateBusyError("An update operation is already running")

        try:
            self._set_state("applying", prepared=prepared)
            manager = self._manager()
            pending = manager.get_update_pending_restart()
            native_update = pending or prepared._native
            normalized_args = (
                None
                if restart_args is None
                else [str(value) for value in restart_args]
            )
            # The Python binding's immediate-exit helper can leave a frozen
            # PyInstaller process alive while Update.exe waits for that same
            # process. Launch the documented graceful-exit path, return to Qt,
            # and let the caller close the app normally.
            manager.wait_exit_then_apply_updates(
                native_update,
                silent=False,
                restart=True,
                restart_args=normalized_args,
            )
        except Exception as exc:
            self._set_state("failed", prepared=prepared, error=exc)
            logger.exception("Could not apply the prepared client update")
            raise
        finally:
            self._operation_lock.release()
