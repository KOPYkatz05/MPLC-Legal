from PySide6.QtCore import QSettings

from app_identity import APP, ORG
from services.api_client import connection_configuration_diagnostics


def test_diagnostics_identify_environment_configuration(monkeypatch, tmp_path):
    secret = "super-secret-credential"
    monkeypatch.setenv("MISSION_LEGAL_API_URL", "https://server.test:8443")
    monkeypatch.setenv("MISSION_LEGAL_API_CERT", str(tmp_path / "missing.pem"))
    monkeypatch.setenv("MISSION_LEGAL_CLIENT_DATA_DIR", str(tmp_path))

    diagnostics = connection_configuration_diagnostics()

    assert diagnostics["source"] == "environment"
    assert diagnostics["host"] == "server.test"
    assert diagnostics["port"] == 8443
    assert diagnostics["certificate_configured"] is True
    assert diagnostics["certificate_exists"] is False
    assert secret not in repr(diagnostics)


def test_diagnostics_identify_qsettings_configuration(monkeypatch, tmp_path, qapp):
    monkeypatch.delenv("MISSION_LEGAL_API_URL", raising=False)
    monkeypatch.delenv("MISSION_LEGAL_API_CERT", raising=False)
    monkeypatch.setenv("MISSION_LEGAL_CLIENT_DATA_DIR", str(tmp_path))
    settings = QSettings(ORG, APP)
    settings.setValue("server/url", "https://saved.test:9443")
    settings.setValue("server/ca_certificate", str(tmp_path / "saved.pem"))
    settings.sync()

    try:
        diagnostics = connection_configuration_diagnostics()
    finally:
        settings.remove("server/url")
        settings.remove("server/ca_certificate")
        settings.sync()

    assert diagnostics["source"] == "qsettings"
    assert diagnostics["host"] == "saved.test"
    assert diagnostics["port"] == 9443
    assert diagnostics["certificate_exists"] is False
