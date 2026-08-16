from types import SimpleNamespace

import pytest

from services.api_client import ApiCompatibilityError, MissionLegalApiClient
from ui.update_coordinator import required_update_version_problem
from version import (
    API_VERSION,
    APP_VERSION,
    MAX_SUPPORTED_SERVER_API_VERSION,
    MIN_SUPPORTED_CLIENT_VERSION,
    MIN_SUPPORTED_SERVER_API_VERSION,
    SCHEMA_VERSION,
)


def test_server_requires_the_same_application_release():
    assert MIN_SUPPORTED_CLIENT_VERSION == APP_VERSION


def test_last_entry_date_protocol_requires_coordinated_server_and_client():
    assert APP_VERSION == "0.3.4"
    assert API_VERSION == "4"
    assert MIN_SUPPORTED_SERVER_API_VERSION == "4"
    assert MAX_SUPPORTED_SERVER_API_VERSION == "4"


def test_compatible_server_versions_are_accepted():
    assert MissionLegalApiClient.validate_compatibility(
        {
            "api_version": API_VERSION,
            "app_version": APP_VERSION,
            "schema_version": SCHEMA_VERSION,
        }
    ) is True


def test_incompatible_api_version_is_rejected():
    with pytest.raises(ApiCompatibilityError, match="incompatible") as captured:
        MissionLegalApiClient.validate_compatibility(
            {
                "api_version": "999",
                "app_version": APP_VERSION,
                "schema_version": SCHEMA_VERSION,
                "minimum_client_version": "999.0.0",
            }
        )
    assert captured.value.client_update_required is True
    assert captured.value.reason == ApiCompatibilityError.CLIENT_UPDATE_REQUIRED
    assert captured.value.required_client_version == "999.0.0"


def test_newer_server_api_requires_a_truthful_client_version_floor():
    with pytest.raises(ApiCompatibilityError, match="does not identify") as captured:
        MissionLegalApiClient.validate_compatibility(
            {"api_version": "999", "minimum_client_version": APP_VERSION}
        )

    assert captured.value.client_update_required is False
    assert captured.value.reason == ApiCompatibilityError.INVALID_METADATA


def test_older_server_api_requires_server_update_not_client_update():
    with pytest.raises(ApiCompatibilityError, match="Update Mission Legal Server") as captured:
        MissionLegalApiClient.validate_compatibility(
            {"api_version": "0", "schema_version": SCHEMA_VERSION}
        )
    assert captured.value.client_update_required is False
    assert captured.value.reason == ApiCompatibilityError.SERVER_UPDATE_REQUIRED


def test_server_schema_changes_do_not_block_remote_clients():
    assert MissionLegalApiClient.validate_compatibility(
        {
            "api_version": API_VERSION,
            "app_version": APP_VERSION,
            "schema_version": SCHEMA_VERSION + 10,
        }
    ) is True


def test_server_can_require_a_newer_client_release():
    with pytest.raises(ApiCompatibilityError, match="or newer is required") as captured:
        MissionLegalApiClient.validate_compatibility(
            {
                "api_version": API_VERSION,
                "app_version": APP_VERSION,
                "minimum_client_version": "999.0.0",
            }
        )
    assert captured.value.client_update_required is True
    assert captured.value.required_client_version == "999.0.0"


def test_server_accepts_the_installed_client_release():
    assert MissionLegalApiClient.validate_compatibility(
        {
            "api_version": API_VERSION,
            "app_version": APP_VERSION,
            "minimum_client_version": APP_VERSION,
        }
    ) is True


def test_missing_api_metadata_is_rejected():
    with pytest.raises(ApiCompatibilityError, match="metadata is missing") as captured:
        MissionLegalApiClient.validate_compatibility({"schema_version": SCHEMA_VERSION})
    assert captured.value.client_update_required is False
    assert captured.value.reason == ApiCompatibilityError.INVALID_METADATA


