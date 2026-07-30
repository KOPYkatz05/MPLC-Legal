import json
from pathlib import Path

from services.api_client import MissionLegalApiClient
from services.dynamics_roster_service import DynamicsRosterService


class DynamicsRosterClientService:
    def __init__(self, api_client=None):
        self.api_client = api_client or MissionLegalApiClient.from_environment()

    def preview(self, file_path):
        if self.api_client is not None:
            return self.api_client.upload("/v1/dynamics-roster/preview", file_path=file_path, data={})
        return DynamicsRosterService().preview(Path(file_path).read_bytes(), str(file_path))

    def apply(self, file_path, preview_id, resolutions=None):
        data = {
            "preview_id": preview_id,
            "resolutions": json.dumps(resolutions or {}),
        }
        if self.api_client is not None:
            return self.api_client.upload(
                "/v1/dynamics-roster/apply", file_path=file_path, data=data
            )
        return DynamicsRosterService().apply(
            Path(file_path).read_bytes(),
            str(file_path),
            preview_id,
            resolutions or {},
            applying_device="local",
        )

    def last_import(self):
        if self.api_client is not None:
            return self.api_client.get("/v1/dynamics-roster/last").get("item")
        return DynamicsRosterService().last_import()
