from services.api_client import ApiCompatibilityError
from PySide6.QtWidgets import QDialog
from ui.dialogs.server_wait_dialog import ServerWaitDialog


class FakeApiClient:
    def __init__(
        self,
        *,
        incompatible_stage=None,
        compatibility_reason=ApiCompatibilityError.CLIENT_UPDATE_REQUIRED,
    ):
        self.incompatible_stage = incompatible_stage
        self.compatibility_reason = compatibility_reason
        self.calls = []
        self.health_payload = {"response": "health"}
        self.session_payload = {"response": "session"}

    def health(self):
        self.calls.append("health")
        return self.health_payload

    def session(self):
        self.calls.append("session")
        return self.session_payload

    def validate_compatibility(self, payload):
        stage = payload["response"]
        self.calls.append(f"validate:{stage}")
        if stage == self.incompatible_stage:
            raise ApiCompatibilityError(
                f"A required update was reported by {stage}.",
                reason=self.compatibility_reason,
                required_client_version="2.0.0",
            )
        return True


def test_server_wait_retry_validates_health_and_session_before_accepting(qapp):
    _ = qapp
    api_client = FakeApiClient()
    dialog = ServerWaitDialog(api_client)
    try:
        dialog.retry()

        assert api_client.calls == [
            "health",
            "validate:health",
            "session",
            "validate:session",
        ]
        assert dialog._allow_close is True
        assert dialog.result() == QDialog.Accepted
        assert dialog.timer.isActive() is False
    finally:
        dialog.close()
        dialog.deleteLater()


def test_server_wait_exposes_required_update_from_health(qapp):
    _ = qapp
    api_client = FakeApiClient(incompatible_stage="health")
    dialog = ServerWaitDialog(api_client)
    try:
        dialog.timer.start()
        dialog.retry()

        assert api_client.calls == ["health", "validate:health"]
        assert dialog.windowTitle() == "Mission Legal Update Required"
        assert dialog.update_button.isHidden() is False
        assert "required update" in dialog.detail_label.text().lower()
        assert dialog.timer.isActive() is False
        assert dialog._allow_close is False
    finally:
        dialog._allow_close = True
        dialog.close()
        dialog.deleteLater()


def test_server_wait_exposes_required_update_from_session(qapp):
    _ = qapp
    api_client = FakeApiClient(incompatible_stage="session")
    dialog = ServerWaitDialog(api_client)
    try:
        dialog.timer.start()
        dialog.retry()

        assert api_client.calls == [
            "health",
            "validate:health",
            "session",
            "validate:session",
        ]
        assert dialog.windowTitle() == "Mission Legal Update Required"
        assert dialog.update_button.isHidden() is False
        assert "required update" in dialog.detail_label.text().lower()
        assert dialog.timer.isActive() is False
        assert dialog._allow_close is False
    finally:
        dialog._allow_close = True
        dialog.close()
        dialog.deleteLater()


def test_server_wait_does_not_offer_client_update_for_old_server(qapp):
    _ = qapp
    api_client = FakeApiClient(
        incompatible_stage="health",
        compatibility_reason=ApiCompatibilityError.SERVER_UPDATE_REQUIRED,
    )
    dialog = ServerWaitDialog(api_client)
    try:
        dialog.timer.start()
        dialog.retry()

        assert dialog.windowTitle() == "Mission Legal Server Update Required"
        assert dialog.update_button.isHidden() is True
        assert "repair Mission Legal Server" in dialog.detail_label.text()
        assert dialog.timer.isActive() is True
    finally:
        dialog.timer.stop()
        dialog._allow_close = True
        dialog.close()
        dialog.deleteLater()
