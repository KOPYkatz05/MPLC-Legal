from pathlib import Path


MISSIONS_ROOT = Path(
    r"C:\Users\PerúLimaCentralMissi\OneDrive - Church of Jesus Christ (1)\Sec. Visas\1. Visas Lima Central\1 DOCUMENTOS DE LEGALIZACIÓN - IMPORTANTE"
)


if not MISSIONS_ROOT.exists():
    raise FileNotFoundError(
        f"Mission root folder not found:\n{MISSIONS_ROOT}"
    )