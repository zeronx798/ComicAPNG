"""Installed-plugin state and typed access to the Plugin Host."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

from comicapng.services.settings import AppSettings

from .api import MaterializedChapter, PluginManifest, SourceChapter, SourceComic, SourceSearchPage
from .client import PluginHostClient, ProgressCallback
from .discovery import DiscoveredPlugin, discover_plugins
from .errors import PluginCallError, PluginError, PluginErrorCode


@dataclass(frozen=True, slots=True)
class PluginStatus:
    manifest: PluginManifest
    enabled: bool
    available: bool | None
    message: str
    dependency_version: str | None = None


class PluginManager:
    def __init__(
        self,
        settings: AppSettings,
        host_client: PluginHostClient | None = None,
    ) -> None:
        self.settings = settings
        self.host_client = host_client or PluginHostClient()
        self.discovered: dict[str, DiscoveredPlugin] = {
            item.manifest.plugin_id: item for item in discover_plugins()
        }
        self.health_cache: dict[str, PluginStatus] = {}

    def is_enabled(self, plugin_id: str) -> bool:
        return self.settings.boolean(f"plugins/{plugin_id}/enabled", True)

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        self._descriptor(plugin_id)
        self.settings.set_value(f"plugins/{plugin_id}/enabled", enabled)
        self.health_cache.pop(plugin_id, None)

    def statuses(self) -> tuple[PluginStatus, ...]:
        result: list[PluginStatus] = []
        for plugin_id, descriptor in self.discovered.items():
            cached = self.health_cache.get(plugin_id)
            if cached is not None:
                result.append(cached)
                continue
            enabled = self.is_enabled(plugin_id)
            if not descriptor.compatible:
                result.append(
                    PluginStatus(
                        descriptor.manifest,
                        enabled,
                        False,
                        descriptor.validation_error or "Incompatible Plugin API",
                    )
                )
            elif not enabled:
                result.append(PluginStatus(descriptor.manifest, False, False, "Disabled"))
            else:
                result.append(PluginStatus(descriptor.manifest, True, None, "Not checked"))
        return tuple(result)

    def health(self, plugin_id: str) -> PluginStatus:
        descriptor = self._descriptor(plugin_id)
        enabled = self.is_enabled(plugin_id)
        if not descriptor.compatible:
            status = PluginStatus(
                descriptor.manifest,
                enabled,
                False,
                descriptor.validation_error or "Incompatible Plugin API",
            )
        elif not enabled:
            status = PluginStatus(descriptor.manifest, False, False, "Disabled")
        else:
            try:
                result = self.host_client.request(
                    "plugin.health",
                    {"plugin_id": plugin_id},
                    timeout=30.0,
                )
                if not isinstance(result, dict):
                    raise ValueError("Health response must be an object")
                status = PluginStatus(
                    descriptor.manifest,
                    True,
                    bool(result.get("available", False)),
                    str(result.get("message", "")),
                    str(result["dependency_version"])
                    if result.get("dependency_version") is not None
                    else None,
                )
            except (PluginCallError, ValueError) as exc:
                message = exc.error.message if isinstance(exc, PluginCallError) else str(exc)
                status = PluginStatus(descriptor.manifest, True, False, message)
        self.health_cache[plugin_id] = status
        return status

    def search(
        self,
        plugin_id: str,
        query: str,
        page: int,
        *,
        cancel_event: Event | None = None,
    ) -> SourceSearchPage:
        self._require_available_for_call(plugin_id)
        result = self.host_client.request(
            "source.search",
            {"plugin_id": plugin_id, "query": query, "page": page},
            cancel_event=cancel_event,
        )
        return SourceSearchPage.from_dict(result)

    def get_comic(
        self,
        plugin_id: str,
        source_id: str,
        *,
        cancel_event: Event | None = None,
    ) -> SourceComic:
        self._require_available_for_call(plugin_id)
        result = self.host_client.request(
            "source.get_comic",
            {"plugin_id": plugin_id, "source_id": source_id},
            cancel_event=cancel_event,
        )
        return SourceComic.from_dict(result)

    def get_chapters(
        self,
        plugin_id: str,
        comic_id: str,
        *,
        cancel_event: Event | None = None,
    ) -> tuple[SourceChapter, ...]:
        self._require_available_for_call(plugin_id)
        result = self.host_client.request(
            "source.get_chapters",
            {"plugin_id": plugin_id, "comic_id": comic_id},
            cancel_event=cancel_event,
        )
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise PluginCallError(
                PluginError(
                    PluginErrorCode.INVALID_SOURCE_DATA,
                    "The source returned an invalid chapter list",
                )
            )
        return tuple(SourceChapter.from_dict(item) for item in result["items"])

    def materialize_chapter(
        self,
        chapter: SourceChapter,
        destination: Path,
        *,
        include_cover: bool,
        task_id: str,
        cancel_event: Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> MaterializedChapter:
        self._require_available_for_call(chapter.plugin_id)
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        result = self.host_client.request(
            "source.materialize_chapter",
            {
                "plugin_id": chapter.plugin_id,
                "chapter": chapter.to_dict(),
                "destination": str(destination),
                "include_cover": include_cover,
                "task_id": task_id,
            },
            cancel_event=cancel_event,
            progress=progress,
            timeout=None,
        )
        return MaterializedChapter.from_dict(result)

    def materialize_cover(
        self,
        plugin_id: str,
        comic_id: str,
        destination: Path,
        *,
        task_id: str,
        cancel_event: Event | None = None,
    ) -> Path:
        self._require_available_for_call(plugin_id)
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        result = self.host_client.request(
            "source.materialize_cover",
            {
                "plugin_id": plugin_id,
                "comic_id": comic_id,
                "destination": str(destination),
                "task_id": task_id,
            },
            cancel_event=cancel_event,
        )
        if not isinstance(result, dict) or not isinstance(result.get("local_path"), str):
            raise PluginCallError(
                PluginError(
                    PluginErrorCode.INVALID_SOURCE_DATA,
                    "The source returned an invalid cover result",
                )
            )
        return Path(result["local_path"])

    def _descriptor(self, plugin_id: str) -> DiscoveredPlugin:
        try:
            return self.discovered[plugin_id]
        except KeyError as exc:
            raise PluginCallError(
                PluginError(PluginErrorCode.NOT_FOUND, "The requested plugin is not installed")
            ) from exc

    def _require_available_for_call(self, plugin_id: str) -> None:
        descriptor = self._descriptor(plugin_id)
        if not descriptor.compatible:
            raise PluginCallError(
                PluginError(
                    PluginErrorCode.INCOMPATIBLE_API,
                    descriptor.validation_error or "The plugin API is incompatible",
                )
            )
        if not self.is_enabled(plugin_id):
            raise PluginCallError(
                PluginError(PluginErrorCode.SOURCE_UNAVAILABLE, "The source plugin is disabled")
            )

    def close(self) -> None:
        self.host_client.close()
