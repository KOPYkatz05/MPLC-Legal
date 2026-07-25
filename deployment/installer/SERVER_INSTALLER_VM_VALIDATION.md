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
- Do not reuse a real office account for the separate manual Server Manager
  sign-off. Create a disposable standard local account in the VM, use it as the
  selected Manager operator, and remove it before reverting the snapshot. The
  automated harness does not create, sign in to, or drive that desktop session.

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

The versions above are illustrative. The baseline must be a known-good,
immutable, lower-version installer; do not use a previously failed development
artifact merely because its version is lower. Record and compare the SHA-256 of
both exact installers before treating the run as evidence. Treat an
artifact-version or identity mismatch as a release blocker.

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

The harness supplies `/MANAGERACCOUNT` to every silent first-install scenario.
This is required because silent Setup cannot safely infer the intended operator
or launch another user's tray process. The automated run verifies the fourth
installed executable, the registered `ManagerOperatorAccount` value, and the
exact installer-owned HKLM Run command. It does not launch the selected
account's Start-menu shortcut or create an interactive sign-in session.

## What a passing run proves

| Gate | Authoritative evidence |
| --- | --- |
| Deferred silent first install | On a pristine machine, the harness runs the baseline installer with `/VERYSILENT` and an explicit `/MANAGERACCOUNT`. It proves that all four product executables and the uninstaller are present while the service, managed firewall rule, `app.db`, and `server.json` remain absent. It also verifies the registered `ManagerOperatorAccount` value and exact machine-wide Manager startup command. The installed `MissionLegalServerSetup.exe` then creates the configured roots and automatically finalizes service registration, firewall policy, startup, and health. The automated run does not sign in as that operator or launch the tray application. |
| Service policy | The service runs as `LocalSystem`, uses delayed automatic start, has non-crash recovery actions, and points at the exact non-reparse service executable under InstallDir. |
| Server Manager installer registration | `MissionLegalServerManager.exe` is present as the fourth versioned product executable, the expected individual Manager operator account is stored in the installer-owned server registration, and HKLM contains only the exact identity-gated `--startup` command. Uninstall proves that command is removed. This automated gate does not prove the windowed manifest, a selected-standard-user pipe connection, rejection of an unrelated user, tray behavior, or Manager command execution. |
| Network and health | Exactly one enabled inbound Private-only TCP rule uses the fixed managed identity and configured port. Every running state reports the expected version through both loopback and the selected Private-profile IPv4 `/health` endpoint. |
| ProgramData ACLs | Candidate-pristine, same-version, successful-upgrade, downgrade, uninstall-preservation, reinstall, and final-uninstall states recursively prove that sensitive ProgramData grants access only to the LocalSystem and Builtin Administrators SIDs. A temporary non-administrator local account is used to prove that `app.db`, server/device configuration, a backup database, and both TLS private keys cannot be read, while the published public CA can be read but not written. The account and its generated password are never retained in evidence, and account removal is verified after every probe. This filesystem probe does not exercise the selected Manager operator's pipe session. |
| Seeded fixture | The baseline API creates a real row. The harness stops the service, copies `app.db` without external SQLite tooling, verifies its hash, uninstalls, archives ProgramData, and returns to a no-ProgramData product state. |
| Candidate pristine migration | The actual `UpgradeArtifact`, not the baseline artifact, is installed on pristine/no-ProgramData state. Its deferred state is proven, packaged setup receives the seeded fixture with `--existing-database`, the fixture source hash remains unchanged, and the original row ID is read through HTTPS. This catches the empty-database-before-migration failure mode. The candidate is then uninstalled and its ProgramData is archived. |
| Same-version rejection | Running the already-installed `UpgradeArtifact` again exits nonzero and leaves the complete installed-file inventory, version, service, firewall, database, TLS/configuration, device credential, and seeded row unchanged. |
| Fresh upgrade baseline | A separate clean baseline install receives the same fixture and creates the authoritative baseline used for upgrade testing. |
| Mission-root behavior | The LocalSystem service creates a missionary directory and performs API-driven archive/restore directory relocation. A sentinel written by the harness moves with that directory and remains hash-identical. This proves folder creation and relocation; it does not claim that LocalSystem modified the sentinel contents. |
| Backup-root behavior | The service creates a mirrored SQLite backup; its metadata and SHA-256 are verified. |
| Preflight failure | Blocking the database-backup preflight makes setup exit nonzero before replacement and leaves the exact baseline tree, service, firewall, authoritative database, TLS/configuration, credentials, record, and document intact. |
| Real post-copy rollback | A separately authorized watcher observes a service executable at the exact InstallDir whose SHA-256 differs from the baseline while the exact immutable `UpgradeArtifact` process is running. While holding that candidate executable exclusively so it cannot start, the watcher appends an authorized mutation to the authoritative database and then truncates only the installed candidate binary, never the installer artifact. Setup must exit nonzero. The attempt receipt must bind the baseline source hash to the verified snapshot hash and prove sidecar cleanup; the installer log must prove database restoration completed before the prior-service start action. The restored baseline schema version and both pre-upgrade API rows are verified along with the exact baseline file inventory/fingerprint, including the fourth Manager executable, registered Manager operator value, service registration/version/running state, Private firewall rule, health, credentials, TLS/configuration, and document. The automated rollback phase does not launch or reconnect a tray process. |
| Successful upgrade | Setup exits zero, health reports the upgrade version, the original API credential and row still work, a new pre-upgrade database backup from the baseline version matches its metadata, and the fourth Manager executable plus registered operator value remain present. The automated phase does not prove a Manager pipe reconnection or autostart state. |
| Downgrade protection | Running the older artifact exits nonzero and leaves the complete upgraded install tree and persistent state unchanged. |
| Uninstall/reinstall | Uninstall removes the service, exact managed firewall rule, registration, machine-wide Manager startup value, and binaries while preserving ProgramData and external roots. Reinstall uses that retained state, accepts the original device credential, restores the fourth Manager executable, registered operator value, and exact HKLM startup command, and is followed by a final data-preserving uninstall. The automated phase has no running tray process; static/unit checks cover exact legacy-HKCU cleanup matching. |

