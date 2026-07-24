# Mission Legal Server installer

This installer owns only the main-computer server role. It installs the frozen
server at the stable 64-bit per-machine location:

```text
C:\Program Files\Mission Legal\Server
```

The Inno Setup `AppId` is intentionally constant across releases. Do not change
it; doing so would create a second Add/Remove Programs entry and break in-place
upgrades.

## Build

Install the locked Python build dependencies and Inno Setup 6 or 7, then run:

```powershell
.\deployment\build_server_installer.ps1
```

The command rebuilds the frozen server package by default. During iteration, an
already validated package can be reused:

```powershell
.\deployment\build_server_installer.ps1 -SkipServerPackageBuild
```

Skipping the raw build does not skip verification. The builder requires the
sibling `dist\<version>\MissionLegalServer.provenance.json` and checks the exact
server role, application/API/schema versions, current Git source and dependency
locks, successful frozen smoke result, Windows executable versions, and every
packaged file's size/SHA-256 and aggregate tree digest. For a raw folder in
another repository-local location, pass `-ServerPackageDir` and its matching
`-ProvenanceManifestPath` together. A changed file, source state, lock file, or
version requires `build_windows.ps1 -Target Server`; the installer builder will
not relabel an older raw folder.

The script reads `APP_VERSION` from `version.py`, builds the standalone database
maintenance gate, compiles the Inno installer, and writes the installer plus a
SHA-256 release manifest to `dist\<version>\installers`.

Authenticode signing can be enabled with an Inno sign-tool definition:

```powershell
.\deployment\build_server_installer.ps1 `
    -SignToolName missionlegal `
    -SignToolCommand 'signtool.exe sign /fd sha256 /tr https://timestamp.example /td sha256 /a $f' `
    -ExpectedSignerThumbprint 'CERTIFICATE_SHA1_THUMBPRINT' `
    -RequireSigning
```

The signing certificate and timestamp URL are release-operator inputs and must
not be committed to the repository. Unsigned installers are for local testing
only. Production releases should use `deployment/build_release.ps1` with
`-RequireSigning`, which requires signing for both client and server artifacts.
Production validation binds the timestamped outer installer, all three installed
server executables, and the embedded maintenance helper to the expected signer.
The expected identity is Windows' 40-hex certificate SHA-1 thumbprint; payload
and release integrity use SHA-256. The raw provenance-bound folder is never
signed in place: it is copied to a unique transaction, verified again, signed,
compiled, and atomically committed only after every signature check succeeds.
Signed production builds require server-package provenance from a clean Git
commit. Exact dirty provenance is accepted only for unsigned development
installer work.

## Upgrade behavior

Before stopping the service, setup rejects downgrades and normal same-version
reinstalls. Before any installed file is removed or replaced, setup then:

1. stops `MissionLegalServer` and waits for `Stopped`;
2. runs the candidate installer's isolated, standard-library maintenance
   helper, avoiding application startup and database migrations while emitting
   the same verified metadata contract for legacy and current upgrades;
3. opens `%PROGRAMDATA%\MissionLegal\app.db` read-only and runs SQLite
   `PRAGMA integrity_check` on the source;
4. creates a SQLite backup-API snapshot under
   `%PROGRAMDATA%\MissionLegal\Backups\Installer`;
5. integrity-checks the snapshot and records its SHA-256 metadata;
6. atomically writes a unique installer-attempt receipt binding the source and
   target versions, authoritative database path, backup path, metadata path,
   attempt ID, sizes, and SHA-256 digests;
7. for an upgrade, captures the complete Program Files application tree and
   records a SHA-256 inventory for independent binary rollback; for a verified
   first install, requires no installer registration, service, or application
   files and skips the unnecessary binary snapshot;
8. replaces the private application runtime;
9. replaces and verifies the sensitive ProgramData ACLs using well-known SIDs;
10. installs or updates the service at its stable executable path;
11. grants and verifies `LocalSystem` Modify access on any already-configured
   mission-document and mirrored-backup directories;
12. replaces the managed firewall rule with exactly one enabled inbound TCP
    rule for the configured port and the Windows **Private** profile only;
13. starts the service and requires `/health` to report the new application
    version;
