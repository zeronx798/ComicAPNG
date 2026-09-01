"""Inspect a PyInstaller package for required runtime resources."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

PLATFORM_PLUGIN_ROOTS = {
    "darwin": ("pyside6", "qt", "plugins", "platforms"),
    "linux": ("pyside6", "qt", "plugins", "platforms"),
    "win32": ("pyside6", "plugins", "platforms"),
}

# The native plugin makes the shipped GUI usable. The offscreen plugin is also
# required because every frozen CI smoke test explicitly selects that backend.
PLATFORM_PLUGIN_REQUIREMENTS = {
    "darwin": ("libqcocoa.dylib", "libqoffscreen.dylib"),
    "linux": ("libqxcb.so", "libqoffscreen.so"),
    "win32": ("qwindows.dll", "qoffscreen.dll"),
}

REQUIRED_RESOURCES = {
    "license",
    "notice",
    "comicapng/resources/i18n/en.json",
    "comicapng/resources/i18n/zh_cn.json",
    "comicapng/resources/icons/comicapng.png",
}


def _normalize_entry(name: str) -> str:
    normalized = name.replace("\\", "/").strip("/").casefold()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _normalized_entries(entries: Iterable[str]) -> set[str]:
    return {_normalize_entry(name) for name in entries}


def _plugin_root(platform_name: str) -> tuple[str, ...]:
    try:
        return PLATFORM_PLUGIN_ROOTS[platform_name]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported frozen validation platform: {platform_name}") from exc


def _is_plugin_path(name: str, platform_name: str, filename: str) -> bool:
    parts = tuple(_normalize_entry(name).split("/"))
    suffix = (*_plugin_root(platform_name), filename.casefold())
    return len(parts) >= len(suffix) and parts[-len(suffix) :] == suffix


def discovered_platform_plugins(entries: Iterable[str]) -> list[str]:
    """Return only entries located in a recognized PySide6 platform-plugin tree."""
    roots = tuple(PLATFORM_PLUGIN_ROOTS.values())
    discovered: set[str] = set()
    for name in entries:
        normalized = _normalize_entry(name)
        parts = tuple(normalized.split("/"))
        if any(
            len(parts) >= len(root) + 1 and parts[-len(root) - 1 : -1] == root
            for root in roots
        ):
            discovered.add(normalized)
    return sorted(discovered)


def validate_platform_plugins(entries: Iterable[str], platform_name: str) -> list[str]:
    """Require native and smoke-test Qt plugins under the platform's real layout."""
    names = _normalized_entries(entries)
    try:
        required_plugins = PLATFORM_PLUGIN_REQUIREMENTS[platform_name]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported frozen validation platform: {platform_name}") from exc

    missing = [
        filename
        for filename in required_plugins
        if not any(_is_plugin_path(name, platform_name, filename) for name in names)
    ]
    if missing:
        expected_root = "/".join(_plugin_root(platform_name))
        raise RuntimeError(
            "Frozen package is missing Qt platform plugins: "
            f"{', '.join(missing)} (expected under {expected_root})"
        )
    return discovered_platform_plugins(names)


def _executable(project_root: Path) -> Path:
    if sys.platform == "win32":
        return project_root / "dist/ComicAPNG.exe"
    if sys.platform == "darwin":
        return project_root / "dist/ComicAPNG.app/Contents/MacOS/ComicAPNG"
    return project_root / "dist/ComicAPNG"


def _bundle_entries(project_root: Path) -> set[str]:
    """Collect physical app-bundle files in addition to one-file archive entries."""
    if sys.platform != "darwin":
        return set()
    bundle_root = project_root / "dist/ComicAPNG.app"
    if not bundle_root.is_dir():
        return set()
    return {
        path.relative_to(project_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
    }


def _print_platform_plugins(entries: Iterable[str]) -> None:
    print("Detected Qt platform plugins:")
    detected = discovered_platform_plugins(entries)
    if not detected:
        print("- none")
        return
    for name in detected:
        print(f"- {name}")


def _validate_resources(entries: set[str]) -> None:
    missing = sorted(REQUIRED_RESOURCES - entries)
    if missing:
        raise RuntimeError(f"Frozen archive is missing resources: {', '.join(missing)}")
    if not any(name.startswith("qtawesome/fonts/") and name.endswith(".ttf") for name in entries):
        raise RuntimeError("Frozen archive is missing qtawesome fonts")
    if not any(
        name.startswith("qtawesome/fonts/") and "-charmap-" in name and name.endswith(".json")
        for name in entries
    ):
        raise RuntimeError("Frozen archive is missing qtawesome charmaps")


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    executable = _executable(project_root)
    if not executable.is_file():
        raise RuntimeError(f"Frozen executable was not found: {executable}")

    archive_entries = set(CArchiveReader(str(executable)).toc)
    all_entries = archive_entries | _bundle_entries(project_root)
    normalized_entries = _normalized_entries(all_entries)
    _print_platform_plugins(normalized_entries)
    validate_platform_plugins(normalized_entries, sys.platform)
    _validate_resources(normalized_entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
