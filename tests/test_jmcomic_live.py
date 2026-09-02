"""Opt-in live JMComic integration check excluded from normal CI."""

from __future__ import annotations

import os

import pytest

from comicapng.extensions.jmcomic.adapter import JMComicPlugin


@pytest.mark.skipif(
    os.environ.get("COMICAPNG_RUN_LIVE_SOURCE_TESTS") != "1",
    reason="Live source tests are opt-in",
)
def test_live_jmcomic_search() -> None:
    page = JMComicPlugin().search("1", 1)
    assert page.page == 1
