"""Plugin API v1 manifest and DTO tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from comicapng.plugins.api import PLUGIN_API_VERSION, PluginManifest, SourceSearchPage
from comicapng.plugins.discovery import discover_plugins, load_manifest


def test_bundled_manifests_are_valid_and_api_v1() -> None:
    discovered = discover_plugins()
    by_id = {item.manifest.plugin_id: item for item in discovered}
    assert set(by_id) == {
        "org.comicapng.source.jmcomic",
        "org.comicapng.source.test",
    }
    assert all(item.compatible for item in discovered)
    assert all(item.manifest.api_version == PLUGIN_API_VERSION for item in discovered)
    assert by_id["org.comicapng.source.jmcomic"].manifest.version == "0.1.0"
    assert by_id["org.comicapng.source.jmcomic"].manifest.official


def test_manifest_rejects_arbitrary_or_unknown_capabilities(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "id": "org.example.bad",
                "name": "Bad",
                "version": "1.0.0",
                "api_version": 1,
                "entrypoint": "example.plugin:create",
                "capabilities": ["invoke_anything"],
            }
        ),
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="unknown capabilities"):
        load_manifest(path)


def test_manifest_and_search_page_round_trip() -> None:
    manifest = PluginManifest.from_dict(
        {
            "id": "org.example.source",
            "name": "Example",
            "version": "1.2.3",
            "api_version": 1,
            "entrypoint": "example.plugin:create",
            "capabilities": ["search"],
            "official": False,
        }
    )
    assert PluginManifest.from_dict(manifest.to_dict()) == manifest
    page = SourceSearchPage.from_dict(
        {
            "page": 2,
            "page_count": 3,
            "total": 21,
            "items": [
                {
                    "plugin_id": manifest.plugin_id,
                    "source_id": "7",
                    "title": "Result",
                    "tags": ["one", "two"],
                }
            ],
        }
    )
    assert SourceSearchPage.from_dict(page.to_dict()) == page
