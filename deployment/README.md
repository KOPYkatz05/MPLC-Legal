# Windows release builds

The release pipeline produces a per-user client installer with a Velopack
update feed and an elevated server installer. Its inputs are two
self-contained, versioned PyInstaller folders; Python is not required on a
target computer.

- `MissionLegalClient` contains `MissionLegal.exe`, a console diagnostics entry,
  the pairing utility, Qt/Fluent resources, OCR dependencies, and the three
  pinned OCR models.
- `MissionLegalServer` contains the server CLI, server configuration utility,
  and Windows service executable. It never contains a database, TLS private key,
  backup, or mission document.

## Complete release

Install Inno Setup 6 or 7 on the build computer, then build the raw folders,
both installers, and the SHA-256 release summary in one command:

First set a new, unpublished `APP_VERSION` in `version.py`. Published client
versions are immutable, so every release must use a higher version.
Keep `MIN_SUPPORTED_CLIENT_VERSION` unchanged for compatible releases. Raise it
only when the server can no longer safely serve an older client, and adjust the
supported server API range only when the API contract actually changes.

```powershell
.\deployment\build_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -InstallVpk
```

This is an unsigned development build. Production builds must pass
`-RequireSigning` together with client and server signing configuration; the
command fails before building if either role is missing. Use `-SkipRawBuilds`
to reuse already-validated folders under `dist\<APP_VERSION>`.

The command does not upload anything. Publish the complete client feed
directory only after validation. Detailed operator guidance is in
[CLIENT_RELEASES.md](CLIENT_RELEASES.md) and
[installer/SERVER_INSTALLER.md](installer/SERVER_INSTALLER.md).

## Build environment

Build on 64-bit Windows with Python 3.12. A clean build environment is strongly
recommended:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\venv\Scripts\python.exe -m pip install -r requirements_lock.txt
.\venv\Scripts\python.exe -m pip install -r requirements_build.txt
```

The client build requires the existing PaddleOCR model tree. Its expected
default is `C:\Local Apps\paddle_models\.paddleocr\whl`; override it with
`-OcrModelRoot` when necessary.

Build and smoke-test both folders:

```powershell
.\deployment\build_windows.ps1
```

Or build one role:

```powershell
.\deployment\build_windows.ps1 -Target Client
.\deployment\build_windows.ps1 -Target Server
```

Output is written beneath `dist\<APP_VERSION>`. PyInstaller work files go under
`build\pyinstaller\<APP_VERSION>`. Both locations are ignored by Git.

The current correctness-first baseline is approximately 1.3 GB for the client
folder and 520 MB for the server folder before ZIP/installer compression. A
fully clean client analysis can take 15 minutes or more on this OCR stack. These
figures are optimization targets, not stable release limits.

## Raw client-folder test

Pair before opening the GUI:

```powershell
.\MissionLegalClientSetup.exe `
  --server "https://MAIN-COMPUTER:8765" `
  --ca-cert "C:\path\to\mission-legal-ca.pem" `
  --pairing-code "123456"

.\MissionLegal.exe
```

Pairing copies the CA certificate into the current user's stable Mission Legal
configuration folder. An unpaired frozen client exits without creating or
opening a local database.

## Installed server first run

On a pristine computer the elevated server installer lays down the binaries but
leaves the service, managed firewall rule, `app.db`, and `server.json` absent
until the authoritative database and server paths have been configured. Run the
installed setup utility once from an elevated PowerShell window:

```powershell
& "$env:ProgramFiles\Mission Legal\Server\MissionLegalServerSetup.exe" `
  --mission-storage-root "C:\path\to\mission documents" `
  --onedrive-backup-dir "C:\path\to\OneDrive\Mission Legal Database Backups" `
  --skip-main-client
```

The installed utility automatically invokes the packaged checked service
helper to register or update `MissionLegalServer`, apply the storage/firewall
policy, start it, and require the packaged version from `/health`. A nonzero
exit means first-run setup is incomplete; do not pair clients until it succeeds.

## Raw server-folder test

Run these commands from an elevated PowerShell window. Use a stable folder path;
the service registration points at `MissionLegalService.exe` in that folder.
Unlike the installed folder, the raw PyInstaller output has no
`InstallerSupport` helper. Its setup utility deliberately leaves registration
and startup to the explicit commands below.

```powershell
.\MissionLegalServerSetup.exe `
  --mission-storage-root "C:\path\to\mission documents" `
  --onedrive-backup-dir "C:\path\to\OneDrive\Mission Legal Database Backups" `
  --skip-main-client

.\MissionLegalService.exe --startup auto install
.\MissionLegalService.exe start
.\MissionLegalServer.exe --create-pairing-code
```

`MissionLegalServerSetup.exe` verifies a Private-profile-only inbound TCP
firewall rule for its configured port and checked `LocalSystem` Modify ACLs on
the mission-document and mirrored-backup roots. Stop the service before passing
`--existing-database`. An empty installer-created database is preserved and
safely replaced; a populated authoritative database is refused unless the
operator also supplies `--replace-existing-database`. Full migration and
recovery semantics are documented in
[`installer/SERVER_INSTALLER.md`](installer/SERVER_INSTALLER.md).

The authoritative database and server identity remain under
`C:\ProgramData\MissionLegal`; replacing the packaged folder does not replace
that data. The server installer automates the service stop, verified
pre-upgrade backup, replacement, restart, and health check.

## Validation boundary

The build script runs import/resource smoke tests against the frozen folders.
Before calling a release dependable, also test on a clean Windows computer or
VM with no Python installation:

1. Configure and start the server service, then reboot it.
2. Pair the client and verify authenticated HTTPS access.
3. Open/render/save a PDF and export a workbook.
4. Run OCR on a real supported document using the bundled models.
5. Verify client, OCR-worker, and server logs in their writable data folders.
6. Upgrade with both installers and confirm ProgramData and client credentials
   remain intact.
7. Publish a second client version to a test feed and verify automatic download,
   restart, and rollback-safe handling of an interrupted update.

The server portion has a strongly gated, non-automatic disposable-VM harness:
[`installer/SERVER_INSTALLER_VM_VALIDATION.md`](installer/SERVER_INSTALLER_VM_VALIDATION.md).
It covers clean install, first-run existing-database migration, LocalSystem
folder creation/relocation and mirrored-backup access, the actual upgrade
artifact on pristine/no-ProgramData state, behavioral same-version rejection,
Private-profile firewall scope, loopback plus selected-Private-IPv4 health,
separate preflight and post-copy rollback failures, successful upgrade,
downgrade rejection, uninstall preservation, and reinstall recovery.
