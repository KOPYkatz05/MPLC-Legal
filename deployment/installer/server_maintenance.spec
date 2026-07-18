# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


SPEC_DIR = Path(SPEC).resolve().parent

analysis = Analysis(
    [str(SPEC_DIR / "server_maintenance.py")],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="MissionLegalServerMaintenance",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
