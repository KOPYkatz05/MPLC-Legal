import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server_setup
from services.database_backup_service import DatabaseBackupError, DatabaseBackupService


TEST_TEMP_ROOT = REPO_ROOT / "run_tmp" / "server-setup-connectivity"


def _create_database(path, values=()):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO app_metadata (key, value) VALUES ('schema_version', '1')"
        )
        connection.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO records (value) VALUES (?)",
            [(value,) for value in values],
        )
        connection.commit()


def _values(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            "SELECT value FROM records ORDER BY id"
        ).fetchall()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ServerSetupConnectivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def test_explicit_database_replaces_only_empty_fresh_destination(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "source.db"
            destination = root / "ProgramData" / "app.db"
            destination.parent.mkdir(parents=True)
            _create_database(source, ["missionary-record"])
            _create_database(destination)
            source_hash = _sha256(source)

            with mock.patch.object(server_setup, "_assert_server_service_stopped") as stopped:
                result = server_setup._handle_existing_database(
                    source,
                    destination,
                    explicitly_supplied=True,
                    allow_populated_replacement=False,
                    database_backup_service=DatabaseBackupService,
                    backup_dir=destination.parent / "Backups",
                )

            stopped.assert_called_once_with()
            self.assertEqual(result, "replaced")
            self.assertEqual(_values(destination), [("missionary-record",)])
            self.assertEqual(_sha256(source), source_hash)
            backups = list((destination.parent / "Backups").glob("*.db"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(_values(backups[0]), [])
            self.assertFalse(list(destination.parent.glob(".*.incoming-*")))
            self.assertFalse(list(destination.parent.glob(".*.rollback-*")))

    def test_changed_source_removes_new_authoritative_destination(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "source.db"
            destination = root / "ProgramData" / "app.db"
            _create_database(source, ["preserve me"])

            with mock.patch.object(
                server_setup,
                "_database_sha256",
                side_effect=("before-transfer", "after-transfer"),
            ):
                with self.assertRaisesRegex(
                    server_setup.ServerSetupError,
                    "changed while it was being transferred",
                ):
                    server_setup._replace_database_safely(
                        source,
                        destination,
                        database_backup_service=DatabaseBackupService,
                        backup_dir=root / "Backups",
                    )

            self.assertTrue(source.is_file())
            DatabaseBackupService.verify(source)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}-wal").exists())
            self.assertFalse(Path(f"{destination}-shm").exists())
            self.assertFalse(list(destination.parent.glob(".*_transfer_*.tmp")))

    def test_failed_final_verification_removes_new_destination(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "source.db"
            destination = root / "ProgramData" / "app.db"
            _create_database(source, ["preserve me"])

            class FinalVerificationFailureService:
                @staticmethod
                def verify(path):
                    if Path(path).resolve() == destination.resolve():
                        raise DatabaseBackupError(
                            "injected final verification failure"
                        )
                    return DatabaseBackupService.verify(path)

                @staticmethod
                def transfer_database(source_path, destination_path):
                    return DatabaseBackupService.transfer_database(
                        source_path,
                        destination_path,
                    )

            with self.assertRaisesRegex(
                DatabaseBackupError,
                "injected final verification failure",
            ):
                server_setup._replace_database_safely(
                    source,
                    destination,
                    database_backup_service=FinalVerificationFailureService,
                    backup_dir=root / "Backups",
                )

            self.assertTrue(source.is_file())
            DatabaseBackupService.verify(source)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}-wal").exists())
            self.assertFalse(Path(f"{destination}-shm").exists())
            self.assertFalse(list(destination.parent.glob(".*_transfer_*.tmp")))

    def test_populated_destination_is_refused_without_explicit_authority(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "source.db"
            destination = root / "ProgramData" / "app.db"
            destination.parent.mkdir(parents=True)
            _create_database(source, ["incoming"])
            _create_database(destination, ["authoritative"])
            source_hash = _sha256(source)
            destination_hash = _sha256(destination)

            with mock.patch.object(server_setup, "_assert_server_service_stopped") as stopped:
                with self.assertRaisesRegex(
                    server_setup.ServerSetupError,
                    "--replace-existing-database",
                ):
                    server_setup._handle_existing_database(
                        source,
                        destination,
                        explicitly_supplied=True,
                        allow_populated_replacement=False,
                        database_backup_service=DatabaseBackupService,
                        backup_dir=destination.parent / "Backups",
                    )

            stopped.assert_called_once_with()
            self.assertEqual(_sha256(source), source_hash)
            self.assertEqual(_sha256(destination), destination_hash)
            self.assertEqual(_values(destination), [("authoritative",)])
            self.assertFalse((destination.parent / "Backups").exists())

    def test_authorized_replacement_preserves_verified_previous_database(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "source.db"
            destination = root / "ProgramData" / "app.db"
            destination.parent.mkdir(parents=True)
            _create_database(source, ["incoming"])
            _create_database(destination, ["authoritative"])

            with mock.patch.object(server_setup, "_assert_server_service_stopped"):
                result = server_setup._handle_existing_database(
                    source,
                    destination,
                    explicitly_supplied=True,
                    allow_populated_replacement=True,
                    database_backup_service=DatabaseBackupService,
                    backup_dir=destination.parent / "Backups",
                )

            self.assertEqual(result, "replaced")
            self.assertEqual(_values(destination), [("incoming",)])
            backups = list((destination.parent / "Backups").glob("*.db"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(_values(backups[0]), [("authoritative",)])
            DatabaseBackupService.verify(backups[0])

    def test_same_explicit_database_is_verified_and_reported(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            database = Path(temporary) / "app.db"
            _create_database(database, ["authoritative"])

            with mock.patch.object(server_setup, "_assert_server_service_stopped"):
                result = server_setup._handle_existing_database(
                    database,
                    database,
                    explicitly_supplied=True,
                    allow_populated_replacement=False,
                    database_backup_service=DatabaseBackupService,
                    backup_dir=database.parent / "Backups",
                )

            self.assertEqual(result, "already-authoritative")
            self.assertEqual(_values(database), [("authoritative",)])

    def test_matching_snapshot_at_different_path_is_retry_safe(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "selected-snapshot.db"
            destination = root / "ProgramData" / "app.db"
            destination.parent.mkdir(parents=True)
            _create_database(source, ["already-migrated"])
            shutil.copy2(source, destination)
            original_hash = _sha256(destination)

            with mock.patch.object(server_setup, "_assert_server_service_stopped"):
                result = server_setup._handle_existing_database(
                    source,
                    destination,
                    explicitly_supplied=True,
                    allow_populated_replacement=False,
                    database_backup_service=DatabaseBackupService,
                    backup_dir=destination.parent / "Backups",
                )

            self.assertEqual(result, "already-authoritative")
            self.assertEqual(_sha256(destination), original_hash)
            self.assertFalse((destination.parent / "Backups").exists())

    def test_missing_explicit_database_fails_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(
                server_setup.ServerSetupError,
                "explicitly supplied database does not exist",
            ):
                server_setup._handle_existing_database(
                    root / "missing.db",
                    root / "destination.db",
                    explicitly_supplied=True,
                    allow_populated_replacement=False,
                    database_backup_service=DatabaseBackupService,
                    backup_dir=root / "Backups",
                )

    def test_implicit_legacy_source_never_replaces_existing_destination(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            source = root / "legacy-default.db"
            destination = root / "app.db"
            _create_database(source, ["legacy"])
            _create_database(destination, ["authoritative"])

            result = server_setup._handle_existing_database(
                source,
                destination,
                explicitly_supplied=False,
                allow_populated_replacement=False,
                database_backup_service=DatabaseBackupService,
                backup_dir=root / "Backups",
            )

            self.assertEqual(result, "destination-preserved")
            self.assertEqual(_values(destination), [("authoritative",)])
            self.assertEqual(_values(source), [("legacy",)])
            self.assertFalse((root / "Backups").exists())

    @unittest.skipUnless(os.name == "nt", "Windows installed-service detection")
    def test_only_frozen_installed_folder_activates_service_finish(self):
        install_dir = TEST_TEMP_ROOT / "Mission Legal" / "Server"
        executable = install_dir / "MissionLegalServerSetup.exe"
        helper = (
            install_dir
            / "InstallerSupport"
            / "server_installer_actions.ps1"
        ).resolve()
        with mock.patch.object(Path, "is_file", return_value=True):
            self.assertIsNone(
                server_setup._installed_service_helper(
                    frozen=False,
                    executable=executable,
                    installed_root=install_dir,
                )
            )
            self.assertEqual(
                server_setup._installed_service_helper(
                    frozen=True,
                    executable=executable,
                    installed_root=install_dir,
                ),
                helper,
            )
        with mock.patch.object(Path, "is_file", return_value=False):
            self.assertIsNone(
                server_setup._installed_service_helper(
                    frozen=True,
                    executable=executable,
                    installed_root=install_dir,
                )
            )
        raw_executable = TEST_TEMP_ROOT / "raw" / "MissionLegalServerSetup.exe"
        with mock.patch.object(Path, "is_file", return_value=True):
            self.assertIsNone(
                server_setup._installed_service_helper(
                    frozen=True,
                    executable=raw_executable,
                    installed_root=install_dir,
                )
            )

    def test_installed_service_action_uses_unjoined_process_arguments(self):
        install_dir = TEST_TEMP_ROOT / "Mission Legal" / "Server"
        helper = install_dir / "InstallerSupport" / "server_installer_actions.ps1"
        data_dir = TEST_TEMP_ROOT / "Program Data" / "MissionLegal"
        completed = mock.Mock(returncode=0, stderr="", stdout="verified")

        with mock.patch.object(
            server_setup.subprocess,
            "run",
            return_value=completed,
        ) as run:
            output = server_setup._run_installed_service_action(
                helper,
                "InstallOrUpdate",
                data_dir=data_dir,
                app_version="9.8.7",
            )

        self.assertEqual(output, "verified")
        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[command.index("-File") + 1], str(helper.resolve()))
        self.assertEqual(command[command.index("-Action") + 1], "InstallOrUpdate")
        self.assertEqual(command[command.index("-InstallDir") + 1], str(install_dir.resolve()))
        self.assertEqual(command[command.index("-DataDir") + 1], str(data_dir.resolve()))
        self.assertEqual(command[command.index("-AppVersion") + 1], "9.8.7")
        self.assertEqual(run.call_args.kwargs["cwd"], str(install_dir.resolve()))
        self.assertFalse(run.call_args.kwargs["check"])

    def test_installed_service_finish_registers_then_starts_and_verifies(self):
        helper = TEST_TEMP_ROOT / "Server" / "InstallerSupport" / "server_installer_actions.ps1"
        with mock.patch.object(
            server_setup,
            "_run_installed_service_action",
        ) as action:
            result = server_setup._finish_installed_service_setup(
                TEST_TEMP_ROOT / "ProgramData",
                helper=helper,
                app_version="4.5.6",
            )

        self.assertTrue(result)
        self.assertEqual(
            [call.args[1] for call in action.call_args_list],
            ["InstallOrUpdate", "StartAndVerify"],
        )
        for call in action.call_args_list:
            self.assertEqual(call.kwargs["app_version"], "4.5.6")
            self.assertEqual(call.kwargs["data_dir"], TEST_TEMP_ROOT / "ProgramData")

    def test_installed_service_action_nonzero_exit_is_a_setup_failure(self):
        completed = mock.Mock(
            returncode=17,
            stderr="service registration rejected",
            stdout="",
        )
        helper = (
            TEST_TEMP_ROOT
            / "Server"
            / "InstallerSupport"
            / "server_installer_actions.ps1"
        )
        with mock.patch.object(
            server_setup.subprocess,
            "run",
            return_value=completed,
        ):
            with self.assertRaisesRegex(
                server_setup.ServerSetupError,
                "InstallOrUpdate failed: service registration rejected",
            ):
                server_setup._run_installed_service_action(
                    helper,
                    "InstallOrUpdate",
                    data_dir=TEST_TEMP_ROOT / "ProgramData",
                )

    def test_raw_folder_service_finish_is_explicitly_manual(self):
        with mock.patch.object(
            server_setup,
            "_installed_service_helper",
            return_value=None,
        ), mock.patch.object(
            server_setup,
            "_run_installed_service_action",
        ) as action:
            result = server_setup._finish_installed_service_setup(
                TEST_TEMP_ROOT / "ProgramData"
            )

        self.assertFalse(result)
        action.assert_not_called()

    def test_failed_installed_health_check_stops_service(self):
        helper = TEST_TEMP_ROOT / "Server" / "InstallerSupport" / "server_installer_actions.ps1"
        actions = []

        def run_action(_helper, action, **_kwargs):
            actions.append(action)
            if action == "StartAndVerify":
                raise server_setup.ServerSetupError("health failed")

        with mock.patch.object(
            server_setup,
            "_run_installed_service_action",
            side_effect=run_action,
        ):
            with self.assertRaisesRegex(server_setup.ServerSetupError, "health failed"):
                server_setup._finish_installed_service_setup(
                    TEST_TEMP_ROOT / "ProgramData",
                    helper=helper,
                )

        self.assertEqual(actions, ["InstallOrUpdate", "StartAndVerify", "Stop"])

    def test_windows_host_access_contract_is_checked_and_local_subnet_only(self):
        setup_source = Path(server_setup.__file__).read_text(encoding="utf-8")
        action_source = (
            Path(__file__).resolve().parent / "server_installer_actions.ps1"
        ).read_text(encoding="utf-8")

        for source in (setup_source, action_source):
            self.assertIn("MissionLegalServerHTTPS", source)
            self.assertIn("Mission Legal Server HTTPS", source)
            self.assertIn("MissionLegalServerDiscovery", source)
            self.assertIn("Mission Legal Server Discovery", source)
            self.assertIn("Profile Any", source)
            self.assertIn("RemoteAddress LocalSubnet", source)
            self.assertIn("Protocol TCP", source)
            self.assertIn("Protocol UDP", source)
            self.assertIn("43876", source)
            self.assertIn("LocalPort", source)
            self.assertIn("Get-NetFirewallPortFilter", source)
            self.assertIn("Get-NetFirewallAddressFilter", source)
            self.assertIn("*S-1-5-18:(OI)(CI)M", source)
            self.assertIn("LocalSystem Modify access", source)
            self.assertIn("FileSystemRights", source)

        self.assertIn("$LASTEXITCODE -ne 0", action_source)
        self.assertIn("Remove-MissionLegalFirewallRule", action_source)
        install_action = action_source.split('"InstallOrUpdate" {', 1)[1].split(
            '"StartAndVerify" {', 1
        )[0]
        self.assertIn("Grant-ConfiguredStorageAccess", install_action)
        self.assertIn("Set-MissionLegalFirewallRule", install_action)
        remove_action = action_source.split('"Remove" {', 1)[1].split("}", 1)[0]
        self.assertIn("Remove-MissionLegalFirewallRule", remove_action)
        setup_main = setup_source.split("def main():", 1)[1]
        self.assertIn(
            "installed_service_started = _finish_installed_service_setup(",
            setup_main,
        )

    def test_checked_powershell_failure_is_not_ignored(self):
        completed = mock.Mock(returncode=1, stderr="access denied", stdout="")
        with mock.patch.object(server_setup.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(
                server_setup.ServerSetupError,
                "ACL verification failed: access denied",
            ):
                server_setup._run_windows_powershell(
                    "Write-Output test",
                    description="ACL verification",
                )

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser check")
    def test_embedded_windows_scripts_parse_without_execution(self):
        calls = (
            (server_setup._assert_windows_host_prerequisites, ()),
            (server_setup._assert_server_service_stopped, ()),
            (server_setup._ensure_system_modify_access, (TEST_TEMP_ROOT,)),
            (server_setup._configure_firewall_rule, (18765,)),
        )
        parser_command = r"""
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput(
    $env:MISSION_LEGAL_POWERSHELL_SOURCE,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_.Message }
    exit 1
}
"""
        for function, arguments in calls:
            with self.subTest(function=function.__name__):
                with mock.patch.object(
                    server_setup, "_run_windows_powershell"
                ) as runner:
                    function(*arguments)
                script = runner.call_args.args[0]
                environment = os.environ.copy()
                environment["MISSION_LEGAL_POWERSHELL_SOURCE"] = script
                completed = subprocess.run(
                    [
                        server_setup._powershell_executable(),
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        parser_command,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=environment,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stderr or completed.stdout,
                )


if __name__ == "__main__":
    unittest.main()
