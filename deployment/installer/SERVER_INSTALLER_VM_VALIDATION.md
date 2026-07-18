# Server installer disposable-VM validation

`validate_server_installer_vm.ps1` is the destructive release-candidate gate
for the Mission Legal server installer. Its `-Execute` mode is never invoked by
a build, release, or automated test. Never run `-Execute` on a workstation, the
real server, or a VM containing data you need.

The gate uses the production service name, uninstall identity, Program Files
directory, firewall identity, and `%PROGRAMDATA%\MissionLegal`. Redirecting any
of those would stop testing the real installer. Isolation therefore comes from
a clean, disposable Windows VM snapshot.

## Safety contract

Execution is refused unless all of these conditions are true:

1. The process is 64-bit Windows PowerShell on 64-bit Windows and is elevated.
2. Windows reports a recognized Hyper-V, VMware, VirtualBox, KVM/QEMU, Xen, or
   Parallels virtual-machine identity.
3. `-Execute` and the exact disposable-VM confirmation text are both present.
4. The exact machine-GUID-bound marker
   `%PROGRAMDATA%\MissionLegalInstallerValidation\vm-consent.json` exists,
   belongs to this Windows machine GUID and computer name, and has not expired.
5. The marker directory and file have no reparse-point ancestor, protected ACL
   inheritance, an Administrators or LocalSystem owner, and FullControl rules
   only for Administrators and LocalSystem.
6. The service, exact managed firewall rule, uninstall registration, Program
   Files installation, and `%PROGRAMDATA%\MissionLegal` are all absent.
7. `WorkRoot` is an initially absent top-level directory on a fixed local volume
   named `MissionLegalInstallerValidation-*`. It cannot be inside Windows,
   Program Files, ProgramData, or a user profile, and none of its existing
   ancestors may be a reparse point.
8. The baseline and upgrade installers are different immutable artifacts whose
   embedded versions match the supplied versions.
9. Both installers have valid Authenticode signatures, unless the operator
   explicitly allows unsigned development artifacts.

Marker creation refuses to overwrite or reuse its dedicated directory. Revert
the VM snapshot to create a new marker after a run or expiration. The harness
also rejects a registered uninstaller unless it is a normal, non-reparse file
named `unins*.exe` directly inside the exact server InstallDir.

The harness never recursively deletes product data. It deliberately leaves the
last database, TLS material, backups, mission-document sentinel, logs, and
result JSON in the disposable VM. Revert the snapshot after collecting evidence.

## Required VM and artifacts

- Use a current 64-bit Windows 10/11 or Windows Server VM with no prior Mission
  Legal installation.
- Take a clean snapshot before copying artifacts into the VM.
- Copy a signed baseline installer and a signed, newer upgrade installer into
  the VM. Do not rebuild or overwrite either artifact afterward.
- Copy these three scripts together:
  `validate_server_installer_vm.ps1`,
  `new_server_installer_vm_marker.ps1`, and
  `server_installer_failure_watcher.ps1`.
- Ensure TCP ports 8765 and 18765 are free. A different isolated setup port can
  be supplied with `-ValidationPort`.
- Connect the VM through an IPv4 adapter whose Windows network category is
  **Private**. The harness refuses Public/Domain-only connectivity.

## Run non-mutating validation first

`-ValidateOnly` reads artifact metadata, validates the safe WorkRoot shape, and
reports current machine state and the planned scenario as JSON. It does not
require elevation or a marker, creates no directory, and performs no installer,
service, firewall, registry, or data mutation.

```powershell
.\validate_server_installer_vm.ps1 `
    -BaselineInstaller C:\ValidationArtifacts\MissionLegalServerSetup-0.1.0.exe `
    -BaselineVersion 0.1.0 `
    -UpgradeInstaller C:\ValidationArtifacts\MissionLegalServerSetup-0.1.1.exe `
    -UpgradeVersion 0.1.1 `
    -ValidateOnly
```

Treat an artifact-version or identity mismatch as a release blocker.

## Create the short-lived marker

Open 64-bit **Windows PowerShell as Administrator** in the clean VM:

```powershell
.\new_server_installer_vm_marker.ps1 `
    -CreateMarker `
    -DisposableVmConfirmation "I CONFIRM THIS IS A DISPOSABLE MISSION LEGAL TEST VM" `
    -ExpiresInHours 8
```

Marker creation independently rechecks VM identity, elevation, 64-bit process,
pristine product state, exact path, reparse safety, owner, and ACL. Its maximum
lifetime is 24 hours.

## Execute the release gate

From the same elevated session:

```powershell
.\validate_server_installer_vm.ps1 `
    -BaselineInstaller C:\ValidationArtifacts\MissionLegalServerSetup-0.1.0.exe `
    -BaselineVersion 0.1.0 `
    -UpgradeInstaller C:\ValidationArtifacts\MissionLegalServerSetup-0.1.1.exe `
    -UpgradeVersion 0.1.1 `
    -Execute `
    -DisposableVmConfirmation "I CONFIRM THIS IS A DISPOSABLE MISSION LEGAL TEST VM"
```

