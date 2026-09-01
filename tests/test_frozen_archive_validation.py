"""Platform-aware Qt plugin path validation tests."""

from __future__ import annotations

import pytest

from scripts.validate_frozen_archive import (
    discovered_platform_plugins,
    validate_platform_plugins,
)


@pytest.mark.parametrize(
    ("platform_name", "entries"),
    [
        (
            "win32",
            {
                "PySide6/plugins/platforms/qwindows.dll",
                "PySide6/plugins/platforms/qoffscreen.dll",
            },
        ),
        (
            "linux",
            {
                "PySide6/Qt/plugins/platforms/libqxcb.so",
                "PySide6/Qt/plugins/platforms/libqoffscreen.so",
            },
        ),
        (
            "darwin",
            {
                "dist/ComicAPNG.app/Contents/Frameworks/"
                "PySide6/Qt/plugins/platforms/libqcocoa.dylib",
                "dist/ComicAPNG.app/Contents/Frameworks/"
                "PySide6/Qt/plugins/platforms/libqoffscreen.dylib",
            },
        ),
    ],
)
def test_correct_platform_plugin_paths_pass(
    platform_name: str,
    entries: set[str],
) -> None:
    assert validate_platform_plugins(entries, platform_name)


def test_macos_onefile_archive_paths_pass_without_bundle_prefix() -> None:
    entries = {
        "PySide6/Qt/plugins/platforms/libqcocoa.dylib",
        "PySide6/Qt/plugins/platforms/libqoffscreen.dylib",
    }
    assert validate_platform_plugins(entries, "darwin") == [
        "pyside6/qt/plugins/platforms/libqcocoa.dylib",
        "pyside6/qt/plugins/platforms/libqoffscreen.dylib",
    ]


def test_plugin_in_wrong_directory_fails() -> None:
    entries = {
        "PySide6/Qt/lib/libqcocoa.dylib",
        "PySide6/Qt/plugins/platforms/libqoffscreen.dylib",
    }
    with pytest.raises(RuntimeError, match="libqcocoa.dylib"):
        validate_platform_plugins(entries, "darwin")


def test_missing_required_platform_plugin_fails() -> None:
    with pytest.raises(RuntimeError, match="libqoffscreen.so"):
        validate_platform_plugins(
            {"PySide6/Qt/plugins/platforms/libqxcb.so"},
            "linux",
        )


def test_arbitrary_matching_basename_is_not_accepted_or_reported() -> None:
    entries = {
        "unrelated/libqcocoa.dylib",
        "PySide6/Qt/plugins/platforms/libqoffscreen.dylib",
    }
    assert discovered_platform_plugins(entries) == [
        "pyside6/qt/plugins/platforms/libqoffscreen.dylib"
    ]
    with pytest.raises(RuntimeError, match="libqcocoa.dylib"):
        validate_platform_plugins(entries, "darwin")


def test_plugin_path_matching_is_case_insensitive() -> None:
    entries = {
        "PYSIDE6/PLUGINS/PLATFORMS/QWINDOWS.DLL",
        "PYSIDE6/PLUGINS/PLATFORMS/QOFFSCREEN.DLL",
    }
    assert validate_platform_plugins(entries, "win32")
