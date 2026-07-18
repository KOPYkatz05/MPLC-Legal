# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path


SPEC_DIR = Path(SPEC).resolve().parent
REPO_ROOT = SPEC_DIR.parent
sys.path.insert(0, str(SPEC_DIR))

from pyinstaller_common import SERVER_HIDDEN_IMPORTS, windows_version_info  # noqa: E402


hook_paths = [str(SPEC_DIR / "hooks")]


def server_analysis(entry_point, hiddenimports=()):
    return Analysis(
        [str(REPO_ROOT / entry_point)],
        pathex=[str(REPO_ROOT)],
        binaries=[],
        datas=[],
        hiddenimports=[*SERVER_HIDDEN_IMPORTS, *hiddenimports],
        hookspath=hook_paths,
        hooksconfig={},
        runtime_hooks=[],
        excludes=["paddle", "paddleocr"],
        noarchive=False,
        optimize=0,
    )


server_analysis_result = server_analysis("server_main.py")
setup_analysis = server_analysis("server_setup.py")
service_analysis = server_analysis(
    "windows_service.py",
    hiddenimports=["servicemanager", "win32event", "win32service"],
)

server_pyz = PYZ(server_analysis_result.pure)
server_exe = EXE(
    server_pyz,
    server_analysis_result.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegalServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Server",
        original_filename="MissionLegalServer.exe",
    ),
)
setup_pyz = PYZ(setup_analysis.pure)
setup_exe = EXE(
    setup_pyz,
    setup_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegalServerSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Server Setup",
        original_filename="MissionLegalServerSetup.exe",
    ),
)
service_pyz = PYZ(service_analysis.pure)
service_exe = EXE(
    service_pyz,
    service_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegalService",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Windows Service",
        original_filename="MissionLegalService.exe",
    ),
)

bundle = COLLECT(
    server_exe,
    setup_exe,
    service_exe,
    server_analysis_result.binaries,
    server_analysis_result.datas,
    setup_analysis.binaries,
    setup_analysis.datas,
    service_analysis.binaries,
    service_analysis.datas,
    strip=False,
    upx=False,
    name="MissionLegalServer",
)
