"""Manifest discovery without importing plugin implementation modules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .api import PLUGIN_API_VERSION, PluginManifest


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    manifest: PluginManifest
    manifest_path: Path
    compatible: bool
    validation_error: str | None = None


def load_manifest(path: Path) -> PluginManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read plugin manifest {path}: {exc}") from exc
    return PluginManifest.from_dict(value)


def _bundled_manifest_paths() -> list[Path]:
    root = files("comicapng.extensions")
    paths: list[Path] = []
    for child in root.iterdir():
        manifest = child.joinpath("manifest.json")
        if manifest.is_file():
            paths.append(Path(str(manifest)))
    return sorted(paths)


def discover_plugins(extra_roots: tuple[Path, ...] = ()) -> tuple[DiscoveredPlugin, ...]:
    paths = _bundled_manifest_paths()
    for root in extra_roots:
        if root.is_dir():
            paths.extend(sorted(root.glob("*/manifest.json")))

    discovered: list[DiscoveredPlugin] = []
    seen: set[str] = set()
    for path in paths:
        try:
            manifest = load_manifest(path)
            if manifest.plugin_id in seen:
                raise ValueError(f"Duplicate plugin ID: {manifest.plugin_id}")
            seen.add(manifest.plugin_id)
            compatible = manifest.api_version == PLUGIN_API_VERSION
            error = None if compatible else (
                f"Plugin API {manifest.api_version} is not supported by API {PLUGIN_API_VERSION}"
            )
            discovered.append(DiscoveredPlugin(manifest, path, compatible, error))
        except ValueError as exc:
            placeholder = PluginManifest(
                plugin_id=f"invalid.{len(discovered) + 1}",
                name=path.parent.name or "Invalid plugin",
                version="0.0.0",
                api_version=PLUGIN_API_VERSION,
                entrypoint="invalid.plugin:create",
                capabilities=("search",),
            )
            discovered.append(DiscoveredPlugin(placeholder, path, False, str(exc)))
    return tuple(discovered)