Unsigned development artifacts require `-AllowUnsignedInstallers`; such a run
is not production-release evidence. `-WorkRoot` is the only storage-path
override. Its default on `C:` is
`C:\MissionLegalInstallerValidation-VM`. Every mission and mirror-backup root is
first proven absent beneath the unique RunRoot and checked for reparse points.
The harness then creates the operator-selected mission root required by the CLI;
packaged setup creates the backup root.

## What a passing run proves

| Gate | Authoritative evidence |
| --- | --- |
| Deferred first install | On a pristine machine, the baseline installer lays down registered binaries and the uninstaller but leaves the service, managed firewall rule, `app.db`, and `server.json` absent. The installed `MissionLegalServerSetup.exe` then creates the configured roots and automatically finalizes service registration, firewall policy, startup, and health. |
| Service policy | The service runs as `LocalSystem`, uses delayed automatic start, has non-crash recovery actions, and points at the exact non-reparse service executable under InstallDir. |
| Network and health | Exactly one enabled inbound Private-only TCP rule uses the fixed managed identity and configured port. Every running state reports the expected version through both loopback and the selected Private-profile IPv4 `/health` endpoint. |
| Seeded fixture | The baseline API creates a real row. The harness stops the service, copies `app.db` without external SQLite tooling, verifies its hash, uninstalls, archives ProgramData, and returns to a no-ProgramData product state. |
| Candidate pristine migration | The actual `UpgradeArtifact`, not the baseline artifact, is installed on pristine/no-ProgramData state. Its deferred state is proven, packaged setup receives the seeded fixture with `--existing-database`, the fixture source hash remains unchanged, and the original row ID is read through HTTPS. This catches the empty-database-before-migration failure mode. The candidate is then uninstalled and its ProgramData is archived. |
| Same-version rejection | Running the already-installed `UpgradeArtifact` again exits nonzero and leaves the complete installed-file inventory, version, service, firewall, database, TLS/configuration, device credential, and seeded row unchanged. |
| Fresh upgrade baseline | A separate clean baseline install receives the same fixture and creates the authoritative baseline used for upgrade testing. |
| Mission-root behavior | The LocalSystem service creates a missionary directory and performs API-driven archive/restore directory relocation. A sentinel written by the harness moves with that directory and remains hash-identical. This proves folder creation and relocation; it does not claim that LocalSystem modified the sentinel contents. |
| Backup-root behavior | The service creates a mirrored SQLite backup; its metadata and SHA-256 are verified. |
| Preflight failure | Blocking the database-backup preflight makes setup exit nonzero before replacement and leaves the exact baseline tree, service, firewall, authoritative database, TLS/configuration, credentials, record, and document intact. |
| Real post-copy rollback | A separately authorized watcher observes a service executable at the exact InstallDir whose SHA-256 differs from the baseline while the exact immutable `UpgradeArtifact` process is running. It truncates only that installed candidate, never the installer artifact. Setup must exit nonzero and restore the exact baseline file inventory/fingerprint, service binary, registration, version, running state, Private firewall rule, health, database, credentials, TLS/configuration, row, and document. |
| Successful upgrade | Setup exits zero, health reports the upgrade version, the original API credential and row still work, and a new pre-upgrade database backup from the baseline version matches its metadata. |
| Downgrade protection | Running the older artifact exits nonzero and leaves the complete upgraded install tree and persistent state unchanged. |
| Uninstall/reinstall | Uninstall removes service, exact managed firewall rule, registration, and binaries while preserving ProgramData and external roots. Reinstall uses that retained state, accepts the original device credential, and is followed by a final data-preserving uninstall. |

The post-copy watcher is destructive by design, but it has no standalone broad
target. The harness creates a short-lived authorization containing the exact
InstallDir, exact target path, baseline hash, upgrade artifact path/hash, and a
random token. The watcher also verifies the live installer PID/path/hash before
opening the candidate with an exclusive handle. It is not referenced by build
or release automation.

The firewall and dual-surface health checks run inside the VM. A real request
originating from a second computer remains part of the client-pairing boundary
in `deployment/README.md`; an in-VM request cannot prove hypervisor/NAT or
external network reachability.

## Results and failure handling

Each run creates a unique directory such as:

```text
C:\MissionLegalInstallerValidation-VM\run-20260717T220000Z-1234abcd
```

It contains Inno setup/uninstall logs, process output, a transcript, the seeded
fixture, separately archived ProgramData scenarios, watcher authorization and
evidence, mission/backup roots, and `result.json`. Pairing codes and device
credentials are not written into `result.json`.

If any phase fails, do not repair the VM and resume. Preserve the logs, revert
to the clean snapshot, fix and rebuild the installer, and rerun with two new
immutable artifacts. A pass is valid only when every phase completes in one run.
