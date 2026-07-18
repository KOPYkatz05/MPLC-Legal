from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = REPO_ROOT / "deployment"


def _read(name: str) -> str:
    return (DEPLOYMENT / name).read_text(encoding="utf-8-sig")


def test_release_builders_enforce_transaction_and_signing_contracts():
    client = _read("build_client_release.ps1")
    server = _read("build_server_installer.ps1")
    release = _read("build_release.ps1")
    safety = _read("release_safety.ps1")

    for source in (client, server):
        assert "New-MissionLegalReleaseTransaction" in source
        assert "Complete-MissionLegalReleaseTransaction" in source
        assert "Repair-MissionLegalInterruptedReleaseTransaction" in source
        assert "ExpectedSignerThumbprint" in source
        assert "RequireTimestamp:$RequireSigning" in source
        assert "Assert-MissionLegalVersionIsNewer" in source

    assert "StagedServerPackageDir" in server
    assert 'server_installed_executable' in server
    assert 'server_embedded_maintenance_executable' in server
    assert "package_provenance" in server

    for executable in (
        "MissionLegal.exe",
        "MissionLegalUpdateWorker.exe",
        "MissionLegalClientSetup.exe",
        "MissionLegalDiagnostics.exe",
        "MissionLegal_ExecutionStub.exe",
    ):
        assert executable in safety

    assert "release-metadata" in release
    assert "metadata_snapshots" in release
    assert "raw_package_provenance" in release
    assert "Immutable release metadata already exists" in release
    assert "InitialRelease" in client
    assert "Get-PublishedHttpFeedAssets" in client
    assert "cloned/downloaded published client history" in client
    assert "RequireSha256" in client
    assert "missing a valid SHA-256 digest" in client
    assert "duplicate case-insensitive archive path" in safety


def test_runtime_state_is_forbidden_from_both_raw_packages():
    for name in ("build_client_release.ps1", "build_server_installer.ps1"):
        source = _read(name)
        for runtime_name in (
            "api-device.json",
            "devices.json",
            "pairing.json",
            "pairing-transaction.json",
            "server.json",
            "workspaces.json",
        ):
            assert runtime_name in source


def test_published_feed_verifier_is_https_read_only_and_summary_bound():
    verifier = _read("verify_published_client_feed.ps1")
    assert "AllowAutoRedirect = $false" in verifier
    assert "ResponseHeadersRead" in verifier
    assert "ReleaseSummaryPath" in verifier
    assert "Assert-DownloadedArtifact" in verifier
    assert "Assert-MissionLegalClientPackageSignatures" in verifier
    assert "remote_mutations_performed = $false" in verifier
    for mutation in ("Invoke-RestMethod", "PostAsync", "PutAsync", "DeleteAsync"):
        assert mutation not in verifier


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="PowerShell required")
def test_release_safety_semver_recovery_and_archive_guards(tmp_path: Path):
    safety = DEPLOYMENT / "release_safety.ps1"
    root = tmp_path / "release"
    final = root / "stable"
    rollback = root / "stable.rollback-fixture"
    stale = root / ".stable.test.transaction-0123456789abcdef0123456789abcdef"
    rollback.mkdir(parents=True)
    stale.mkdir()
    (rollback / "old.txt").write_text("old", encoding="utf-8")

    quoted_safety = str(safety).replace("'", "''")
    quoted_final = str(final).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
. '{quoted_safety}'
if ((Compare-MissionLegalSemVer '1.0.0' '1.0.0-rc.10') -ne 1) {{ throw 'SemVer release ordering failed.' }}
if ((Compare-MissionLegalSemVer '1.0.0-rc.2' '1.0.0-rc.10') -ne -1) {{ throw 'SemVer numeric ordering failed.' }}
try {{ Assert-MissionLegalVersionIsNewer '1.0.0' @('1.0.0') 'fixture'; throw 'monotonic check accepted equality' }} catch {{ if ($_.Exception.Message -notmatch 'not newer') {{ throw }} }}
if (Test-MissionLegalSafeArchiveEntry 'lib/app/file.exe:stream') {{ throw 'ADS path accepted.' }}
if (Test-MissionLegalSafeArchiveEntry 'lib/../file.exe') {{ throw 'Traversal path accepted.' }}
if (Test-MissionLegalSafeWindowsLeafName 'Setup.exe:stream') {{ throw 'ADS leaf accepted.' }}
if (Test-MissionLegalSafeWindowsLeafName 'CON.txt') {{ throw 'Reserved leaf accepted.' }}
if (Test-MissionLegalSafeWindowsLeafName 'Setup.exe.') {{ throw 'Trailing-dot leaf accepted.' }}
Repair-MissionLegalInterruptedReleaseTransaction '{quoted_final}'
if (-not (Test-Path -LiteralPath (Join-Path '{quoted_final}' 'old.txt'))) {{ throw 'Rollback was not recovered.' }}
if (Test-Path -LiteralPath '{str(stale).replace("'", "''")}') {{ throw 'Stale transaction was not removed.' }}
try {{ Get-NormalizedCertificateThumbprint ('A' * 64); throw 'SHA-256 thumbprint accepted.' }} catch {{ if ($_.Exception.Message -notmatch '40-character') {{ throw }} }}
try {{ Get-NormalizedCertificateThumbprint (('A' * 40) + '!'); throw 'Malformed thumbprint accepted.' }} catch {{ if ($_.Exception.Message -notmatch 'hexadecimal digits') {{ throw }} }}
try {{ ConvertTo-MissionLegalSemVer '1.0.0-01'; throw 'Leading-zero prerelease accepted.' }} catch {{ if ($_.Exception.Message -notmatch 'leading zeroes') {{ throw }} }}
"""
    result = subprocess.run(
        [
            shutil.which("powershell.exe"),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
