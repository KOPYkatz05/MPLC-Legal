# Codex Cloud Setup

Use this guide when creating the Codex Cloud environment for this repository:

`KOPYkatz05/MPLC-Legal`

## Recommended Environment

- Base image: `universal`
- Python version: `3.12`
- Agent internet access: off by default; enable it only for tasks that need live
  documentation or package/network access during the agent phase.
- Environment variable:
  - `MISSIONS_ROOT=/tmp/mission-legal-data`

## Setup Script

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

if [ -f requirements_lock.txt ]; then
  python -m pip install -r requirements_lock.txt
else
  python -m pip install -r requirements.txt
fi

mkdir -p /tmp/mission-legal-data
```

## Maintenance Script

```bash
source .venv/bin/activate

if [ -f requirements_lock.txt ]; then
  python -m pip install -r requirements_lock.txt
else
  python -m pip install -r requirements.txt
fi

mkdir -p /tmp/mission-legal-data
```

## Cloud-Safe Validation

```bash
source .venv/bin/activate
export MISSIONS_ROOT=/tmp/mission-legal-data
python main.py --clean-pycache --dry-run
```

The current pytest suite contains an OCR integration test that references
Windows-local PaddleOCR model paths. Run it only on a machine where those model
folders exist, or after adding cloud-accessible model setup.

## Codex Cloud UI Steps

1. Open `https://chatgpt.com/codex/settings/environments`.
2. Create a new environment.
3. Select `KOPYkatz05/MPLC-Legal`.
4. Use the default branch, `main`.
5. Set Python to `3.12`.
6. Add `MISSIONS_ROOT=/tmp/mission-legal-data` as an environment variable.
7. Paste the setup script and maintenance script above.
8. Save the environment and let Codex build the cache.
