import base64
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path


INSTALLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = INSTALLER_DIR.parents[1]
TEST_TEMP_ROOT = REPO_ROOT / "run_tmp" / "server-installer-unittest"


def _maintenance_module():
    path = INSTALLER_DIR / "server_maintenance.py"
    spec = importlib.util.spec_from_file_location("server_maintenance", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _create_database(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO app_metadata (key, value) VALUES ('schema_version', '7')"
        )
        connection.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO records (value) VALUES (?)", [("alpha",), ("beta",)]
        )
        connection.commit()


class ServerInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def test_maintenance_creates_integrity_checked_snapshot(self):
        maintenance = _maintenance_module()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            database = root / "app.db"
            _create_database(database)

            result = maintenance.create_pre_upgrade_backup(
                database,
                root / "Backups" / "Installer",
                "0.1.0",
                "0.2.0",
                root / "Logs" / "installer.log",
            )

            backup = Path(result["path"])
            metadata_path = Path(result["metadata_path"])
            self.assertEqual(result["status"], "backed-up")
            self.assertTrue(backup.is_file())
            self.assertTrue(metadata_path.is_file())
            maintenance.verify_database(backup)
            with closing(sqlite3.connect(backup)) as connection:
                rows = connection.execute(
                    "SELECT value FROM records ORDER BY id"
                ).fetchall()
            self.assertEqual(rows, [("alpha",), ("beta",)])
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["reason"], "installer-pre-upgrade")
            self.assertEqual(metadata["schema_version"], "7")
            self.assertEqual(metadata["app_version_from"], "0.1.0")
            self.assertEqual(metadata["app_version_to"], "0.2.0")
            self.assertEqual(
                metadata["backup_sha256"],
                hashlib.sha256(backup.read_bytes()).hexdigest(),
            )

    def test_maintenance_rejects_corrupt_database(self):
        maintenance = _maintenance_module()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            database = root / "app.db"
            database.write_bytes(b"not a sqlite database")

            with self.assertRaisesRegex(maintenance.MaintenanceError, "integrity"):
                maintenance.create_pre_upgrade_backup(
                    database, root / "Backups", "0.1.0", "0.2.0"
                )
            self.assertFalse(list((root / "Backups").glob("*.db")))

    def test_inno_definition_enforces_upgrade_safety_contract(self):
        script = (INSTALLER_DIR / "mission_legal_server.iss").read_text(
            encoding="utf-8"
        )
        setup = script.split("[Setup]", 1)[1].split("[Files]", 1)[0]
        install_delete = script.split("[InstallDelete]", 1)[1].split(
            "[Registry]", 1
        )[0]
        prepare = script.split(
            "function PrepareToInstall(var NeedsRestart: Boolean): String;", 1
        )[1].split("procedure CurStepChanged", 1)[0]
        initialize = script.split("function InitializeSetup: Boolean;", 1)[1].split(
            "function QuoteArgument", 1
        )[0]

        self.assertIn("AppId={{8A39739D-CBD2-4C38-AE5D-9DE7E69B29D5}", setup)
        self.assertIn(r"DefaultDirName={autopf}\Mission Legal\Server", setup)
        self.assertIn("PrivilegesRequired=admin", setup)
        self.assertIn("ArchitecturesInstallIn64BitMode=x64compatible", setup)
        self.assertIn("SetupLogging=yes", setup)
        self.assertIn("UninstallLogging=yes", setup)
        self.assertIn("CompareReleaseVersions", initialize)
        self.assertIn("Downgrades are blocked", initialize)
        self.assertIn("Same-version reinstalls are blocked", initialize)
        self.assertIn("AllowDevelopmentReinstall", initialize)
        self.assertIn("{param:ALLOWDEVREINSTALL|0}", script)
        self.assertIn("#ifdef DevelopmentBuild", script)
        self.assertIn(
            "RecordInitialServiceState := not PreflightStarted", prepare
        )
        stop_call = "ServiceScript, 'Stop', RecordInitialServiceState"
        self.assertIn(stop_call, prepare)
        self.assertLess(prepare.index(stop_call), prepare.index("RunBackupGate"))
        self.assertLess(
            prepare.index("RunBackupGate"), prepare.index("RunRollbackAction('Capture')")
        )
        self.assertIn("--backup-before-upgrade", script)
        self.assertLess(
            script.index("--backup-before-upgrade"),
            script.index("MaintenancePath :="),
        )
        self.assertIn("StartAndVerify", script)
        self.assertIn("ServerConfiguredBeforeInstall", script)
        self.assertIn("Service registration and startup are deferred", script)
        self.assertIn("RestorePriorInstallation", script)
        self.assertIn("RunRollbackAction('Restore')", script)
        self.assertIn("InstallerBinaries\\rollback-{#AppVersion}", script)
        restore = script.split("function RestorePriorInstallation: Boolean;", 1)[
            1
        ].split("function RemoveServiceWithoutHelper", 1)[0]
        restore_files = "RunRollbackAction('Restore')"
        restore_registration = "RunServiceAction(ServiceScript, 'InstallOrUpdate'"
        restore_start = "RunServiceAction(ServiceScript, 'StartOnly'"
        self.assertLess(restore.index(restore_files), restore.index(restore_registration))
        self.assertLess(
            restore.index(restore_registration), restore.index(restore_start)
        )
        self.assertIn("managed firewall rule could not be restored", restore)
        self.assertIn("CurUninstallStepChanged", script)
        self.assertIn("'Remove'", script)
        self.assertIn("RemoveServiceWithoutHelper", script)
        self.assertIn("sc.exe", script)
        fallback = script.split("function RemoveFirewallWithoutHelper: Boolean;", 1)[
            1
        ].split("function PrepareToInstall", 1)[0]
        self.assertIn("MissionLegalServerHTTPS", fallback)
        self.assertIn("Mission Legal Server HTTPS", fallback)
        self.assertIn("Remove-NetFirewallRule", fallback)
        self.assertNotIn("-Group", fallback)
        self.assertNotIn("*", fallback)
        self.assertIn("Result := RemoveFirewallWithoutHelper", fallback)
        self.assertNotIn("{commonappdata}", install_delete.lower())
        self.assertNotIn("[UninstallDelete]", script)

    def test_binary_rollback_helper_restores_exact_prior_tree(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is required for the rollback helper")
        helper = INSTALLER_DIR / "server_installer_rollback.ps1"
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            install = root / "Program Files" / "Mission Legal" / "Server"
            snapshot = root / "ProgramData" / "Rollback"
            (install / "_internal").mkdir(parents=True)
            (install / "MissionLegalServer.exe").write_bytes(b"old-server")
            (install / "_internal" / "runtime.dll").write_bytes(b"old-runtime")

            def run(action):
                subprocess.run(
                    [
                        powershell,
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(helper),
                        "-Action",
                        action,
                        "-InstallDir",
                        str(install),
                        "-SnapshotDir",
                        str(snapshot),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

            run("Capture")
            (install / "MissionLegalServer.exe").write_bytes(b"broken-new-server")
            (install / "_internal" / "runtime.dll").unlink()
            (install / "new-only.dll").write_bytes(b"new-only")
            run("Restore")

            self.assertEqual(
                (install / "MissionLegalServer.exe").read_bytes(), b"old-server"
            )
            self.assertEqual(
                (install / "_internal" / "runtime.dll").read_bytes(),
                b"old-runtime",
            )
            self.assertFalse((install / "new-only.dll").exists())
            run("Discard")
            self.assertFalse(snapshot.exists())

    def test_existing_good_snapshot_is_preserved_when_install_tree_is_damaged(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is required for the rollback helper")
        helper = INSTALLER_DIR / "server_installer_rollback.ps1"
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            install = root / "installed"
            snapshot = root / "rollback"
            install.mkdir()
            executable = install / "MissionLegalServer.exe"
            executable.write_bytes(b"known-good-server")

            command = [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
                "-InstallDir",
                str(install),
                "-SnapshotDir",
                str(snapshot),
            ]
            subprocess.run(command + ["-Action", "Capture"], check=True)
            saved_snapshot = {
                path.relative_to(snapshot): path.read_bytes()
                for path in snapshot.rglob("*")
                if path.is_file()
            }

            executable.write_bytes(b"damaged-candidate")
            (install / "candidate-only.dll").write_bytes(b"candidate")
            retry = subprocess.run(
                command + ["-Action", "Capture"],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(retry.returncode, 0)
            self.assertIn(
                "existing binary rollback snapshot was preserved",
                (retry.stdout + retry.stderr).lower(),
            )
            self.assertEqual(
                saved_snapshot,
                {
                    path.relative_to(snapshot): path.read_bytes()
                    for path in snapshot.rglob("*")
                    if path.is_file()
                },
            )

            subprocess.run(command + ["-Action", "Restore"], check=True)
            self.assertEqual(executable.read_bytes(), b"known-good-server")
            self.assertFalse((install / "candidate-only.dll").exists())
            subprocess.run(command + ["-Action", "Discard"], check=True)

    def test_service_helper_verifies_path_health_and_recovery(self):
        helper = (INSTALLER_DIR / "server_installer_actions.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'ValidateSet("Stop", "InstallOrUpdate", "StartAndVerify", "StartOnly", "Remove")',
            helper,
        )
        self.assertIn("Get-RegisteredServiceExecutable", helper)
        self.assertIn("Service executable mismatch", helper)
        self.assertIn("Get-HealthUri", helper)
        self.assertIn("Health endpoint reports version", helper)
        self.assertIn("sc.exe", helper)
        self.assertIn("restart/5000/restart/15000/restart/60000", helper)

    def test_build_reads_version_and_emits_silent_release_metadata(self):
        build = (REPO_ROOT / "deployment" / "build_server_installer.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("from version import APP_VERSION", build)
        self.assertIn('"/DAppVersion=$AppVersion"', build)
        self.assertIn("MissionLegalServerSetup-$AppVersion.exe", build)
        self.assertIn("/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG", build)
        self.assertIn("Get-FileHash", build)
        self.assertIn("Get-AuthenticodeSignature", build)
        self.assertIn("Authenticode signature is not valid", build)
        self.assertIn("AllowUnpublishedDevelopmentOverwrite", build)
        self.assertIn("Published or potentially published same-version artifacts are immutable", build)
        self.assertIn('"/DDevelopmentBuild=1"', build)
        self.assertIn("development_build", build)

    def test_release_orchestrator_builds_immutable_client_last(self):
        build = (REPO_ROOT / "deployment" / "build_release.ps1").read_text(
            encoding="utf-8"
        )
        server_call = (
            '& (Join-Path $PSScriptRoot "build_server_installer.ps1") '
            "@ServerArguments"
        )
        client_call = (
            '& (Join-Path $PSScriptRoot "build_client_release.ps1") '
            "@ClientArguments"
        )
        self.assertLess(build.index(server_call), build.index(client_call))
        self.assertLess(
            build.index("Server installer Authenticode signature is not valid"),
            build.index(client_call),
        )
        self.assertLess(
            build.index("Server installer manifest SHA-256 does not match"),
            build.index(client_call),
        )
        self.assertIn(
            "MISSION_LEGAL_VPK_SIGN_PARAMS cannot be combined",
            build,
        )
        self.assertIn("ReuseExistingServerRelease", build)
        self.assertIn("Reusing immutable server installer", build)
        self.assertIn("PreviousReleaseProvider", build)

    def test_vm_harness_is_explicitly_gated_and_never_automatic(self):
        harness_path = INSTALLER_DIR / "validate_server_installer_vm.ps1"
        marker_path = INSTALLER_DIR / "new_server_installer_vm_marker.ps1"
        harness = harness_path.read_text(encoding="utf-8")
        marker = marker_path.read_text(encoding="utf-8")

        self.assertIn('ParameterSetName = "Validate"', harness)
        self.assertIn('ParameterSetName = "Execute"', harness)
        self.assertIn("[switch]$ValidateOnly", harness)
        self.assertIn("[switch]$Execute", harness)
        validate_branch = harness.split("if ($ValidateOnly) {", 1)[1].split(
            "$ConsentEvidence = Assert-ExecutionConsent", 1
        )[0]
        self.assertIn('mutating_actions_performed = $false', validate_branch)
        self.assertNotIn("New-Item", validate_branch)
        self.assertNotIn("Invoke-InstallerExecutable", validate_branch)

        expected_consent = (
            "I CONFIRM THIS IS A DISPOSABLE MISSION LEGAL TEST VM"
        )
        for source in (harness, marker):
            self.assertIn(expected_consent, source)
            self.assertIn("Test-IsAdministrator", source)
            self.assertIn("Get-VirtualMachineIdentity", source)
            self.assertIn("machine_guid", source)
            self.assertIn("Is64BitOperatingSystem", source)
            self.assertIn("Is64BitProcess", source)
        self.assertIn("marker expired", harness)
        self.assertIn("product state is not pristine", harness)
        self.assertIn("-AllowUnsignedInstallers", harness)
        self.assertIn("Assert-SafeWorkRoot $ResolvedWorkRoot -RequireAbsent", harness)
        self.assertIn("Assert-NewScenarioPath", harness)
        self.assertIn("Assert-NoReparseAncestors", harness)

        marker_parameters = marker.split("$ErrorActionPreference", 1)[0]
        self.assertNotIn("$MarkerPath", marker_parameters)
        self.assertIn(
            "[Environment+SpecialFolder]::CommonApplicationData",
            marker,
        )
        self.assertNotIn("Join-Path $env:ProgramData", marker)
        self.assertIn('Join-Path $MarkerDirectory "vm-consent.json"', marker)
        self.assertIn("already exists", marker)
        self.assertIn("instead of overwriting or reusing consent state", marker)
        self.assertIn("SetAccessRuleProtection($true, $false)", marker)
        self.assertIn("AreAccessRulesProtected", marker)
        self.assertIn('SecurityIdentifier]::new("S-1-5-32-544")', marker)
        self.assertIn('SecurityIdentifier]::new("S-1-5-18")', marker)

        for script in (REPO_ROOT / "deployment").rglob("*.ps1"):
            if script == harness_path:
                continue
            self.assertNotIn(
                harness_path.name,
                script.read_text(encoding="utf-8"),
                f"{script} must never invoke the destructive VM harness",
            )

    def test_vm_harness_covers_server_release_safety_matrix(self):
        harness = (
            INSTALLER_DIR / "validate_server_installer_vm.ps1"
        ).read_text(encoding="utf-8")

        required_phases = (
            '"baseline-deferred-setup-and-seeded-fixture"',
            '"upgrade-artifact-pristine-migration-and-same-version-rejection"',
            '"fresh-baseline-from-same-fixture"',
            '"preflight-upgrade-failure-preserves-baseline"',
            '"post-copy-upgrade-failure-rolls-back-exact-baseline"',
            '"successful-upgrade"',
            '"downgrade-rejected-with-upgraded-state-unchanged"',
            '"uninstall-preserves-data"',
            '"reinstall-proves-preserved-data"',
            '"final-uninstall"',
        )
        for phase in required_phases:
            self.assertIn(phase, harness)

        self.assertIn("Assert-PrivateServerFirewallRule", harness)
        self.assertIn("Assert-NoServerFirewallRule", harness)
        self.assertIn("Get-PrivateNetworkEvidence", harness)
        self.assertIn('"--host", "0.0.0.0"', harness)
        self.assertIn('profile -notmatch \'Public|Domain|Any\'', harness)
        self.assertIn('StartName -cne "LocalSystem"', harness)
        self.assertIn("Test-LocalSystemMissionRootRelocation", harness)
        self.assertIn("content_was_created_by_harness", harness)
        self.assertIn("sentinel_content_unchanged", harness)
        self.assertIn("Wait-ServiceCreatedMirrorBackup", harness)
        self.assertIn('"--existing-database"', harness)
        self.assertIn("DatabaseFixtureSha256", harness)
        self.assertIn("Get-VerifiedUpgradeBackup", harness)
        self.assertIn('reason -ceq "installer-pre-upgrade"', harness)
        self.assertIn("app_version_from", harness)
        self.assertIn("backup_sha256", harness)
        self.assertIn("source_file_sha256", harness)
        self.assertIn("tls_ca_private_key", harness)
        self.assertIn("tls_server_private_key", harness)
        self.assertIn("original_device_credential_still_valid", harness)
        self.assertIn("firewall_rule_removed", harness)
        self.assertGreaterEqual(harness.count("Assert-DeferredFirstInstallState"), 4)
        self.assertGreaterEqual(harness.count("Wait-ServerHealthSurfaces"), 8)
        self.assertIn("Invoke-PostCopyUpgradeFailure", harness)
        self.assertIn("Get-InstallTreeInventory", harness)
        self.assertIn("Assert-InstallTreeMatches", harness)
        self.assertIn("authoritative_database", harness)
        self.assertIn("same_version_state_unchanged", harness)
        self.assertIn("UpgradeArtifact pristine migration changed", harness)
        self.assertIn("exact child of InstallDir", harness)

        candidate_phase = harness.index(
            'Invoke-ValidationPhase "upgrade-artifact-pristine-migration'
        )
        baseline_phase = harness.index(
            'Invoke-ValidationPhase "fresh-baseline-from-same-fixture"'
        )
        post_copy_phase = harness.index(
            'Invoke-ValidationPhase "post-copy-upgrade-failure'
        )
        successful_phase = harness.index(
            'Invoke-ValidationPhase "successful-upgrade"'
        )
        self.assertLess(candidate_phase, baseline_phase)
        self.assertLess(baseline_phase, post_copy_phase)
        self.assertLess(post_copy_phase, successful_phase)

    def test_vm_post_copy_watcher_is_tightly_scoped_and_nonautomatic(self):
        harness_path = INSTALLER_DIR / "validate_server_installer_vm.ps1"
        watcher_path = INSTALLER_DIR / "server_installer_failure_watcher.ps1"
        harness = harness_path.read_text(encoding="utf-8")
        watcher = watcher_path.read_text(encoding="utf-8")

        self.assertIn(watcher_path.name, harness)
        self.assertIn('"Mission Legal\\Server"', watcher)
        self.assertIn('"MissionLegalService.exe"', watcher)
        self.assertIn("baseline_sha256", watcher)
        self.assertIn("upgrade_installer_path", watcher)
        self.assertIn("upgrade_installer_sha256", watcher)
        self.assertIn("installer_pid", watcher)
        self.assertIn("Win32_Process", watcher)
        self.assertIn("ExclusiveHash -ceq $BaselineSha256", watcher)
        self.assertIn("[IO.FileShare]::None", watcher)
        self.assertIn("$Stream.SetLength(0)", watcher)
        self.assertNotIn("SetLength", "\n".join(
            line for line in watcher.splitlines()
            if "UpgradeInstaller" in line
        ))

        for script in (REPO_ROOT / "deployment").rglob("*.ps1"):
            if script == harness_path:
                continue
            self.assertNotIn(
                watcher_path.name,
                script.read_text(encoding="utf-8"),
                f"{script} must never invoke the destructive watcher",
            )

    @unittest.skipUnless(
        sys.platform == "win32" and shutil.which("powershell.exe"),
        "ValidateOnly contract uses Windows PE metadata and Windows PowerShell",
    )
    def test_vm_validate_only_is_nonmutating_and_rejects_unsafe_work_roots(self):
        powershell = shutil.which("powershell.exe")
        harness = INSTALLER_DIR / "validate_server_installer_vm.ps1"

        def run_encoded(script):
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            return subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    encoded,
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        def build_fixture(path, version, type_name):
            source = f'''using System;
using System.Reflection;
[assembly: AssemblyVersion("{version}.0")]
[assembly: AssemblyFileVersion("{version}.0")]
[assembly: AssemblyInformationalVersion("{version}")]
public static class {type_name} {{ public static void Main() {{ }} }}
'''
            escaped_source = source.replace("'", "''")
            escaped_path = str(path).replace("'", "''")
            result = run_encoded(
                f"$source = '{escaped_source}'; "
                f"Add-Type -TypeDefinition $source -Language CSharp "
                f"-OutputAssembly '{escaped_path}' -OutputType ConsoleApplication"
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            baseline = root / "baseline-0.1.0.exe"
            upgrade = root / "upgrade-0.1.1.exe"
            build_fixture(baseline, "0.1.0", "BaselineFixture")
            build_fixture(upgrade, "0.1.1", "UpgradeFixture")

            volume = Path(REPO_ROOT.anchor)
            safe_work_root = volume / (
                "MissionLegalInstallerValidation-UT" + uuid.uuid4().hex[:10]
            )
            self.assertFalse(safe_work_root.exists())
            common = [
                "&",
                f"'{str(harness).replace(chr(39), chr(39) * 2)}'",
                "-BaselineInstaller",
                f"'{str(baseline).replace(chr(39), chr(39) * 2)}'",
                "-BaselineVersion",
                "0.1.0",
                "-UpgradeInstaller",
                f"'{str(upgrade).replace(chr(39), chr(39) * 2)}'",
                "-UpgradeVersion",
                "0.1.1",
                "-ValidateOnly",
            ]

            valid_script = " ".join(
                common
                + [
                    "-WorkRoot",
                    f"'{str(safe_work_root).replace(chr(39), chr(39) * 2)}'",
                ]
            )
            valid = run_encoded(valid_script)
            self.assertEqual(valid.returncode, 0, valid.stderr or valid.stdout)
            json_start = valid.stdout.find("{")
            self.assertGreaterEqual(json_start, 0, valid.stdout)
            plan = json.loads(valid.stdout[json_start:])
            self.assertEqual(plan["mode"], "validate-only")
            self.assertFalse(plan["mutating_actions_performed"])
            self.assertFalse(plan["work_root_exists"])
            self.assertFalse(safe_work_root.exists())

            unsafe_roots = [
                root / ("MissionLegalInstallerValidation-nested" + uuid.uuid4().hex[:6]),
                Path(os.environ["ProgramData"])
                / ("MissionLegalInstallerValidation-programdata" + uuid.uuid4().hex[:6]),
            ]
            for unsafe_root in unsafe_roots:
                self.assertFalse(unsafe_root.exists())
                unsafe_script = " ".join(
                    common
                    + [
                        "-WorkRoot",
                        f"'{str(unsafe_root).replace(chr(39), chr(39) * 2)}'",
                    ]
                )
                rejected = run_encoded(unsafe_script)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(
                    "top-level directory",
                    rejected.stderr + rejected.stdout,
                )
                self.assertFalse(unsafe_root.exists())

    def test_vm_validation_runbook_describes_destructive_boundary(self):
        runbook = (
            INSTALLER_DIR / "SERVER_INSTALLER_VM_VALIDATION.md"
        ).read_text(encoding="utf-8")
        normalized = " ".join(runbook.split())
        self.assertIn("Never run", runbook)
        self.assertIn("-ValidateOnly", runbook)
        self.assertIn("creates no directory", normalized)
        self.assertIn("machine-GUID-bound", runbook)
        self.assertIn("Private", runbook)
        self.assertIn("LocalSystem", runbook)
        self.assertIn("empty-database-before-migration", runbook)
        self.assertIn("Deferred first install", runbook)
        self.assertIn("Candidate pristine migration", runbook)
        self.assertIn("Real post-copy rollback", runbook)
        self.assertIn("Same-version rejection", runbook)
        self.assertIn("selected Private-profile IPv4", runbook)
        self.assertIn("does not claim that LocalSystem modified", runbook)
        self.assertIn("revert", runbook)


if __name__ == "__main__":
    unittest.main()
