# Repository Instructions

## Project Overview

This is a Python desktop application for tracking mission legalization workflows.
The UI is built with PySide6, persistence uses SQLAlchemy, and document/OCR
features use PyMuPDF, OpenCV, PaddleOCR, and PaddlePaddle.

## Environment Setup

Use Python 3.12 unless a task specifically requires matching a different local
runtime.

For Codex Cloud, use this setup script:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

if [ -f requirements_lock.txt ]; then
  python -m pip install -r requirements_lock.txt
else
  python -m pip install -r requirements.txt
fi
```

If PySide6 or OpenCV import checks fail because of missing Linux GUI libraries,
add the needed Debian packages in the Codex environment setup before installing
Python requirements.

## Runtime Configuration

The app reads `MISSIONS_ROOT` to choose the mission document storage folder.
In cloud or test environments, set it to a temporary folder, for example:

```bash
export MISSIONS_ROOT=/tmp/mission-legal-data
mkdir -p "$MISSIONS_ROOT"
```

Do not rely on the Windows OneDrive default path in `config.py` when running in
Codex Cloud.

## Useful Commands

Run the desktop app locally:

```bash
python main.py
```

Run a safe non-GUI smoke check:

```bash
python main.py --clean-pycache --dry-run
```

Run tests:

```bash
python -m pytest
```

The current OCR integration test requires local PaddleOCR model directories on a
Windows machine. Do not use it as the default Codex Cloud validation unless those
model paths have been provided. For general cloud work, prefer targeted import
checks and the non-GUI smoke check above.

## Development Guidance

- Keep desktop UI behavior in PySide6 patterns already used under `ui/`.
- Keep workflow and document business logic in `services/`.
- Keep database schema changes in `database/models/` and initialization changes
  in `database/db.py`.
- Avoid committing generated caches, local databases, logs, OCR model downloads,
  or OneDrive document contents.
- When a change touches OCR, PDF rendering, or image processing, mention whether
  it was validated locally or only with cloud-safe checks.
