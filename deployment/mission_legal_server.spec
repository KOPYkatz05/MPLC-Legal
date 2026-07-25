# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path


SPEC_DIR = Path(SPEC).resolve().parent
REPO_ROOT = SPEC_DIR.parent
sys.path.insert(0, str(SPEC_DIR))

from pyinstaller_common import (  # noqa: E402
    SERVER_HIDDEN_IMPORTS,
    application_datas,
    windows_version_info,
)


hook_paths = [str(SPEC_DIR / "hooks")]


def server_analysis(
    entry_point,
    hiddenimports=(),
    datas=(),
    *,
    include_server_hidden_imports=True,
):
    role_hidden_imports = (
        list(SERVER_HIDDEN_IMPORTS)
        if include_server_hidden_imports
        else []
    )
    return Analysis(
        [str(REPO_ROOT / entry_point)],
        pathex=[str(REPO_ROOT)],
        binaries=[],
        datas=list(datas),
        hiddenimports=[*role_hidden_imports, *hiddenimports],
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
    hiddenimports=[
        "servicemanager",
        "server.management",
        "server.management_pipe",
        "win32event",
        "win32file",
        "win32pipe",
        "win32security",
        "win32service",
    ],
)
manager_analysis = server_analysis(
    "server_manager.py",
    include_server_hidden_imports=False,
    hiddenimports=[
        "PySide6.QtNetwork",
        "PySide6.QtWidgets",
        "iconipy",
        "qfluentwidgets",
        "services.pairing_package",
        "services.server_update_service",
        "ui.server_manager_window",
        "win32file",
        "win32pipe",
        "win32security",
        "win32service",
    ],
    datas=[
        *application_datas(REPO_ROOT),
        (str(REPO_ROOT / "deployment" / "server_release.json"), "."),
        (
            str(
                REPO_ROOT
                / "assets"
                / "icons"
                / "server_manager"
                / "server_manager_icon_256.png"
            ),
            "assets/icons/server_manager",
        ),
        (
            str(
                REPO_ROOT
                / "assets"
                / "icons"
                / "server_manager"
                / "server_manager_tray_64.png"
            ),
            "assets/icons/server_manager",
        ),
        (
            str(
                REPO_ROOT
                / "assets"
                / "icons"
                / "server_manager"
                / "server_manager_icon.ico"
            ),
            "assets/icons/server_manager",
        ),
    ],
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
manager_pyz = PYZ(manager_analysis.pure)
manager_exe = EXE(
    manager_pyz,
    manager_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MissionLegalServerManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(
        REPO_ROOT
        / "assets"
        / "icons"
        / "server_manager"
        / "server_manager_icon.ico"
    ),
    version=windows_version_info(
        REPO_ROOT,
        description="Mission Legal Server Manager",
        original_filename="MissionLegalServerManager.exe",
    ),
)

bundle = COLLECT(
    server_exe,
    setup_exe,
    service_exe,
    manager_exe,
    server_analysis_result.binaries,
    server_analysis_result.datas,
    setup_analysis.binaries,
    setup_analysis.datas,
    service_analysis.binaries,
    service_analysis.datas,
    manager_analysis.binaries,
    manager_analysis.datas,
    strip=False,
    upx=False,
    name="MissionLegalServer",
)