14. publishes and verifies a read-only copy of the public CA certificate for
    client setup.

If service or health validation fails after files were copied, setup stops the
candidate and uses only that attempt's durable receipt. It validates the
receipt's versions and paths, both SHA-256 bindings, backup metadata, size, and
SQLite integrity before changing the live database. It then removes stale
`-wal`, `-shm`, and `-journal` sidecars and atomically restores the exact
pre-upgrade snapshot. If no database existed before setup, the receipt instead
restores that exact no-database state. The verified backup and metadata remain
preserved in either case.

Only after database restoration succeeds does setup restore and hash-verify the
prior application tree, re-verify the prior service registration and managed
firewall rule, and restart the prior service if it was running before the
upgrade. A database-restore error fails closed: setup does not retry recovery or
start either candidate or prior binaries automatically. A binary recovery
snapshot that cannot be safely validated is likewise preserved and blocks
another same-version capture instead of being overwritten.

Until the server has an installer-validation read-only marker, run upgrades in
a short maintenance window with client applications closed. The candidate is
live briefly while `/health` is evaluated; if it accepts a write and then fails
validation, exact pre-upgrade restoration necessarily discards that
post-snapshot write. A future validation-mode gate should reject API mutations
until setup commits the successful upgrade.

Any failed gate produces a nonzero setup result. Setup and uninstall logging are
always enabled; the service and maintenance helpers also append logs under
`%PROGRAMDATA%\MissionLegal\Logs`. Binary rollback diagnostics are written to
`installer-rollback.log`, including the exact hidden PowerShell error.

Silent upgrades are supported by Inno Setup:

```powershell
.\MissionLegalServerSetup-<version>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG
```

The updater must treat every nonzero installer exit code as failure. It should
also verify the release-manifest SHA-256 before launching setup.

## First server configuration

An interactive first install now includes a small guided setup:

1. choose **Create a fresh server** or **Migrate a verified database snapshot**;
2. select the existing mission-document folder;
3. select the OneDrive database-backup folder;
4. for migration, select the `.db` snapshot.

After the files are copied, the installer runs the packaged server-setup utility
under the elevation already granted to Setup. It configures the protected
ProgramData state, storage ACLs, Private-profile firewall rule, Windows service,
startup, and health check. No Administrator PowerShell window or second command
is required. The guided path always uses `--skip-main-client`, so it never writes
desktop credentials or settings into the elevated administrator's profile, and
it never passes `--replace-existing-database`.

The migration source is integrity-checked and remains unchanged. If a populated
authoritative database already exists, guided migration fails without replacing
it. If setup fails after creating or migrating the database, the installer
removes the candidate service, restores the receipted database or no-database
state, and lets Inno Setup remove the new application files.

Unattended `/SILENT` and `/VERYSILENT` first installs deliberately retain the
old deferred behavior because there are no interactive path selections. They
lay down the binaries and uninstaller but do not create the service, managed
firewall rule, `app.db`, or `server.json`. Finish one of those installs with the
packaged utility:

```powershell
& "$env:ProgramFiles\Mission Legal\Server\MissionLegalServerSetup.exe" `
    --onedrive-backup-dir "C:\path\to\OneDrive\Mission Legal Backups" `
    --mission-storage-root "C:\path\to\Mission Documents" `
    --skip-main-client
