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

The script reads `APP_VERSION` from `version.py`, builds the standalone database
maintenance gate, compiles the Inno installer, and writes the installer plus a
SHA-256 release manifest to `dist\<version>\installers`.

Authenticode signing can be enabled with an Inno sign-tool definition:

```powershell
.\deployment\build_server_installer.ps1 `
    -SignToolName missionlegal `
    -SignToolCommand 'signtool.exe sign /fd sha256 /tr https://timestamp.example /td sha256 /a $f'
```

The signing certificate and timestamp URL are release-operator inputs and must
not be committed to the repository. Unsigned installers are for local testing
only. Production releases should use `deployment/build_release.ps1` with
`-RequireSigning`, which requires signing for both client and server artifacts.
When a server sign tool is supplied directly, the builder also requires the
resulting installer to have a valid Authenticode signature.

## Upgrade behavior

Before stopping the service, setup rejects downgrades and normal same-version
reinstalls. Before any installed file is removed or replaced, setup then:

1. stops `MissionLegalServer` and waits for `Stopped`;
2. asks the installed `MissionLegalServer.exe --backup-before-upgrade` command
   to create and verify the snapshot;
3. for the first upgrade from a legacy package that lacks that command, runs a
   standalone standard-library maintenance gate carried inside setup;
4. opens `%PROGRAMDATA%\MissionLegal\app.db` read-only and runs SQLite
   `PRAGMA integrity_check` on the source;
5. creates a SQLite backup-API snapshot under
   `%PROGRAMDATA%\MissionLegal\Backups\Installer`;
6. integrity-checks the snapshot and records its SHA-256 metadata;
7. captures the complete Program Files application tree and records a SHA-256
   inventory for independent binary rollback;
8. replaces the private application runtime;
9. installs or updates the service at its stable executable path;
10. grants and verifies `LocalSystem` Modify access on any already-configured
   mission-document and mirrored-backup directories;
11. replaces the managed firewall rule with exactly one enabled inbound TCP
    rule for the configured port and the Windows **Private** profile only;
12. starts the service and requires `/health` to report the new application
    version.

If service or health validation fails after files were copied, setup restores
and hash-verifies the prior application tree, re-verifies the prior service
registration and managed firewall rule, and restarts the prior service only if
it was running before the upgrade. A recovery snapshot that cannot be safely
validated is preserved and blocks another same-version capture instead of being
overwritten.

Any failed gate produces a nonzero setup result. Setup and uninstall logging are
always enabled; the service and maintenance helpers also append logs under
`%PROGRAMDATA%\MissionLegal\Logs`.

Silent upgrades are supported by Inno Setup:

```powershell
.\MissionLegalServerSetup-<version>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG
```

The updater must treat every nonzero installer exit code as failure. It should
also verify the release-manifest SHA-256 before launching setup.

## First server configuration

The installer deliberately does not write user-profile settings while elevated.
On a fresh machine where `app.db` and `Configuration\server.json` are not both
present, it installs the binaries and registered uninstaller but creates neither
the service nor the managed firewall rule. It also leaves `app.db` and
`server.json` absent. This prevents an automatic service start from creating an
empty authoritative database before setup can migrate the real database.

After the first install, open an elevated PowerShell window as the intended
Windows account. Configure the mission-storage and backup locations with the
packaged setup utility:

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
