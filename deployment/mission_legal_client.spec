# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path


SPEC_DIR = Path(SPEC).resolve().parent
REPO_ROOT = SPEC_DIR.parent
sys.path.insert(0, str(SPEC_DIR))

from pyinstaller_common import (  # noqa: E402
    CLIENT_HIDDEN_IMPORTS,
    application_datas,
    ocr_model_datas,
    windows_version_info,
)


hook_paths = [str(SPEC_DIR / "hooks")]
client_analysis = Analysis(
    [str(REPO_ROOT / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=application_datas(REPO_ROOT) + ocr_model_datas(),
    hiddenimports=CLIENT_HIDDEN_IMPORTS,
    hookspath=hook_paths,
    hooksconfig={},
    runtime_hooks=[],
    excludes=["paddle.jit.sot"],
    noarchive=False,
    optimize=0,
)
setup_analysis = Analysis(
    [str(REPO_ROOT / "client_setup.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=["keyring.backends.Windows", "win32cred"],
    hookspath=hook_paths,
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
update_worker_analysis = Analysis(
    [str(REPO_ROOT / "client_update_worker.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=["velopack"],
    hookspath=hook_paths,
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

client_pyz = PYZ(client_analysis.pure)
client_exe = EXE(
    client_pyz,
    client_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Client",
        original_filename="MissionLegal.exe",
    ),
)
diagnostic_pyz = PYZ(client_analysis.pure)
diagnostic_exe = EXE(
    diagnostic_pyz,
    client_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegalDiagnostics",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Diagnostics",
        original_filename="MissionLegalDiagnostics.exe",
    ),
)
setup_pyz = PYZ(setup_analysis.pure)
setup_exe = EXE(
    setup_pyz,
    setup_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegalClientSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Client Setup",
        original_filename="MissionLegalClientSetup.exe",
    ),
)
update_worker_pyz = PYZ(update_worker_analysis.pure)
update_worker_exe = EXE(
    update_worker_pyz,
    update_worker_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegalUpdateWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Update Worker",
        original_filename="MissionLegalUpdateWorker.exe",
    ),
)

bundle = COLLECT(
    client_exe,
    diagnostic_exe,
    setup_exe,
    update_worker_exe,
    client_analysis.binaries,
    client_analysis.datas,
    setup_analysis.binaries,
    setup_analysis.datas,
    update_worker_analysis.binaries,
    update_worker_analysis.datas,
    strip=False,
    upx=False,
    name="MissionLegalClient",
)
