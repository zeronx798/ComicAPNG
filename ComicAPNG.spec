# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

project_root = Path(SPECPATH)
with (project_root / "pyproject.toml").open("rb") as stream:
    app_version = tomllib.load(stream)["project"]["version"]

app_icon = project_root / "src/comicapng/resources/icons/ComicAPNG.png"
codesign_identity = os.environ.get("COMICAPNG_CODESIGN_IDENTITY") or None
entitlements_file = os.environ.get("COMICAPNG_ENTITLEMENTS_FILE") or None
qtawesome_datas = collect_data_files("qtawesome")
package_datas = collect_data_files("comicapng")
jmcomic_datas, jmcomic_binaries, jmcomic_hiddenimports = collect_all("jmcomic")
curl_cffi_datas, curl_cffi_binaries, curl_cffi_hiddenimports = collect_all("curl_cffi")
extension_hiddenimports = collect_submodules("comicapng.extensions")
jmcomic_metadata = copy_metadata("jmcomic")
legal_datas = [
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "NOTICE"), "."),
    (str(project_root / "third-party/jmcomic-LICENSE.txt"), "third-party"),
]

analysis = Analysis(
    [str(project_root / "src/comicapng/_pyinstaller_entry.py")],
    pathex=[str(project_root / "src")],
    binaries=jmcomic_binaries + curl_cffi_binaries,
    datas=(
        qtawesome_datas
        + package_datas
        + jmcomic_datas
        + curl_cffi_datas
        + jmcomic_metadata
        + legal_datas
    ),
    hiddenimports=jmcomic_hiddenimports + curl_cffi_hiddenimports + extension_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ComicAPNG",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=codesign_identity,
    entitlements_file=entitlements_file,
    icon=str(app_icon),
)

if sys.platform == "darwin":
    application = BUNDLE(
        executable,
        name="ComicAPNG.app",
        icon=str(app_icon),
        bundle_identifier="org.comicapng.ComicAPNG",
        version=app_version,
        info_plist={
            "CFBundleDisplayName": "ComicAPNG",
            "CFBundleName": "ComicAPNG",
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
        },
    )
