# Windows onedir packages

The packaging layer produces two self-contained, versioned Windows folders.
Python is not required on a target computer.

- `MissionLegalClient` contains `MissionLegal.exe`, a console diagnostics entry,
  the pairing utility, Qt/Fluent resources, OCR dependencies, and the three
  pinned OCR models.
- `MissionLegalServer` contains the server CLI, server configuration utility,
  and Windows service executable. It never contains a database, TLS private key,
  backup, or mission document.

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

## Raw server-folder test

Run these commands from an elevated PowerShell window. Use a stable folder path;
the service registration points at `MissionLegalService.exe` in that folder.

```powershell
.\MissionLegalServerSetup.exe `
  --mission-storage-root "C:\path\to\mission documents" `
  --onedrive-backup-dir "C:\path\to\OneDrive\Mission Legal Database Backups" `
  --skip-main-client

.\MissionLegalService.exe --startup auto install
.\MissionLegalService.exe start
.\MissionLegalServer.exe --create-pairing-code
```

The authoritative database and server identity remain under
`C:\ProgramData\MissionLegal`; replacing the packaged folder does not replace
that data. The installer phase will automate service stop/replacement/start and
normal-user client pairing.

## Validation boundary

The build script runs import/resource smoke tests against the frozen folders.
Before calling a release dependable, also test on a clean Windows computer or
VM with no Python installation:

1. Configure and start the server service, then reboot it.
2. Pair the client and verify authenticated HTTPS access.
3. Open/render/save a PDF and export a workbook.
4. Run OCR on a real supported document using the bundled models.
5. Verify client, OCR-worker, and server logs in their writable data folders.
6. Replace both version folders and confirm ProgramData and client credentials
   remain intact.
