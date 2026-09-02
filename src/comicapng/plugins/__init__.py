"""Versioned source-plugin support for ComicAPNG Desktop."""

from .api import (
    PLUGIN_API_VERSION,
    MaterializedChapter,
    PluginManifest,
    SourceChapter,
    SourceComic,
    SourcePage,
    SourceSearchPage,
    SourceSearchResult,
)
from .errors import PluginCallError, PluginError, PluginErrorCode, PluginOperationError

__all__ = [
    "PLUGIN_API_VERSION",
    "MaterializedChapter",
    "PluginCallError",
    "PluginError",
    "PluginErrorCode",
    "PluginManifest",
    "PluginOperationError",
    "SourceChapter",
    "SourceComic",
    "SourcePage",
    "SourceSearchPage",
    "SourceSearchResult",
]
