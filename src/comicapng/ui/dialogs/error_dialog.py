"""Localized error dialog helpers."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from comicapng.i18n import I18n


def show_error(
    parent: QWidget,
    i18n: I18n,
    title_key: str,
    message_key: str,
    details: str = "",
) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(i18n.tr(title_key))
    box.setText(i18n.tr(message_key))
    if details:
        box.setDetailedText(details)
    box.exec()
