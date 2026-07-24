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
command also requires `-ExpectedSignerThumbprint` with the approved signing
certificate's 40-hex Windows SHA-1 thumbprint and fails before building if any
role or identity is missing. Use `-SkipRawBuilds`
to reuse already-validated folders under `dist\<APP_VERSION>`; the downstream
builders still verify each folder against its sibling provenance manifest.
Signed production builds additionally require that manifest to record a clean
Git commit. Dirty, exactly matched provenance remains available for unsigned
development builds.

Production builds import the published client history from `UpdateUrl` by
default and require a strictly increasing SemVer. Only the first production
release may pass `-InitialRelease`; that mode fails if either the local channel
or the published source already contains assets.

The command does not upload anything. Publish the complete client feed
directory only after validation. Detailed operator guidance is in
[CLIENT_RELEASES.md](CLIENT_RELEASES.md) and
[installer/SERVER_INSTALLER.md](installer/SERVER_INSTALLER.md).

Each builder uses a unique transaction-local output and commits the completed
directory only after validation. The orchestrator then atomically creates
`dist\<version>\release-metadata`, containing immutable snapshots of both raw
provenance manifests, the client JSON feed state, the server installer manifest,
and `release-summary.json` with SHA-256/size and signature evidence. It never
overwrites that per-version metadata.

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

Each successful role smoke test also writes a manifest beside, never inside,
the raw role folder:

```text
dist\<APP_VERSION>\
  MissionLegalClient\
  MissionLegalClient.provenance.json
  MissionLegalServer\
  MissionLegalServer.provenance.json
```

The deterministic manifest binds the role and application/API/schema versions,
Git commit and exact dirty state, Python/platform/build-tool versions, hashes of
both dependency lock files, the successful frozen smoke result, and every
packaged path with its byte size and SHA-256. It also records the Windows
`FileVersion` and `ProductVersion` of every PyInstaller executable. Client
provenance additionally binds the three source OCR model trees byte-for-byte to
their packaged copies. Its sorted file inventory produces one package-tree
digest; the manifest stays outside the folder so it never needs a self-hash.

Client and server installer builders always re-run this verification, including
direct-input and skip-raw-build paths. A changed source tree, dependency lock,
package byte, role, or requested version is not relabeled: rebuild that raw role
with `build_windows.ps1`. The manifest is local build evidence, not a substitute
for Authenticode and published release hashes.

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

On an interactive first install, the elevated server installer asks whether this
computer will create a fresh server or migrate a verified `.db` snapshot. It
then asks for the existing mission-document folder and the OneDrive
database-backup folder. For migration, it also asks for the snapshot file.

Setup automatically runs the installed configuration utility with its existing
elevation, configures the service and Private-profile firewall rule, starts the
server, and health-checks the packaged version. It preserves a migration source,
never authorizes replacement of a populated authoritative database, and does
not write main-client settings into the elevated administrator's profile. Setup
is complete only after the service owns the configured listener, remains stable,
passes the final health check, publishes the verified public CA, and commits the
protected `Configuration\installer-ready-v1.marker`.

`/SILENT` and `/VERYSILENT` first installs still defer configuration because no
storage paths were selected. To finish one of those installs manually, run:

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
If an interactive first attempt fails before the readiness marker is committed,
running the installer again reopens the guided fresh/migration setup even when
some protected database or configuration state remains from recovery.

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
operator also supplies `--replace-existing-database`, except that a byte-for-byte
identical supplied snapshot is accepted as the already-authoritative database
for a safe retry. Full migration and recovery semantics are documented in
[`installer/SERVER_INSTALLER.md`](installer/SERVER_INSTALLER.md).

The authoritative database and server identity remain under
`C:\ProgramData\MissionLegal`; replacing the packaged folder does not replace
that data. The server installer automates the service stop, verified
pre-upgrade backup, replacement, restart, and health check.

The server installer also enforces a SID-based ProgramData boundary: sensitive
database, backup, configuration, device, and TLS-key material is limited to
LocalSystem and Builtin Administrators. Client setup uses the deliberately
read-only public CA copy at
`C:\ProgramData\MissionLegal\Public\mission-legal-ca.pem`; no private key is
made client-readable.

## Validation boundary

The build script runs import/resource smoke tests against the frozen folders and
emits the verified raw-package provenance described above.
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
downgrade rejection, uninstall preservation, reinstall recovery, and an actual
standard-user read-denial/read-only-public-CA ACL probe.
