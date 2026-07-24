import base64
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


INSTALLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = INSTALLER_DIR.parents[1]
TEST_TEMP_ROOT = REPO_ROOT / "run_tmp" / "server-installer-unittest"


@contextmanager
def _writable_test_directory():
    """Avoid Python 3.12's restrictive Windows TemporaryDirectory ACL."""

    path = TEST_TEMP_ROOT / f"rollback-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


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
        with _writable_test_directory() as root:
            database = root / "app.db"
            _create_database(database)

            result = maintenance.create_pre_upgrade_backup(
                database,
                root / "Backups" / "Installer",
                "0.1.0",
                "0.2.0",
                root / "Backups" / "Installer" / "attempt.json",
                root / "Logs" / "installer.log",
            )

            backup = Path(result["path"])
            metadata_path = Path(result["metadata_path"])
            receipt_path = root / "Backups" / "Installer" / "attempt.json"
            self.assertEqual(result["status"], "backed-up")
            self.assertTrue(backup.is_file())
            self.assertTrue(metadata_path.is_file())
            self.assertTrue(receipt_path.is_file())
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
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["format"], 1)
            self.assertEqual(receipt["status"], "backed-up")
            self.assertEqual(receipt["attempt_id"], metadata["attempt_id"])
            self.assertEqual(receipt["backup_path"], str(backup))
            self.assertEqual(
                receipt["metadata_sha256"],
                hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
            )

    def test_maintenance_rejects_corrupt_database(self):
        maintenance = _maintenance_module()
        with _writable_test_directory() as root:
            database = root / "app.db"
            database.write_bytes(b"not a sqlite database")

            with self.assertRaisesRegex(maintenance.MaintenanceError, "integrity"):
                maintenance.create_pre_upgrade_backup(
                    database,
                    root / "Backups",
                    "0.1.0",
                    "0.2.0",
                    root / "Backups" / "attempt.json",
                )
            self.assertFalse(list((root / "Backups").glob("*.db")))

    def test_maintenance_restores_exact_receipted_snapshot_and_clears_sidecars(self):
        maintenance = _maintenance_module()
        with _writable_test_directory() as root:
            database = root / "Data" / "app.db"
            database.parent.mkdir()
            _create_database(database)
            backup_dir = root / "Backups" / "Installer"
            receipt_path = backup_dir / "attempt-restore.json"
            result = maintenance.create_pre_upgrade_backup(
                database,
                backup_dir,
                "0.1.0",
                "0.2.0",
                receipt_path,
            )
            backup = Path(result["path"])
            expected_bytes = backup.read_bytes()

            with closing(sqlite3.connect(database)) as connection:
                connection.execute("INSERT INTO records (value) VALUES ('candidate')")
                connection.execute(
                    "UPDATE app_metadata SET value = '999' WHERE key = 'schema_version'"
                )
                connection.commit()
            for suffix in maintenance.SQLITE_SIDECAR_SUFFIXES:
                Path(f"{database}{suffix}").write_bytes(b"stale candidate sidecar")

            restored = maintenance.restore_pre_upgrade_backup(
                database,
                backup_dir,
                receipt_path,
                "0.1.0",
                "0.2.0",
            )

            self.assertEqual(restored["status"], "restored")
            self.assertEqual(database.read_bytes(), expected_bytes)
            self.assertTrue(backup.is_file(), "rollback must preserve the verified backup")
            self.assertTrue(Path(result["metadata_path"]).is_file())
            for suffix in maintenance.SQLITE_SIDECAR_SUFFIXES:
                self.assertFalse(Path(f"{database}{suffix}").exists())
            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute(
                    "SELECT value FROM records ORDER BY id"
                ).fetchall()
                schema = connection.execute(
                    "SELECT value FROM app_metadata WHERE key = 'schema_version'"
                ).fetchone()[0]
            self.assertEqual(rows, [("alpha",), ("beta",)])
            self.assertEqual(schema, "7")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["restore_status"], "restored")
            self.assertEqual(
                receipt["restored_database_sha256"],
                hashlib.sha256(expected_bytes).hexdigest(),
            )
            self.assertTrue(receipt["sqlite_sidecars_cleared"])
            self.assertIn("restored_at", receipt)

    def test_maintenance_rejects_tampered_backup_before_touching_live_database(self):
        maintenance = _maintenance_module()
        with _writable_test_directory() as root:
            database = root / "app.db"
            _create_database(database)
            backup_dir = root / "Backups"
            receipt_path = backup_dir / "attempt.json"
            result = maintenance.create_pre_upgrade_backup(
                database,
                backup_dir,
                "0.1.0",
                "0.2.0",
                receipt_path,
            )
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("INSERT INTO records (value) VALUES ('candidate')")
                connection.commit()
            candidate_hash = hashlib.sha256(database.read_bytes()).hexdigest()
            Path(result["path"]).write_bytes(b"tampered backup")

            with self.assertRaisesRegex(
                maintenance.MaintenanceError, "receipt SHA-256"
            ):
                maintenance.restore_pre_upgrade_backup(
                    database,
                    backup_dir,
                    receipt_path,
                    "0.1.0",
                    "0.2.0",
                )

            self.assertEqual(
                hashlib.sha256(database.read_bytes()).hexdigest(), candidate_hash
            )
            with closing(sqlite3.connect(database)) as connection:
                values = connection.execute(
                    "SELECT value FROM records ORDER BY id"
                ).fetchall()
            self.assertEqual(values[-1], ("candidate",))

    def test_maintenance_no_database_receipt_removes_candidate_database_and_sidecars(self):
        maintenance = _maintenance_module()
        with _writable_test_directory() as root:
            database = root / "Data" / "app.db"
            backup_dir = root / "Backups"
            receipt_path = backup_dir / "no-database-attempt.json"
            result = maintenance.create_pre_upgrade_backup(
                database,
                backup_dir,
                "unknown",
                "0.2.0",
                receipt_path,
            )
            self.assertEqual(result["status"], "no-database")
            database.parent.mkdir(parents=True)
            _create_database(database)
            for suffix in maintenance.SQLITE_SIDECAR_SUFFIXES:
                Path(f"{database}{suffix}").write_bytes(b"candidate sidecar")

            restored = maintenance.restore_pre_upgrade_backup(
                database,
                backup_dir,
                receipt_path,
                "unknown",
                "0.2.0",
            )

            self.assertEqual(restored["status"], "restored-no-database")
            self.assertFalse(database.exists())
            for suffix in maintenance.SQLITE_SIDECAR_SUFFIXES:
                self.assertFalse(Path(f"{database}{suffix}").exists())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["restore_status"], "restored-no-database")
            self.assertTrue(receipt["restored_database_absent"])
            self.assertTrue(receipt["sqlite_sidecars_cleared"])

    def test_maintenance_receipt_is_bound_to_versions_and_cannot_be_reused(self):
        maintenance = _maintenance_module()
        with _writable_test_directory() as root:
            database = root / "app.db"
            _create_database(database)
            backup_dir = root / "Backups"
            receipt_path = backup_dir / "attempt.json"
            maintenance.create_pre_upgrade_backup(
                database,
                backup_dir,
                "0.1.0",
                "0.2.0",
                receipt_path,
            )

            with self.assertRaisesRegex(
                maintenance.MaintenanceError, "app_version_to"
            ):
                maintenance.restore_pre_upgrade_backup(
                    database,
                    backup_dir,
                    receipt_path,
                    "0.1.0",
                    "0.3.0",
                )
            with self.assertRaisesRegex(
                maintenance.MaintenanceError, "receipt already exists"
            ):
                maintenance.create_pre_upgrade_backup(
                    database,
                    backup_dir,
                    "0.1.0",
                    "0.2.0",
                    receipt_path,
                )
            with self.assertRaisesRegex(
                maintenance.MaintenanceError, "direct child"
            ):
                maintenance.create_pre_upgrade_backup(
                    database,
                    backup_dir,
                    "0.1.0",
                    "0.2.0",
                    root / "outside-receipt.json",
                )

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
        self.assertIn("ExecAndLogOutput", script)
        self.assertIn("CompareReleaseVersions", initialize)
        self.assertIn("Downgrades are blocked", initialize)
        self.assertIn("Same-version reinstalls are blocked", initialize)
        self.assertIn("AllowDevelopmentReinstall", initialize)
        self.assertIn("{param:ALLOWDEVREINSTALL|0}", script)
        self.assertIn("#ifdef DevelopmentBuild", script)
        self.assertIn("HasServerRegistrationFootprint", initialize)
        self.assertIn("HasServerServiceRegistration", initialize)
        self.assertIn("service exists without a registered", initialize)
        self.assertIn("version is missing", initialize)
        self.assertIn("NeedsPriorBinarySnapshot :=", prepare)
        self.assertIn("InstalledPayloadIsRecognizable", prepare)
        self.assertIn("RunRollbackAction('PrepareFresh')", prepare)
        self.assertIn(
            "RecordInitialServiceState := not PreflightStarted", prepare
        )
        stop_call = "ServiceScript, 'Stop', RecordInitialServiceState"
        self.assertIn(stop_call, prepare)
        self.assertLess(
            prepare.index("RunRollbackAction('PrepareFresh')"),
            prepare.index(stop_call),
        )
        self.assertLess(prepare.index(stop_call), prepare.index("RunBackupGate"))
        self.assertLess(
            prepare.index("RunBackupGate"), prepare.index("RunRollbackAction('Capture')")
        )
        self.assertNotIn("--backup-before-upgrade", script)
        self.assertIn("MaintenancePath :=", script)
        self.assertIn("pre-upgrade-backup", script)
        self.assertIn("restore-pre-upgrade-backup", script)
        self.assertIn("--receipt", script)
        self.assertIn("installer-attempt-", script)
        self.assertIn(r"Backups\Installer", script)
        self.assertIn("StartAndVerify", script)
        self.assertIn("ServerConfiguredBeforeInstall", script)
        self.assertIn("Silent installation left service registration", script)
        self.assertIn("RestorePriorInstallation", script)
        self.assertIn("RunRollbackAction('Restore')", script)
        self.assertIn("InstallerBinaries\\rollback-{#AppVersion}", script)
        restore = script.split("function RestorePriorInstallation: Boolean;", 1)[
            1
        ].split("function RemoveServiceWithoutHelper", 1)[0]
        restore_stop = "RunServiceAction(ServiceScript, 'Stop', False)"
        restore_database = "RunDatabaseRollback"
        restore_database_complete = (
            "Verified authoritative database rollback completed before binary"
        )
        restore_files = "RunRollbackAction('Restore')"
        restore_registration = "RunServiceAction(ServiceScript, 'InstallOrUpdate'"
        restore_start = "RunServiceAction(ServiceScript, 'StartOnly'"
        self.assertLess(restore.index(restore_stop), restore.index(restore_database))
        self.assertLess(
            restore.index(restore_database), restore.index(restore_database_complete)
        )
        self.assertLess(
            restore.index(restore_database_complete), restore.index(restore_files)
        )
        self.assertLess(restore.index(restore_files), restore.index(restore_registration))
        self.assertLess(
            restore.index(restore_registration), restore.index(restore_start)
        )
        self.assertIn("managed firewall rule could not be restored", restore)
        self.assertIn("prior service will remain stopped", restore)
        self.assertIn("RollbackFailedClosed := True", restore)
        self.assertLess(
            restore.index("if RollbackFailedClosed then"),
            restore.index("RunDatabaseRollback"),
        )
        self.assertNotIn(
            "BinaryRollbackRestored or (not BinarySnapshotCaptured)", restore
        )
        self.assertIn("PostCopyDatabaseMutationPossible", restore)
        self.assertIn(
            "if BinarySnapshotCaptured and (not RunRollbackAction('Restore'))",
            restore,
        )
        deinitialize = script.split("procedure DeinitializeSetup;", 1)[1].split(
            "procedure CurUninstallStepChanged", 1
        )[0]
        self.assertIn("not RollbackFailedClosed", deinitialize)
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

    def test_inno_first_install_wizard_and_automatic_configuration_contract(self):
        script = (INSTALLER_DIR / "mission_legal_server.iss").read_text(
            encoding="utf-8"
        )
        wizard = script.split("procedure InitializeWizard;", 1)[1].split(
            "procedure RestorePriorVersionRegistry", 1
        )[0]
        post_install = script.split(
            "procedure CurStepChanged(CurStep: TSetupStep);", 1
        )[1].split("procedure DeinitializeSetup", 1)[0]

        self.assertIn("CreateInputOptionPage", wizard)
        self.assertIn("Create a fresh server", wizard)
        self.assertIn("Migrate a verified database snapshot", wizard)
        self.assertIn("CreateInputDirPage", wizard)
        self.assertIn("Mission documents folder", wizard)
        self.assertIn("OneDrive database backup folder", wizard)
        self.assertIn("CreateInputFilePage", wizard)
        self.assertIn("function ShouldSkipPage", wizard)
        self.assertIn("SetupModePage.SelectedValueIndex <> 1", wizard)
        self.assertIn("function NextButtonClick", wizard)
        self.assertIn("WizardSilent", wizard)
        self.assertIn("DirExists(StoragePage.Values[0])", wizard)
        self.assertIn("FileExists(MigrationDatabasePage.Values[0])", wizard)
        self.assertIn("function RunInitialServerConfiguration", wizard)
        self.assertIn(r"{app}\MissionLegalServerSetup.exe", wizard)
        self.assertIn("--mission-storage-root", wizard)
        self.assertIn("--onedrive-backup-dir", wizard)
        self.assertIn("--existing-database", wizard)
        self.assertIn("--skip-main-client", wizard)
        self.assertNotIn("--replace-existing-database", wizard)
        self.assertIn("if WizardSetupRequired then", post_install)
        self.assertLess(
            post_install.index("PostCopyDatabaseMutationPossible := True"),
            post_install.index("RunInitialServerConfiguration"),
        )
        self.assertIn("not HasServerServiceRegistration", post_install)
        self.assertLess(
            post_install.index("RunInitialServerConfiguration"),
            post_install.index("ServiceScript, 'StartAndVerify'"),
        )
        self.assertIn("RestorePriorInstallation", post_install)
        self.assertIn("RaiseException", post_install)
        self.assertIn(
            "(not WizardSetupRequired) and (not ServerConfiguredBeforeInstall)",
            post_install,
        )

    def test_binary_rollback_helper_restores_exact_prior_tree(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is required for the rollback helper")
        helper = INSTALLER_DIR / "server_installer_rollback.ps1"
        with _writable_test_directory() as root:
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
        with _writable_test_directory() as root:
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

    def test_binary_rollback_helper_serializes_empty_inventory_as_an_array(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is required for the rollback helper")
        helper = INSTALLER_DIR / "server_installer_rollback.ps1"
        with _writable_test_directory() as root:
            install = root / "missing-install"
            snapshot = root / "rollback"
            log_file = root / "Logs" / "installer-rollback.log"
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
                "-LogFile",
                str(log_file),
            ]

            subprocess.run(command + ["-Action", "Capture"], check=True)

            metadata = json.loads(
                (snapshot / "snapshot.json").read_text(encoding="utf-8-sig")
            )
            self.assertFalse(metadata["had_installation"])
            self.assertEqual(metadata["files"], [])
            self.assertIn(
                "action=Capture succeeded",
                log_file.read_text(encoding="utf-8-sig"),
            )

            subprocess.run(command + ["-Action", "PrepareFresh"], check=True)
            self.assertFalse(snapshot.exists())
            self.assertIn(
                "action=PrepareFresh succeeded",
                log_file.read_text(encoding="utf-8-sig"),
            )

    def test_prepare_fresh_repairs_only_the_legacy_empty_snapshot(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is required for the rollback helper")
        helper = INSTALLER_DIR / "server_installer_rollback.ps1"
        with _writable_test_directory() as root:
            install = root / "empty-install"
            snapshot = root / "rollback"
            files = snapshot / "files"
            install.mkdir()
            files.mkdir(parents=True)
            (snapshot / "snapshot.json").write_text(
                json.dumps(
                    {
                        "format": 1,
                        "install_dir": str(install),
                        "had_installation": False,
                        "captured_at": "2026-07-18T00:00:00Z",
                        "files": {},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
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
                "-LogFile",
                str(root / "rollback.log"),
                "-Action",
                "PrepareFresh",
            ]

            subprocess.run(command, check=True, capture_output=True, text=True)

            self.assertFalse(snapshot.exists())

    def test_prepare_fresh_rejects_ambiguous_empty_metadata(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is required for the rollback helper")
        helper = INSTALLER_DIR / "server_installer_rollback.ps1"
        cases = {
            "missing-had-installation": {
                "files": {},
            },
            "null-had-installation": {
                "had_installation": None,
                "files": {},
            },
            "string-had-installation": {
                "had_installation": "false",
                "files": {},
            },
            "null-files": {
                "had_installation": False,
                "files": None,
            },
        }
        with _writable_test_directory() as root:
            for name, fields in cases.items():
                with self.subTest(name=name):
                    install = root / name / "empty-install"
                    snapshot = root / name / "rollback"
                    (snapshot / "files").mkdir(parents=True)
                    install.mkdir()
                    payload = {
                        "format": 1,
                        "install_dir": str(install),
                        "captured_at": "2026-07-18T00:00:00Z",
                        **fields,
                    }
                    metadata_path = snapshot / "snapshot.json"
                    metadata_path.write_text(
                        json.dumps(payload, indent=2),
                        encoding="utf-8",
                    )
                    before = metadata_path.read_bytes()

                    retry = subprocess.run(
                        [
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
                            "-Action",
                            "PrepareFresh",
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    self.assertNotEqual(retry.returncode, 0)
                    self.assertTrue(snapshot.is_dir())
                    self.assertEqual(metadata_path.read_bytes(), before)

    def test_prepare_fresh_preserves_real_or_ambiguous_state(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is required for the rollback helper")
        helper = INSTALLER_DIR / "server_installer_rollback.ps1"
        with _writable_test_directory() as root:
            install = root / "unregistered-install"
            snapshot = root / "rollback"
            files = snapshot / "files"
            install.mkdir()
            files.mkdir(parents=True)
            (install / "unexpected.exe").write_bytes(b"do-not-overwrite")
            metadata_path = snapshot / "snapshot.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "format": 1,
                        "install_dir": str(install),
                        "had_installation": False,
                        "captured_at": "2026-07-18T00:00:00Z",
                        "files": {},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            before = metadata_path.read_bytes()
            log_file = root / "rollback.log"
            retry = subprocess.run(
                [
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
                    "-LogFile",
                    str(log_file),
                    "-Action",
                    "PrepareFresh",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(retry.returncode, 0)
            self.assertTrue(snapshot.is_dir())
            self.assertEqual(metadata_path.read_bytes(), before)
            self.assertEqual(
                (install / "unexpected.exe").read_bytes(), b"do-not-overwrite"
            )
            self.assertIn(
                "unregistered application tree",
                log_file.read_text(encoding="utf-8-sig").lower(),
            )

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

    def test_server_programdata_acl_is_sid_based_fail_closed_and_vm_proven(self):
        data_acl = (REPO_ROOT / "server" / "data_acl.py").read_text(
            encoding="utf-8"
        )
        tls = (REPO_ROOT / "server" / "tls.py").read_text(encoding="utf-8")
        setup = (REPO_ROOT / "server_setup.py").read_text(encoding="utf-8")
        helper = (INSTALLER_DIR / "server_installer_actions.ps1").read_text(
            encoding="utf-8"
        )
        harness = (INSTALLER_DIR / "validate_server_installer_vm.ps1").read_text(
            encoding="utf-8"
        )

        for sid in ("S-1-5-18", "S-1-5-32-544", "S-1-5-32-545"):
            self.assertIn(sid, data_acl)
            self.assertIn(sid, helper)
            self.assertIn(sid, harness)
        for source in (data_acl, helper):
            self.assertIn("SetAccessRuleProtection($true, $false)", source)
            self.assertIn("AreAccessRulesProtected", source)
            self.assertNotIn("Administrators:F", source)
            self.assertNotIn("SYSTEM:F", source)
            self.assertNotIn("USERNAME", source)

        self.assertIn("if completed.returncode != 0", data_acl)
        self.assertIn("ServerDataAclError", data_acl)
        self.assertIn("protect_private_key_files(*paths)", tls)
        self.assertIn("protect_sensitive_server_data(app_data_dir)", setup)
        self.assertIn(
            'settings.setValue("server/ca_certificate", str(published_ca))',
            setup,
        )
        self.assertIn('Path("Public") / "mission-legal-ca.pem"', data_acl)
        self.assertIn("Protect-MissionLegalServerData", helper)
        self.assertIn("Publish-MissionLegalPublicCa", helper)
        initialization = helper.split("switch ($Action)", 1)[0]
        self.assertLess(
            initialization.index("Protect-MissionLegalServerData"),
            initialization.index("Beginning installer service action"),
        )

        self.assertIn("Invoke-StandardUserServerDataProbe", harness)
        self.assertIn("New-LocalUser", harness)
        self.assertIn("Remove-LocalUser -SID", harness)
        self.assertIn("LoadUserProfile = $false", harness)
        self.assertIn("sensitive_read_denied = $true", harness)
        self.assertIn("public_ca_read_allowed = $true", harness)
        self.assertIn("public_ca_write_denied = $true", harness)
        self.assertGreaterEqual(harness.count("Assert-ServerDataAclPolicy"), 7)
        for protected_name in (
            "app.db",
            "devices.json",
            "mission-legal-ca-key.pem",
            "mission-legal-server-key.pem",
            'Public\\mission-legal-ca.pem',
        ):
            self.assertIn(protected_name, harness)

    def test_package_provenance_accepts_exact_tree_and_rejects_tamper_and_relabel(self):
        helper = REPO_ROOT / "deployment" / "package_provenance.py"
        with _writable_test_directory() as root:
            package = root / "MissionLegalServer"
            package.mkdir()
            artifact = package / "server-runtime.bin"
            original_bytes = b"verified frozen server fixture"
            artifact.write_bytes(original_bytes)
            smoke = root / "smoke.jsonl"
            smoke.write_text(
                json.dumps(
                    {
                        "api_version": "1",
                        "app_version": "1.2.3",
                        "frozen": True,
                        "imports": [],
                        "role": "server",
                        "schema_version": 1,
                        "status": "ok",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = root / "MissionLegalServer.provenance.json"
            common = [
                "--repo-root",
                str(REPO_ROOT),
                "--package-dir",
                str(package),
                "--manifest-path",
                str(manifest),
            ]
            create_command = [
                sys.executable,
                "-B",
                str(helper),
                "create",
                *common,
                "--role",
                "server",
                "--app-version",
                "1.2.3",
                "--api-version",
                "1",
                "--schema-version",
                "1",
                "--smoke-result",
                str(smoke),
                "--dependency-lock",
                str(REPO_ROOT / "requirements_lock.txt"),
                "--dependency-lock",
                str(REPO_ROOT / "requirements_build.txt"),
            ]
            create = subprocess.run(
                create_command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(create.returncode, 0, create.stdout + create.stderr)
            record = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(record["role"], "server")
            self.assertEqual(record["application"]["app_version"], "1.2.3")
            self.assertEqual(record["files"][0]["path"], artifact.name)
            self.assertEqual(record["file_count"], 1)
            self.assertEqual(len(record["tree_sha256"]), 64)
            self.assertIn("git_commit", record["source"])
            self.assertEqual(
                [item["path"] for item in record["dependency_locks"]],
                ["requirements_build.txt", "requirements_lock.txt"],
            )
            deterministic_bytes = manifest.read_bytes()
            recreate = subprocess.run(
                create_command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                recreate.returncode, 0, recreate.stdout + recreate.stderr
            )
            self.assertEqual(manifest.read_bytes(), deterministic_bytes)

            def verify(version):
                return subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(helper),
                        "verify",
                        *common,
                        "--expected-role",
                        "server",
                        "--expected-app-version",
                        version,
                        "--expected-api-version",
                        "1",
                        "--expected-schema-version",
                        "1",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

            exact = verify("1.2.3")
            self.assertEqual(exact.returncode, 0, exact.stdout + exact.stderr)

            artifact.write_bytes(original_bytes + b"-tampered")
            tampered = verify("1.2.3")
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("tree does not match", tampered.stderr.lower())

            artifact.write_bytes(original_bytes)
            stale = verify("1.2.4")
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("application version mismatch", stale.stderr.lower())

    def test_build_reads_version_and_emits_silent_release_metadata(self):
        build = (REPO_ROOT / "deployment" / "build_server_installer.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "from version import API_VERSION, APP_VERSION, SCHEMA_VERSION", build
        )
        self.assertIn('"/DAppVersion=$AppVersion"', build)
        self.assertIn("MissionLegalServerSetup-$AppVersion.exe", build)
        self.assertIn("/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG", build)
        self.assertIn("Get-FileHash", build)
        self.assertIn("Get-AuthenticodeSignature", build)
        self.assertIn("Authenticode signature is not valid", build)
        self.assertIn("AllowUnpublishedDevelopmentOverwrite", build)
        self.assertIn("RequireSigning", build)
        self.assertIn(
            "RequireSigning cannot be combined with AllowUnpublishedDevelopmentOverwrite",
            build,
        )
        self.assertIn("Published or potentially published same-version artifacts are immutable", build)
        self.assertIn('"/DDevelopmentBuild=1"', build)
        self.assertIn("development_build", build)
        self.assertIn("production_signing_required", build)
        self.assertIn("package_provenance.py", build)
        self.assertIn("--expected-role server", build)
        self.assertIn("--required-windows-version-exe MissionLegalServer.exe", build)
        self.assertIn('"$PackageName.provenance.json"', build)
        self.assertIn("clean Git commit", build)
        for forbidden_name in (
            "devices.json",
            "server.json",
            ".pfx",
            ".p12",
            "PRIVATE KEY",
            "db|sqlite|sqlite3",
        ):
            self.assertIn(forbidden_name, build)

    def test_raw_build_emits_role_provenance_after_smoke_validation(self):
        build = (REPO_ROOT / "deployment" / "build_windows.ps1").read_text(
            encoding="utf-8"
        )
        client_release = (
            REPO_ROOT / "deployment" / "build_client_release.ps1"
        ).read_text(encoding="utf-8")
        helper = (REPO_ROOT / "deployment" / "package_provenance.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("New-PackageProvenance", build)
        self.assertIn("MissionLegalClient.provenance.json", build)
        self.assertIn("MissionLegalServer.provenance.json", build)
        self.assertLess(
            build.index("$ClientSmoke.ExitCode"),
            build.index('$ClientManifest = Join-Path $DistRoot'),
        )
        self.assertLess(
            build.index("$ServerSmoke.ExitCode"),
            build.index('$ServerManifest = Join-Path $DistRoot'),
        )
        for executable in (
            "MissionLegal.exe",
            "MissionLegalDiagnostics.exe",
            "MissionLegalClientSetup.exe",
            "MissionLegalUpdateWorker.exe",
            "MissionLegalServer.exe",
            "MissionLegalServerSetup.exe",
            "MissionLegalService.exe",
        ):
            self.assertIn(f'"{executable}"', build)
        for required_field in (
            '"dependency_locks"',
            '"files"',
            '"ocr_models"',
            '"smoke_result"',
            '"source"',
            '"tree_sha256"',
            '"windows_executables"',
        ):
            self.assertIn(required_field, helper)
        self.assertIn('"--expected-role", "client"', client_release)
        self.assertIn(
            '"--required-windows-version-exe", "MissionLegal.exe"',
            client_release,
        )
        self.assertIn("Assert-ClientRawPackageProvenance", client_release)
        self.assertIn("clean Git commit", client_release)
        self.assertGreaterEqual(
            client_release.count("Assert-ClientRawPackageProvenance"), 3
        )

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
        self.assertIn(
            "RequireSigning cannot be combined with AllowUnpublishedDevelopmentOverwrite",
            build,
        )
        self.assertIn("RequireSigning = [bool]$RequireSigning", build)
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
        self.assertIn("Get-VerifiedRollbackReceipt", harness)
        self.assertIn("restored_before_prior_service_start", harness)
        self.assertIn("restored_database_sha256", harness)
        self.assertIn("-ExcludeDatabaseHash", harness)
        self.assertIn("database_schema_version_restored", harness)
        self.assertIn("pre_upgrade_rows_restored", harness)
        self.assertIn('Join-Path $ExpectedDataRoot "Backups\\Installer"', harness)
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
        self.assertIn("database_sha256", watcher)
        self.assertIn("database_before_sha256", watcher)
        self.assertIn("database_mutated_sha256", watcher)
        self.assertIn("MISSION-LEGAL-INSTALLER-CANDIDATE-MUTATION", watcher)
        self.assertIn("$DatabaseStream.Flush($true)", watcher)
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

        with _writable_test_directory() as root:
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
        self.assertIn("Deferred silent first install", runbook)
        self.assertIn("Candidate pristine migration", runbook)
        self.assertIn("Real post-copy rollback", runbook)
        self.assertIn("Same-version rejection", runbook)
        self.assertIn("selected Private-profile IPv4", runbook)
        self.assertIn("does not claim that LocalSystem modified", runbook)
        self.assertIn("ProgramData ACLs", runbook)
        self.assertIn("temporary non-administrator local account", runbook)
        self.assertIn("published public CA can be read but not written", runbook)
        self.assertIn("revert", runbook)


if __name__ == "__main__":
    unittest.main()
