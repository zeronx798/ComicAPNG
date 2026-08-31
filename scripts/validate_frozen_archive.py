"""Inspect a PyInstaller executable for required runtime resources."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def _executable(project_root: Path) -> Path:
    if sys.platform == "win32":
        return project_root / "dist/ComicAPNG.exe"
    if sys.platform == "darwin":
        return project_root / "dist/ComicAPNG.app/Contents/MacOS/ComicAPNG"
    return project_root / "dist/ComicAPNG"


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    executable = _executable(project_root)
    if not executable.is_file():
        raise RuntimeError(f"Frozen executable was not found: {executable}")

    names = {
        name.replace("\\", "/").casefold()
        for name in CArchiveReader(str(executable)).toc
    }
    platform_plugins = {
        "darwin": ("libqcocoa.dylib", "libqoffscreen.dylib"),
        "linux": ("libqxcb.so", "libqoffscreen.so"),
        "win32": ("qwindows.dll", "qoffscreen.dll"),
    }
    required = {
        "license",
        "notice",
        "comicapng/resources/i18n/en.json",
        "comicapng/resources/i18n/zh_cn.json",
        "comicapng/resources/icons/comicapng.png",
    }
    required.update(
        f"pyside6/plugins/platforms/{filename}"
        for filename in platform_plugins[sys.platform]
    )
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"Frozen archive is missing resources: {', '.join(missing)}")
    if not any(name.startswith("qtawesome/fonts/") and name.endswith(".ttf") for name in names):
        raise RuntimeError("Frozen archive is missing qtawesome fonts")
    if not any(
        name.startswith("qtawesome/fonts/") and "-charmap-" in name and name.endswith(".json")
        for name in names
    ):
        raise RuntimeError("Frozen archive is missing qtawesome charmaps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
