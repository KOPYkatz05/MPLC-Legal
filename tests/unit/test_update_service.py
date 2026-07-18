import json
import sys
from types import SimpleNamespace

import pytest

from services.update_service import (
    ClientUpdateService,
    UpdateConfigurationError,
    UpdateNotReadyError,
    UpdateSourceConfig,
    load_update_config,
)


class FakeAsset:
    Version = "0.1.1"
    NotesMarkdown = "A dependable update."
    Size = 1234


class VersionedAsset(FakeAsset):
    def __init__(self, version):
        self.Version = version


class FakeManager:
    def __init__(self, *, update=True):
        self.update = update
        self.downloaded = False
        self.applied = []
        self.restarted_with_args = []

    def get_update_pending_restart(self):
        return FakeAsset() if self.downloaded else None

    def check_for_updates(self):
        if not self.update:
            return None
        return SimpleNamespace(TargetFullRelease=FakeAsset())

    def download_updates(self, _update_info, callback):
        for value in (5, 50, 40, 100):
            callback(value)
        self.downloaded = True

    def wait_exit_then_apply_updates(
        self,
        update,
        *,
        silent=False,
        restart=True,
        restart_args=None,
    ):
        self.applied.append(update)
        self.restarted_with_args.append(
            {
                "silent": silent,
                "restart": restart,
                "restart_args": restart_args,
            }
        )


def _config():
    return UpdateSourceConfig("https://updates.example.test/mission-legal")


def test_missing_update_source_disables_service(monkeypatch, tmp_path):
    monkeypatch.delenv("MISSION_LEGAL_UPDATE_URL", raising=False)
    monkeypatch.setenv("MISSION_LEGAL_UPDATE_CONFIG", str(tmp_path / "missing.json"))

    service = ClientUpdateService()

    assert service.enabled is False
    assert service.state == "disabled"
    assert service.check_and_download() is None


def test_update_config_rejects_embedded_secrets(monkeypatch, tmp_path):
    config = tmp_path / "update.json"
    config.write_text(
        json.dumps(
            {
                "url": "https://updates.example.test",
                "access_token": "must-not-be-embedded",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MISSION_LEGAL_UPDATE_URL", raising=False)

    with pytest.raises(UpdateConfigurationError, match="must not contain"):
        load_update_config(config)


def test_update_config_requires_https_for_nonlocal_sources(monkeypatch, tmp_path):
    config = tmp_path / "update.json"
    config.write_text(
        json.dumps({"url": "http://updates.example.test"}),
        encoding="utf-8",
    )
    monkeypatch.delenv("MISSION_LEGAL_UPDATE_URL", raising=False)

    with pytest.raises(UpdateConfigurationError, match="must use HTTPS"):
        load_update_config(config)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@updates.example.test/releases",
        "https://updates.example.test/releases?access_token=secret",
        "https://updates.example.test/releases#private-fragment",
    ],
)
def test_update_config_rejects_secrets_in_source_url(
    monkeypatch,
    tmp_path,
    url,
):
    config = tmp_path / "update.json"
    config.write_text(json.dumps({"url": url}), encoding="utf-8")
    monkeypatch.delenv("MISSION_LEGAL_UPDATE_URL", raising=False)

    with pytest.raises(UpdateConfigurationError, match="must not contain"):
        load_update_config(config)


def test_update_config_requires_a_json_boolean_for_prerelease(monkeypatch, tmp_path):
    config = tmp_path / "update.json"
    config.write_text(
        json.dumps(
            {
                "url": "https://updates.example.test/releases",
                "prerelease": "false",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MISSION_LEGAL_UPDATE_URL", raising=False)

    with pytest.raises(UpdateConfigurationError, match="JSON boolean"):
        load_update_config(config)


def test_no_available_update_returns_to_idle():
    manager = FakeManager(update=False)
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: manager,
    )

    assert service.check_and_download() is None
    assert service.state == "idle"
    assert service.prepared_update is None


def test_update_download_is_monotonic_and_becomes_ready():
    manager = FakeManager()
    progress = []
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: manager,
    )

    prepared = service.check_and_download(progress.append)

    assert prepared.version == "0.1.1"
    assert prepared.notes_markdown == "A dependable update."
    assert prepared.size == 1234
    assert progress == [5, 50, 50, 100]
    assert service.state == "ready"


def test_newer_feed_update_replaces_an_older_pending_update():
    class ThreeVersionManager(FakeManager):
        def __init__(self):
            super().__init__()
            self.pending = VersionedAsset("0.1.1")
            self.target = VersionedAsset("0.1.2")

        def get_update_pending_restart(self):
            return self.pending

        def check_for_updates(self):
            return SimpleNamespace(TargetFullRelease=self.target)

        def download_updates(self, _update_info, callback):
            self.downloaded = True
            self.pending = self.target
            callback(100)

    manager = ThreeVersionManager()
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: manager,
    )

    prepared = service.check_and_download()

    assert manager.downloaded is True
    assert prepared.version == "0.1.2"
    assert service.state == "ready"


def test_pending_update_remains_available_when_feed_is_offline():
    class OfflineManager(FakeManager):
        def get_update_pending_restart(self):
            return VersionedAsset("0.1.1")

        def check_for_updates(self):
            raise OSError("offline")

    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: OfflineManager(),
    )

    prepared = service.check_and_download()

    assert prepared.version == "0.1.1"
    assert service.state == "ready"


@pytest.mark.parametrize("target_version", ["0.1.1", "0.1.0"])
def test_same_or_older_feed_update_does_not_replace_pending(target_version):
    class ExistingPendingManager(FakeManager):
        def __init__(self):
            super().__init__()
            self.pending = VersionedAsset("0.1.1")

        def get_update_pending_restart(self):
            return self.pending

        def check_for_updates(self):
            return SimpleNamespace(TargetFullRelease=VersionedAsset(target_version))

    manager = ExistingPendingManager()
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: manager,
    )

    prepared = service.check_and_download()

    assert manager.downloaded is False
    assert prepared.version == "0.1.1"


def test_apply_requires_a_downloaded_update():
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: FakeManager(),
    )

    with pytest.raises(UpdateNotReadyError):
        service.apply_prepared_update()


def test_prepared_update_is_applied_once():
    manager = FakeManager()
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: manager,
    )
    service.check_and_download()

    service.apply_prepared_update()

    assert len(manager.applied) == 1
    assert manager.applied[0].Version == "0.1.1"


def test_staged_worker_update_can_be_loaded_and_restarted_with_arguments():
    manager = FakeManager()
    manager.downloaded = True
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: manager,
    )

    prepared = service.load_pending_update()
    service.apply_prepared_update(restart_args=["--update-smoke", "0.1.1"])

    assert prepared.version == "0.1.1"
    assert manager.restarted_with_args == [
        {
            "silent": False,
            "restart": True,
            "restart_args": ["--update-smoke", "0.1.1"],
        }
    ]


def test_failed_check_records_error_and_allows_retry():
    calls = []

    class FailingManager(FakeManager):
        def check_for_updates(self):
            calls.append("check")
            if len(calls) == 1:
                raise OSError("offline")
            return None

    manager = FailingManager()
    service = ClientUpdateService(
        _config(),
        manager_factory=lambda _config: manager,
    )

    with pytest.raises(OSError, match="offline"):
        service.check_and_download()
    assert service.state == "failed"
    assert service.error == "offline"

    assert service.check_and_download() is None
    assert service.state == "idle"
