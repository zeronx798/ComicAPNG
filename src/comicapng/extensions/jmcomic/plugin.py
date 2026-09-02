"""Entrypoint for the official JMComic source extension."""

from __future__ import annotations

from .adapter import JMComicPlugin


def create_plugin() -> JMComicPlugin:
    return JMComicPlugin()
