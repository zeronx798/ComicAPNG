"""ComicAPNG-owned data transfer objects for Plugin API v1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

PLUGIN_API_VERSION = 1
SOURCE_CAPABILITIES = frozenset(
    {"search", "comic_details", "chapters", "materialize_pages"}
)
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _string(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    result = value.strip()
    if not result and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    result = _string(value, field_name, allow_empty=True)
    return result or None


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for item in value:
        text = _string(item, field_name, allow_empty=True)
        if text:
            result.append(text)
    return tuple(result)


def _integer(value: object, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if result < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return result


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} must be an object with string keys")
    return dict(value)


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Validated metadata used to discover and launch one source plugin."""

    plugin_id: str
    name: str
    version: str
    api_version: int
    entrypoint: str
    capabilities: tuple[str, ...]
    official: bool = False

    @classmethod
    def from_dict(cls, value: object) -> PluginManifest:
        data = _mapping(value, "manifest")
        plugin_id = _string(data.get("id"), "manifest.id")
        if PLUGIN_ID_PATTERN.fullmatch(plugin_id) is None:
            raise ValueError("manifest.id has an invalid format")
        version = _string(data.get("version"), "manifest.version")
        if VERSION_PATTERN.fullmatch(version) is None:
            raise ValueError("manifest.version must use major.minor.patch")
        entrypoint = _string(data.get("entrypoint"), "manifest.entrypoint")
        if entrypoint.count(":") != 1:
            raise ValueError("manifest.entrypoint must use module:factory")
        module_name, factory_name = entrypoint.split(":", 1)
        if not module_name or not factory_name or not factory_name.isidentifier():
            raise ValueError("manifest.entrypoint has an invalid format")
        capabilities = _strings(data.get("capabilities"), "manifest.capabilities")
        if not capabilities:
            raise ValueError("manifest.capabilities must not be empty")
        unknown = set(capabilities) - SOURCE_CAPABILITIES
        if unknown:
            raise ValueError(f"manifest has unknown capabilities: {', '.join(sorted(unknown))}")
        official = data.get("official", False)
        if not isinstance(official, bool):
            raise ValueError("manifest.official must be a boolean")
        return cls(
            plugin_id=plugin_id,
            name=_string(data.get("name"), "manifest.name"),
            version=version,
            api_version=_integer(data.get("api_version"), "manifest.api_version", minimum=1),
            entrypoint=entrypoint,
            capabilities=capabilities,
            official=official,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "entrypoint": self.entrypoint,
            "capabilities": list(self.capabilities),
            "official": self.official,
        }


