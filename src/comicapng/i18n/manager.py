"""JSON-backed localization manager."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


class I18n:
    SUPPORTED_LOCALES = ("en", "zh_CN")

    def __init__(self, locale_name: str = "en") -> None:
        self.locale_name = self._select_locale(locale_name)
        self._fallback = self._load("en")
        self._messages = self._load(self.locale_name)

    @classmethod
    def _select_locale(cls, locale_name: str) -> str:
        normalized = locale_name.replace("-", "_")
        if normalized in cls.SUPPORTED_LOCALES:
            return normalized
        if normalized.casefold().startswith("zh"):
            return "zh_CN"
        return "en"

    @staticmethod
    def _load(locale_name: str) -> dict[str, str]:
        resource = files("comicapng.resources.i18n").joinpath(f"{locale_name}.json")
        with resource.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        return {str(key): str(text) for key, text in value.items()}

    def tr(self, key: str, **values: Any) -> str:
        template = self._messages.get(key, self._fallback.get(key, key))
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return template
