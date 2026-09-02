"""Centralized mature icon-library access."""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtGui import QIcon

from .theme import ACCENT, DANGER, TEXT, TEXT_MUTED

ICON_NAMES = {
    "about": "fa5s.info-circle",
    "actual_size": "fa5s.search",
    "add": "fa5s.plus",
    "book": "fa5s.book-open",
    "cancel": "fa5s.times",
    "cover": "fa5s.star",
    "create": "fa5s.layer-group",
    "delete": "fa5s.trash-alt",
    "direction": "fa5s.exchange-alt",
    "dual_page": "fa5s.columns",
    "export": "fa5s.file-export",
    "extract": "fa5s.box-open",
    "file": "fa5s.file-image",
    "fit_page": "fa5s.expand",
    "fit_width": "fa5s.arrows-alt-h",
    "folder": "fa5s.folder-open",
    "fullscreen": "fa5s.expand-arrows-alt",
    "image": "fa5s.images",
    "metadata": "fa5s.tags",
    "move_bottom": "fa5s.angle-double-down",
    "move_down": "fa5s.arrow-down",
    "move_top": "fa5s.angle-double-up",
    "move_up": "fa5s.arrow-up",
    "next": "fa5s.chevron-right",
    "open": "fa5s.folder-open",
    "previous": "fa5s.chevron-left",
    "read": "fa5s.book-reader",
    "settings": "fa5s.cog",
    "search": "fa5s.search",
    "single_page": "fa5s.file",
    "sources": "fa5s.globe",
    "zoom_in": "fa5s.search-plus",
    "zoom_out": "fa5s.search-minus",
}


def icon(name: str, *, color: str = TEXT) -> QIcon:
    return qta.icon(ICON_NAMES[name], color=color)


def muted_icon(name: str) -> QIcon:
    return icon(name, color=TEXT_MUTED)


def accent_icon(name: str) -> QIcon:
    return icon(name, color=ACCENT)


def danger_icon(name: str) -> QIcon:
    return icon(name, color=DANGER)
