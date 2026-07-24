import os
from pathlib import Path
from unittest import mock

import pytest

import server_setup
import windows_service
from database.runtime import get_database_path


SERVICE_OVERRIDE_NAMES = (
    "MISSION_LEGAL_DATA_DIR",
    "MISSION_LEGAL_DATABASE_PATH",
    "MISSION_LEGAL_TLS_CERT",
    "MISSION_LEGAL_TLS_KEY",
    "MISSION_LEGAL_SERVER_HOST",
    "MISSION_LEGAL_SERVER_PORT",
)
TEST_ROOT = Path(__file__).resolve().parents[2] / "run_tmp" / "server-runtime-env"


def test_frozen_service_ignores_inherited_development_overrides():
    program_data = TEST_ROOT / "frozen" / "ProgramData"
    environment = {
        "PROGRAMDATA": str(program_data),
        "MISSION_LEGAL_DATA_DIR": str(TEST_ROOT / "frozen" / "wrong-data"),
        "MISSION_LEGAL_DATABASE_PATH": str(TEST_ROOT / "frozen" / "wrong.db"),
        "MISSION_LEGAL_TLS_CERT": str(TEST_ROOT / "frozen" / "wrong-cert.pem"),
        "MISSION_LEGAL_TLS_KEY": str(TEST_ROOT / "frozen" / "wrong-key.pem"),
        "MISSION_LEGAL_SERVER_HOST": "203.0.113.15",
        "MISSION_LEGAL_SERVER_PORT": "65535",
    }

    configured = windows_service._configure_service_runtime_environment(
        frozen=True,
        environment=environment,
    )

    expected = program_data.resolve() / "MissionLegal"
    assert configured == expected
    assert environment["MISSION_LEGAL_DATA_DIR"] == str(expected)
    assert environment["MISSION_LEGAL_SERVER_PROCESS"] == "1"
    for name in SERVICE_OVERRIDE_NAMES[1:]:
        assert name not in environment


def test_source_service_preserves_explicit_development_overrides():
    environment = {
        "PROGRAMDATA": str(TEST_ROOT / "source" / "ProgramData"),
        "MISSION_LEGAL_DATA_DIR": str(TEST_ROOT / "source" / "development-data"),
        "MISSION_LEGAL_DATABASE_PATH": str(TEST_ROOT / "source" / "development.db"),
        "MISSION_LEGAL_TLS_CERT": str(
            TEST_ROOT / "source" / "development-cert.pem"
        ),
        "MISSION_LEGAL_TLS_KEY": str(TEST_ROOT / "source" / "development-key.pem"),
        "MISSION_LEGAL_SERVER_HOST": "127.0.0.2",
        "MISSION_LEGAL_SERVER_PORT": "18765",
    }
    before = dict(environment)

    configured = windows_service._configure_service_runtime_environment(
        frozen=False,
        environment=environment,
    )

    assert configured == Path(before["MISSION_LEGAL_DATA_DIR"]).resolve()
    assert environment["MISSION_LEGAL_SERVER_PROCESS"] == "1"
    for name in SERVICE_OVERRIDE_NAMES:
        assert environment[name] == before[name]


def test_frozen_service_fails_closed_without_programdata():
    environment = {
        "MISSION_LEGAL_DATA_DIR": str(TEST_ROOT / "missing" / "wrong-data"),
        "MISSION_LEGAL_DATABASE_PATH": str(TEST_ROOT / "missing" / "wrong.db"),
    }

    with pytest.raises(RuntimeError, match="cannot locate Windows ProgramData"):
        windows_service._configure_service_runtime_environment(
            frozen=True,
            environment=environment,
        )


def test_service_package_smoke_entrypoint_bypasses_scm_dispatch():
    with mock.patch(
        "utils.package_smoke.run_server_package_smoke_test",
        return_value=23,
    ) as smoke, mock.patch.object(
        windows_service,
        "_require_pywin32",
    ) as require_pywin32:
        result = windows_service.main(["--package-smoke-test"])

    assert result == 23
    smoke.assert_called_once_with()
    require_pywin32.assert_not_called()


def test_explicit_setup_data_dir_overrides_inherited_database_path():
    data_dir = TEST_ROOT / "setup" / "ProgramData" / "MissionLegal"
    inherited_database = TEST_ROOT / "setup" / "development" / "do-not-touch.db"
    environment = {
        "MISSION_LEGAL_DATA_DIR": str(TEST_ROOT / "setup" / "wrong-data"),
        "MISSION_LEGAL_DATABASE_PATH": str(inherited_database),
    }

    configured = server_setup._configure_server_data_environment(
        data_dir,
        environment=environment,
    )

    assert configured == data_dir.resolve()
    assert environment["MISSION_LEGAL_DATA_DIR"] == str(data_dir.resolve())
    assert "MISSION_LEGAL_DATABASE_PATH" not in environment

    with mock.patch.dict(os.environ, environment, clear=True):
        assert get_database_path() == data_dir.resolve() / "app.db"
