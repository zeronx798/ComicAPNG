"""Validate resources required by native ComicAPNG packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import qtawesome
from PIL import Image
from PySide6.QtCore import QLibraryInfo


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    resource_root = project_root / "src/comicapng/resources"
    icon_path = resource_root / "icons/ComicAPNG.png"
    _require(icon_path.is_file(), f"Missing application icon: {icon_path}")
    with Image.open(icon_path) as image:
        _require(image.format == "PNG", "Application icon must be a PNG")
        _require(image.size == (1024, 1024), "Application icon must be 1024 x 1024")
        _require("A" in image.getbands(), "Application icon must preserve transparency")

    locale_keys: set[str] | None = None
    for locale_name in ("en", "zh_CN"):
        locale_path = resource_root / f"i18n/{locale_name}.json"
        _require(locale_path.is_file(), f"Missing locale: {locale_name}")
        values = json.loads(locale_path.read_text(encoding="utf-8"))
        _require(isinstance(values, dict) and bool(values), f"Invalid locale: {locale_name}")
        keys = set(values)
        if locale_keys is None:
            locale_keys = keys
        else:
            _require(keys == locale_keys, f"Locale keys differ: {locale_name}")

    qtawesome_root = Path(qtawesome.__file__).resolve().parent
    font_root = qtawesome_root / "fonts"
    _require(any(font_root.glob("*.ttf")), "qtawesome font files are unavailable")
    _require(any(font_root.glob("*-charmap-*.json")), "qtawesome charmaps are unavailable")

    plugin_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    platform_root = plugin_root / "platforms"
    plugin_names = {
        "darwin": ("libqcocoa.dylib", "libqoffscreen.dylib"),
        "linux": ("libqxcb.so", "libqoffscreen.so"),
        "win32": ("qwindows.dll", "qoffscreen.dll"),
    }
    required_plugins = plugin_names.get(sys.platform)
    _require(required_plugins is not None, f"Unsupported packaging platform: {sys.platform}")
    for plugin_name in required_plugins:
        _require((platform_root / plugin_name).is_file(), f"Missing Qt plugin: {plugin_name}")

    for filename in ("LICENSE", "NOTICE", "ComicAPNG.spec"):
        _require((project_root / filename).is_file(), f"Missing packaging file: {filename}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