if ($LASTEXITCODE -ne 0) {
    throw "Mission Legal Server configuration failed."
}
```

The installed setup utility detects its fixed
`InstallerSupport\server_installer_actions.ps1` helper after configuration is
complete. It passes the installed directory, current server data directory,
and packaged application version as separate process arguments, then runs the
checked `InstallOrUpdate` and `StartAndVerify` actions. A successful return
therefore proves that the service is registered, running, and reporting the
packaged version through `/health`. If health verification fails, setup stops
the service and returns a nonzero result.

This automatic finish is intentionally limited to the Inno-installed frozen
folder. A raw PyInstaller folder has no `InstallerSupport` helper, so its setup
utility reports that service registration remains manual.

### Server-data access policy

Setup and every installer upgrade fail closed unless the server-data ACL can be
applied and read back successfully. `%PROGRAMDATA%\MissionLegal`, its database,
backups, configuration, device records, and TLS private keys allow only these
well-known identities:

- LocalSystem (`S-1-5-18`): FullControl;
- Builtin Administrators (`S-1-5-32-544`): FullControl.

Sensitive ACL inheritance is removed, the owner is set to Builtin
Administrators, reparse points are rejected, and existing descendants are
repaired recursively. New runtime files inherit only the same two identities.
There is no separate read grant for the Windows account that ran setup.

The only client-readable exception is the deliberately published public
certificate:

```text
C:\ProgramData\MissionLegal\Public\mission-legal-ca.pem
```

That directory and file grant Builtin Users (`S-1-5-32-545`) ReadAndExecute,
never write-capable access. The source CA certificate and both private keys stay
inside the protected configuration tree. When setup configures the main client,
its `server/ca_certificate` setting points to this public copy. Publication is
atomic, verifies that its SHA-256 matches the protected source certificate, and
refuses unexpected files or reparse points in the public directory.

Setup checks every Windows command it runs. It grants `LocalSystem` inherited
Modify access to both configured storage directories and verifies the resulting
ACL. It also creates or updates the fixed `MissionLegalServerHTTPS` firewall
rule, verifies its port/direction/action/profile, and removes an older rule with
the same product display name. Changing `--port` replaces the previous managed
rule instead of leaving the old port open.

### Existing database migration

An explicitly supplied `--existing-database` is never ignored:

- the source must exist and pass SQLite integrity verification;
- `MissionLegalServer` must be absent or stopped;
- if no authoritative destination exists, setup transfers and verifies the
  source through SQLite's backup API;
- if the installer-created destination contains only an empty application
  schema, setup preserves a verified local snapshot and safely replaces it;
- if the destination contains application data, setup refuses the operation
  without changing either database.

For a normal first-server migration, select **Migrate a verified database
snapshot** in the interactive installer. The manual command below is reserved
for a deferred/silent install or for an explicitly reviewed replacement of
already-populated authoritative data.

Replacing a populated authoritative database requires deliberate authority:

```powershell
Stop-Service MissionLegalServer -ErrorAction SilentlyContinue
& "$env:ProgramFiles\Mission Legal\Server\MissionLegalServerSetup.exe" `
    --onedrive-backup-dir "C:\path\to\OneDrive\Mission Legal Backups" `
    --mission-storage-root "C:\path\to\Mission Documents" `
    --existing-database "D:\verified-transfer\app.db" `
    --replace-existing-database `
    --skip-main-client
if ($LASTEXITCODE -ne 0) {
    Start-Service MissionLegalServer -ErrorAction SilentlyContinue
    throw "Existing database migration failed; the prior database was preserved."
}
```

On success the installed setup utility registers or updates, starts, and
health-verifies the service; do not run a second manual `Start-Service`.

Use `--replace-existing-database` only after reviewing and preserving both data
sets. Setup checkpoints and verifies the destination, creates a verified local
snapshot under `%PROGRAMDATA%\MissionLegal\Backups`, stages and verifies the
incoming database, and restores the prior destination if replacement fails.
The supplied source is not deleted or moved.

## Uninstall safety

Uninstall stops and deletes only the Windows service, removes the exact managed
firewall rule, and removes files recorded under the Program Files application
directory. It never deletes ProgramData, mission documents, backups, TLS/device
credentials, or any user's LocalAppData. Those remain available for reinstall
or manual archival.

## Disposable-VM release validation

Do not validate the elevated installer on a development workstation or the real
server. The strongly gated procedure proves deferred first install and packaged
setup finalization, tests the actual candidate on pristine/no-ProgramData
migration, rejects the same version, exercises separate preflight and real
post-copy rollback failures, checks loopback plus selected-Private-IPv4 health,
and then covers successful upgrade, downgrade, uninstall, and reinstall. It is
documented in
[`SERVER_INSTALLER_VM_VALIDATION.md`](SERVER_INSTALLER_VM_VALIDATION.md). The
execution harness is never called by a build or release script and requires a
short-lived machine-bound consent marker at the exact dedicated ProgramData
path inside a recognized disposable VM.
