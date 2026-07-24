from unittest.mock import patch

import windows_service


def test_service_disables_uvicorn_color_detection():
    captured = {}

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, config):
            self.should_exit = False

        def run(self):
            return None

    service = object.__new__(windows_service.MissionLegalWindowsService)
    service.server = None

    with (
        patch("windows_service._configure_service_runtime_environment"),
        patch("server.tls.generate_local_tls", return_value={
            "server_cert": "server.crt",
            "server_key": "server.key",
        }),
        patch("server.configuration.load_server_configuration", return_value={}),
        patch("uvicorn.Config", FakeConfig),
        patch("uvicorn.Server", FakeServer),
        patch("servicemanager.LogInfoMsg"),
        patch("servicemanager.LogErrorMsg"),
    ):
        service.SvcDoRun()

    assert captured["use_colors"] is False
