# MPLC Legalization Process Tracker

An internal application for helping mission secretaries track legalization requirements for new missionaries and make onboarding and training more consistent.

## Main-computer server deployment

Mission Legal supports one authoritative SQLite database on the main computer and authenticated HTTPS clients on additional computers. The live SQLite database stays on the main computer's local disk; only verified, rotating snapshots are written to OneDrive.

On the main computer, run PowerShell as Administrator:

```powershell
.\scripts\install_windows_service.ps1 `
  -MissionStorageRoot "C:\path\to\the\mission\OneDrive\folder" `
  -OneDriveBackupDir "C:\path\to\OneDrive\Mission Legal Database Backups"
```

This transfers an existing `data\app.db` to `C:\ProgramData\MissionLegal\app.db` using SQLite's online backup API, verifies integrity, configures TLS, restricts local data permissions, installs the automatic Windows service, configures restart-on-failure, and opens the HTTPS port only on Private networks. It does not overwrite an existing ProgramData database.

Setup also pairs the main computer's desktop application with its own HTTPS service, so the main app and additional computers use the same validation and database access path.

Create a ten-minute, one-use pairing code:

```powershell
.\scripts\create_pairing_code.ps1
```

Copy only the generated `mission-legal-ca.pem` certificate to the additional computer. Never copy either private-key file. Pair the additional computer:

```powershell
python client_setup.py `
  --server "https://MAIN-COMPUTER:8765" `
  --ca-cert "C:\path\to\mission-legal-ca.pem" `
  --pairing-code "123456"
```

Device credentials are stored through Windows Credential Manager. If the main computer is unavailable, a client waits and retries; it never falls back to a local writable database. Configure a DHCP reservation for the main computer and keep BitLocker enabled on its system volume.

List paired devices or revoke one from the main computer:

```powershell
.\scripts\manage_devices.ps1
.\scripts\manage_devices.ps1 -RevokeDeviceId "device-id-from-the-list"
```

Restore a dated OneDrive snapshot from an elevated PowerShell window. The script stops the service, verifies SQLite integrity and the recorded SHA-256 checksum, preserves the current database as a local pre-restore backup, restores the selected snapshot, and restarts the service:

```powershell
.\scripts\restore_database_backup.ps1 `
  -Snapshot "C:\path\to\OneDrive\Mission Legal Database Backups\mission-legal_....db"
```
