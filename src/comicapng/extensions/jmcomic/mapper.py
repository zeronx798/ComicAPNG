"""Map public jmcomic entity attributes into ComicAPNG-owned DTOs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from comicapng.plugins.api import SourceChapter, SourceComic, SourceSearchPage, SourceSearchResult

PLUGIN_ID = "org.comicapng.source.jmcomic"


def _attribute(value: object, name: str, default: Any = None) -> Any:
    try:
        result = getattr(value, name, default)
    except Exception:
        return default
    return default if result is None else result


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        candidates: Iterable[object] = value.split(",") if "," in value else value.split()
    elif isinstance(value, Iterable):
        candidates = value
    else:
        candidates = (value,)
    return tuple(text for item in candidates if (text := _text(item)))


def map_search_page(upstream_page: object, requested_page: int) -> SourceSearchPage:
    iterator = _attribute(upstream_page, "iter_id_title_tag")
    if not callable(iterator):
        raise ValueError("JMComic search result does not expose iter_id_title_tag")
    items = tuple(
        SourceSearchResult(
            plugin_id=PLUGIN_ID,
            source_id=_text(album_id),
            title=_text(title) or _text(album_id),
            tags=_list(tags),
            cover_ref=f"jmcomic:album-cover:{_text(album_id)}",
        )
        for album_id, title, tags in iterator()
    )
    page_number = _attribute(upstream_page, "page_number", requested_page)
    page_count = _attribute(upstream_page, "page_count", 0)
    total = _attribute(upstream_page, "total", len(items))
    return SourceSearchPage(
        page=max(1, int(page_number or requested_page)),
        page_count=max(0, int(page_count or 0)),
        total=max(0, int(total or 0)),
        items=items,
    )


def map_album(upstream_album: object) -> SourceComic:
    album_id = _text(_attribute(upstream_album, "album_id", _attribute(upstream_album, "id")))
    if not album_id:
        raise ValueError("JMComic album has no source ID")
    authors = _list(_attribute(upstream_album, "authors"))
    if not authors:
        authors = _list(_attribute(upstream_album, "author"))
    try:
        chapter_count = len(upstream_album)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        chapter_count = 0
    extra = {
        key: value
        for key in ("page_count", "likes", "views")
        if (value := _text(_attribute(upstream_album, key)))
    }
    return SourceComic(
        plugin_id=PLUGIN_ID,
        source_id=album_id,
        title=_text(_attribute(upstream_album, "name")) or album_id,
        authors=authors,
        description=_text(_attribute(upstream_album, "description")) or None,
        tags=_list(_attribute(upstream_album, "tags")),
        chapter_count=max(0, int(chapter_count)),
        cover_ref=f"jmcomic:album-cover:{album_id}",
        source_ref=None,
        extra=extra,
    )


def map_chapters(upstream_album: object) -> tuple[SourceChapter, ...]:
    album_id = _text(_attribute(upstream_album, "album_id", _attribute(upstream_album, "id")))
    if not album_id:
        raise ValueError("JMComic album has no source ID")
    try:
        upstream_chapters = iter(upstream_album)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("JMComic album does not expose chapters") from exc
    chapters: list[SourceChapter] = []
    for sequence, upstream in enumerate(upstream_chapters, 1):
        chapter_id = _text(_attribute(upstream, "photo_id", _attribute(upstream, "id")))
        if not chapter_id:
            raise ValueError("JMComic chapter has no source ID")
        chapters.append(
            SourceChapter(
                plugin_id=PLUGIN_ID,
                source_id=chapter_id,
                comic_id=album_id,
                title=_text(_attribute(upstream, "name")) or chapter_id,
                index=sequence,
            )
        )
    return tuple(chapters)