def test_missing_application_version_metadata_is_rejected():
    with pytest.raises(
        ApiCompatibilityError,
        match="application-version metadata is missing",
    ) as captured:
        MissionLegalApiClient.validate_compatibility(
            {"api_version": API_VERSION, "schema_version": SCHEMA_VERSION}
        )

    assert captured.value.reason == ApiCompatibilityError.INVALID_METADATA


def test_invalid_application_version_metadata_is_rejected():
    with pytest.raises(
        ApiCompatibilityError,
        match="application-version metadata is invalid",
    ) as captured:
        MissionLegalApiClient.validate_compatibility(
            {
                "api_version": API_VERSION,
                "app_version": "not-a-version",
            }
        )

    assert captured.value.reason == ApiCompatibilityError.INVALID_METADATA


def test_newer_server_application_requires_matching_client():
    with pytest.raises(ApiCompatibilityError, match="999.0.0 is required") as captured:
        MissionLegalApiClient.validate_compatibility(
            {
                "api_version": API_VERSION,
                "app_version": "999.0.0",
            }
        )

    assert captured.value.reason == ApiCompatibilityError.CLIENT_UPDATE_REQUIRED
    assert captured.value.required_client_version == "999.0.0"


def test_newer_client_accepts_compatible_older_server(monkeypatch):
    monkeypatch.setattr("services.api_client.APP_VERSION", "0.2.2")

    assert MissionLegalApiClient.validate_compatibility(
        {
            "api_version": API_VERSION,
            "app_version": "0.2.1",
            "minimum_client_version": "0.2.1",
        }
    ) is True


def test_required_update_version_rejects_an_insufficient_feed_release():
    problem = required_update_version_problem("1.4.9", "1.5.0")

    assert "requires Mission Legal 1.5.0" in problem
    assert "latest update offered" in problem


def test_required_update_version_accepts_the_server_floor():
    assert required_update_version_problem("1.5.0", "1.5.0") == ""


def test_pre_pair_optional_update_uses_optional_wording_and_applies_only_on_accept(
    monkeypatch,
):
    from ui import update_coordinator

    class FakeService:
        enabled = True

        def __init__(self):
            self.apply_calls = 0

        def apply_prepared_update(self):
            self.apply_calls += 1

    class FakeMessageBox:
        Information = object()
        AcceptRole = object()
        RejectRole = object()
        accept_restart = False
        shown = []

        def __init__(self, _parent=None):
            self.restart_button = None

        @classmethod
        def information(cls, _parent, title, text):
            cls.shown.append((title, text))

        @classmethod
        def warning(cls, _parent, title, text):
            cls.shown.append((title, text))

        @classmethod
        def critical(cls, _parent, title, text):
            cls.shown.append((title, text))

        def setIcon(self, _icon):
            pass

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def setInformativeText(self, text):
            self.informative_text = text

        def setDetailedText(self, _text):
            pass

        def addButton(self, text, _role):
            button = object()
            if text == "Restart and update":
                self.restart_button = button
            return button

        def exec(self):
            self.__class__.shown.append(
                (self.title, f"{self.text} {self.informative_text}")
            )

        def clickedButton(self):
            if self.accept_restart:
                return self.restart_button
            return None

    service = FakeService()
    prepared = SimpleNamespace(
        version="0.2.0",
        notes_markdown="",
    )
    monkeypatch.setattr(update_coordinator, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(update_coordinator, "ClientUpdateService", lambda: service)
    monkeypatch.setattr(
        update_coordinator,
        "_download_update_blocking",
        lambda *_args: {"prepared": prepared, "error": ""},
    )

    assert update_coordinator.offer_optional_client_update() is False
    assert service.apply_calls == 0
    title, copy = FakeMessageBox.shown[-1]
    assert title == "Mission Legal Update Available"
    assert "is available" in copy
    assert "continue pairing" in copy.lower()
    assert "required" not in copy.lower()

    FakeMessageBox.accept_restart = True
    assert update_coordinator.offer_optional_client_update() is True
    assert service.apply_calls == 1
