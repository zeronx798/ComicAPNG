"""Public-API adapter for jmcomic 2.7.x."""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from types import ModuleType
from typing import Any

from comicapng.plugins.api import (
    MaterializedChapter,
    SourceChapter,
    SourceComic,
    SourcePage,
    SourceSearchPage,
)
from comicapng.plugins.errors import PluginError, PluginErrorCode, PluginOperationError
from comicapng.plugins.validation import validate_materialized_chapter, validate_materialized_file

from .mapper import PLUGIN_ID, map_album, map_chapters, map_search_page

LOGGER = logging.getLogger(__name__)


class JMComicPlugin:
    plugin_id = PLUGIN_ID

    def __init__(self, backend: ModuleType | Any | None = None) -> None:
        self._backend = backend
        self._client: Any | None = None
        self._albums: dict[str, Any] = {}

    def health(self) -> dict[str, Any]:
        injected_backend = self._backend is not None
        try:
            self._backend_module()
            version = (
                getattr(self._backend, "__version__", "test")
                if injected_backend
                else importlib.metadata.version("jmcomic")
            )
        except PluginOperationError as exc:
            return {
                "available": False,
                "message": "The jmcomic dependency is unavailable",
                "dependency_version": None,
                "error_code": PluginErrorCode.DEPENDENCY_UNAVAILABLE.value,
                "technical_type": exc.error.details,
            }
        return {
            "available": True,
            "message": "JMComic source is ready",
            "dependency_version": str(version),
        }

    def search(self, query: str, page: int) -> SourceSearchPage:
        try:
            upstream = self._get_client().search_site(search_query=query, page=page)
            return map_search_page(upstream, page)
        except Exception as exc:
            raise self._translate_exception(exc, "search") from exc

    def get_comic(self, source_id: str) -> SourceComic:
        try:
            album = self._get_client().get_album_detail(source_id)
            comic = map_album(album)
            self._albums[comic.source_id] = album
            return comic
        except Exception as exc:
            raise self._translate_exception(exc, "comic details") from exc

    def get_chapters(self, comic_id: str) -> tuple[SourceChapter, ...]:
        try:
            album = self._albums.get(comic_id)
            if album is None:
                album = self._get_client().get_album_detail(comic_id)
                self._albums[comic_id] = album
            return map_chapters(album)
        except Exception as exc:
            raise self._translate_exception(exc, "chapters") from exc

    def materialize_cover(
        self,
        comic_id: str,
        destination: Path,
        *,
        task_id: str,
        cancel_event: Event,
    ) -> Path:
        del task_id
        self._check_cancel(cancel_event)
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        cover_path = (destination / "cover.jpg").resolve()
        try:
            self._get_client().download_album_cover(comic_id, str(cover_path))
            self._check_cancel(cancel_event)
            return validate_materialized_file(cover_path, destination)
        except PluginOperationError:
            raise
        except Exception as exc:
            raise self._translate_exception(exc, "album cover") from exc

    def materialize_chapter(
        self,
        chapter: SourceChapter,
        destination: Path,
        *,
        include_cover: bool,
        task_id: str,
        cancel_event: Event,
        progress,
    ) -> MaterializedChapter:
        self._check_cancel(cancel_event)
        backend = self._backend_module()
        destination = Path(destination).resolve()
        try:
            option = backend.JmOption.construct(
                {
                    "log": True,
                    "dir_rule": {"base_dir": str(destination), "rule": "Bd_Pname"},
                    "download": {"threading": {"photo": 1}},
                }
            )
            task_context = getattr(backend, "jm_task_context", None)
            context = task_context(task_id=task_id) if callable(task_context) else nullcontext()
            progress(0, 1)
            with context:
                result = backend.download_photo(chapter.source_id, option=option)
            self._check_cancel(cancel_event)
            downloader = getattr(result, "downloader", None)
            if downloader is not None and (
                getattr(downloader, "download_failed_image", None)
                or getattr(downloader, "download_failed_photo", None)
            ):
                raise PluginOperationError(
                    PluginError(
                        PluginErrorCode.PARTIAL_DOWNLOAD,
                        "JMComic reported a partial chapter download",
                    )
                )
            manifest = getattr(result, "manifest", None)
            paths = getattr(manifest, "image_filepath_list", None)
            if not isinstance(paths, (list, tuple)):
                raise PluginOperationError(
                    PluginError(
                        PluginErrorCode.INVALID_SOURCE_DATA,
                        "JMComic did not return a download manifest",
                    )
                )
            pages = tuple(
                SourcePage(
                    plugin_id=PLUGIN_ID,
                    source_id=f"{chapter.source_id}:{index}",
                    chapter_id=chapter.source_id,
                    index=index,
                    local_path=Path(path).resolve(),
                )
                for index, path in enumerate(paths, 1)
            )
            cover_path = None
            if include_cover:
                self._check_cancel(cancel_event)
                cover_path = self.materialize_cover(
                    chapter.comic_id,
                    destination,
                    task_id=task_id,
                    cancel_event=cancel_event,
                )
            progress(1, 1)
            materialized = MaterializedChapter(
                chapter=chapter,
                pages=pages,
                cover_path=cover_path,
                metadata={"jmcomic_download_duration": getattr(result, "duration", None)},
            )
            return validate_materialized_chapter(materialized, destination)
        except PluginOperationError:
            raise
        except Exception as exc:
            raise self._translate_exception(exc, "chapter download") from exc

    def _backend_module(self):
        if self._backend is None:
            try:
                self._backend = importlib.import_module("jmcomic")
            except (ImportError, ModuleNotFoundError) as exc:
                raise PluginOperationError(
                    PluginError(
                        PluginErrorCode.DEPENDENCY_UNAVAILABLE,
                        "The jmcomic dependency could not be imported",
                        type(exc).__name__,
                    )
                ) from exc
            upstream_logger = logging.getLogger("jmcomic")
            upstream_logger.handlers.clear()
            upstream_logger.propagate = True
        return self._backend

    def _get_client(self):
        if self._client is None:
            backend = self._backend_module()
            option = backend.JmOption.construct(
                {"log": True, "download": {"threading": {"photo": 1}}}
            )
            self._client = option.new_jm_client()
        return self._client

    @staticmethod
    def _check_cancel(cancel_event: Event) -> None:
        if cancel_event.is_set():
            raise PluginOperationError(
                PluginError(PluginErrorCode.CANCELLED, "JMComic materialization was cancelled")
            )

    @staticmethod
    def _translate_exception(exc: Exception, operation: str) -> PluginOperationError:
        if isinstance(exc, PluginOperationError):
            return exc
        class_name = type(exc).__name__
        if class_name == "PartialDownloadFailedException":
            code = PluginErrorCode.PARTIAL_DOWNLOAD
            message = "JMComic reported a partial download"
        elif class_name == "MissingAlbumPhotoException":
            code = PluginErrorCode.NOT_FOUND
            message = "The requested JMComic item was not found"
        elif class_name in {
            "RequestRetryAllFailException",
            "ConnectionError",
            "ConnectError",
            "Timeout",
            "TimeoutError",
        }:
            code = PluginErrorCode.NETWORK_ERROR
            message = "JMComic could not reach the source service"
        elif isinstance(exc, (OSError, ValueError)) and operation == "chapter download":
            code = PluginErrorCode.PARTIAL_DOWNLOAD
            message = "JMComic could not materialize a complete readable chapter"
        else:
            code = PluginErrorCode.SOURCE_UNAVAILABLE
            message = f"JMComic could not complete {operation}"
        LOGGER.exception("JMComic operation failed: %s", operation)
        return PluginOperationError(
            PluginError(code, message, class_name, code == PluginErrorCode.NETWORK_ERROR)
        )