Focused unit and protocol tests, rather than this VM harness, cover strict frame
parsing and size limits, the command/argument allowlist, pipe DACL construction,
impersonated client authorization, rejection of remote pipe clients, and
pipe-owner-PID matching against the running SCM service. Those tests establish
the implementation contract but do not prove behavior in a real selected-user
desktop session or prove the final packaged UI.

Before release sign-off, use the same disposable VM to sign in as the selected
standard operator and manually verify that the Manager connects without
elevation. Also verify that an unrelated standard account cannot use the Manager
pipe; the tray starts from the machine entry only for the selected SID; the
borderless window opens, drags, and returns to the tray when closed; **Pairing**,
**Status**, **Paired Devices**, and **Tools** work; a copied automatic setup code
can pair a client without manually selecting a certificate; and **Quit Manager**
leaves `MissionLegalServer` running. Verify that the copied URL uses the active
private IPv4 address, the leaf certificate contains that address, and the CA
fingerprint remains unchanged across an address-triggered leaf renewal.
Requesting a
restart from **Tools** must recycle only the API/server runtime while the SCM
service remains alive; the Manager must show a transitional state and report
the API as running only after Uvicorn is ready again. Finally, inspect the
server's listeners/routes and confirm that the feature added no remote
management endpoint or extra TCP listener. Record only pass/fail evidence; do
not retain the generated pairing code or disposable account credential.

The post-copy watcher is destructive by design, but it has no standalone broad
target. The harness creates a short-lived authorization containing the exact
InstallDir, exact target path and hash, exact ProgramData database path and
pre-upgrade hash, upgrade artifact path/hash, and a random token. The watcher
also verifies the live installer PID/path/hash before opening the candidate and
database with exclusive handles. Its database mutation is permitted only while
the distinct candidate executable remains locked, so the candidate cannot
start between mutation and forced failure. It is not referenced by build or
release automation.

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
evidence, mission/backup roots, the fourth-executable and registered-operator
checks, and `result.json`. Pairing codes and device credentials are not written
into `result.json`. The ACL evidence records only well-known SIDs and the
verified allow/deny outcomes; it does not record a temporary standard-user name
or password. Manual Manager sign-off evidence must likewise omit the pairing
code and disposable account credential.

If any phase fails, do not repair the VM and resume. Preserve the logs, revert
to the clean snapshot, fix and rebuild the installer, and rerun with two new
immutable artifacts. A pass is valid only when every phase completes in one run.