@dataclass(frozen=True, slots=True)
class SourceSearchResult:
    plugin_id: str
    source_id: str
    title: str
    tags: tuple[str, ...] = ()
    cover_ref: str | None = None
    summary: str | None = None
    source_ref: str | None = None

    @classmethod
    def from_dict(cls, value: object) -> SourceSearchResult:
        data = _mapping(value, "search result")
        return cls(
            plugin_id=_string(data.get("plugin_id"), "plugin_id"),
            source_id=_string(data.get("source_id"), "source_id"),
            title=_string(data.get("title"), "title"),
            tags=_strings(data.get("tags"), "tags"),
            cover_ref=_optional_string(data.get("cover_ref"), "cover_ref"),
            summary=_optional_string(data.get("summary"), "summary"),
            source_ref=_optional_string(data.get("source_ref"), "source_ref"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "source_id": self.source_id,
            "title": self.title,
            "tags": list(self.tags),
            "cover_ref": self.cover_ref,
            "summary": self.summary,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class SourceSearchPage:
    page: int
    page_count: int
    total: int
    items: tuple[SourceSearchResult, ...] = ()

    @classmethod
    def from_dict(cls, value: object) -> SourceSearchPage:
        data = _mapping(value, "search page")
        raw_items = data.get("items", [])
        if not isinstance(raw_items, list):
            raise ValueError("items must be a list")
        return cls(
            page=_integer(data.get("page"), "page", minimum=1),
            page_count=_integer(data.get("page_count"), "page_count", minimum=0),
            total=_integer(data.get("total"), "total", minimum=0),
            items=tuple(SourceSearchResult.from_dict(item) for item in raw_items),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "page_count": self.page_count,
            "total": self.total,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class SourceComic:
    plugin_id: str
    source_id: str
    title: str
    authors: tuple[str, ...] = ()
    description: str | None = None
    tags: tuple[str, ...] = ()
    chapter_count: int = 0
    cover_ref: str | None = None
    source_ref: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: object) -> SourceComic:
        data = _mapping(value, "comic")
        return cls(
            plugin_id=_string(data.get("plugin_id"), "plugin_id"),
            source_id=_string(data.get("source_id"), "source_id"),
            title=_string(data.get("title"), "title"),
            authors=_strings(data.get("authors"), "authors"),
            description=_optional_string(data.get("description"), "description"),
            tags=_strings(data.get("tags"), "tags"),
            chapter_count=_integer(data.get("chapter_count", 0), "chapter_count"),
            cover_ref=_optional_string(data.get("cover_ref"), "cover_ref"),
            source_ref=_optional_string(data.get("source_ref"), "source_ref"),
            extra=_mapping(data.get("extra"), "extra"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "source_id": self.source_id,
            "title": self.title,
            "authors": list(self.authors),
            "description": self.description,
            "tags": list(self.tags),
            "chapter_count": self.chapter_count,
            "cover_ref": self.cover_ref,
            "source_ref": self.source_ref,
            "extra": dict(self.extra),
        }


@dataclass(frozen=True, slots=True)
class SourceChapter:
    plugin_id: str
    source_id: str
    comic_id: str
    title: str
    index: int

    @classmethod
    def from_dict(cls, value: object) -> SourceChapter:
        data = _mapping(value, "chapter")
        return cls(
            plugin_id=_string(data.get("plugin_id"), "plugin_id"),
            source_id=_string(data.get("source_id"), "source_id"),
            comic_id=_string(data.get("comic_id"), "comic_id"),
            title=_string(data.get("title"), "title"),
            index=_integer(data.get("index"), "index", minimum=1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "source_id": self.source_id,
            "comic_id": self.comic_id,
            "title": self.title,
            "index": self.index,
        }


@dataclass(frozen=True, slots=True)
class SourcePage:
    plugin_id: str
    source_id: str
    chapter_id: str
    index: int
    local_path: Path
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: object) -> SourcePage:
        data = _mapping(value, "page")
        return cls(
            plugin_id=_string(data.get("plugin_id"), "plugin_id"),
            source_id=_string(data.get("source_id"), "source_id"),
            chapter_id=_string(data.get("chapter_id"), "chapter_id"),
            index=_integer(data.get("index"), "index", minimum=1),
            local_path=Path(_string(data.get("local_path"), "local_path")),
            metadata=_mapping(data.get("metadata"), "metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "source_id": self.source_id,
            "chapter_id": self.chapter_id,
            "index": self.index,
            "local_path": str(self.local_path),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class MaterializedChapter:
    chapter: SourceChapter
    pages: tuple[SourcePage, ...]
    cover_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: object) -> MaterializedChapter:
        data = _mapping(value, "materialized chapter")
        raw_pages = data.get("pages", [])
        if not isinstance(raw_pages, list):
            raise ValueError("pages must be a list")
        cover = _optional_string(data.get("cover_path"), "cover_path")
        return cls(
            chapter=SourceChapter.from_dict(data.get("chapter")),
            pages=tuple(SourcePage.from_dict(page) for page in raw_pages),
            cover_path=Path(cover) if cover else None,
            metadata=_mapping(data.get("metadata"), "metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter": self.chapter.to_dict(),
            "pages": [page.to_dict() for page in self.pages],
            "cover_path": str(self.cover_path) if self.cover_path is not None else None,
            "metadata": dict(self.metadata),
        }


class SourcePlugin(Protocol):
    """The only plugin surface exposed by Plugin API v1."""

    plugin_id: str

    def health(self) -> dict[str, Any]: ...

    def search(self, query: str, page: int) -> SourceSearchPage: ...

    def get_comic(self, source_id: str) -> SourceComic: ...

    def get_chapters(self, comic_id: str) -> tuple[SourceChapter, ...]: ...

    def materialize_cover(
        self,
        comic_id: str,
        destination: Path,
        *,
        task_id: str,
        cancel_event: Any,
    ) -> Path: ...

    def materialize_chapter(
        self,
        chapter: SourceChapter,
        destination: Path,
        *,
        include_cover: bool,
        task_id: str,
        cancel_event: Any,
        progress: Any,
    ) -> MaterializedChapter: ...
