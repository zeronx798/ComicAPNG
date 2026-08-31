"""Persistent application preferences."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from comicapng.core.models import DEFAULT_BODY_DURATION_MS, DEFAULT_COVER_DURATION_MS
from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.ui.theme import BACKGROUND
from comicapng.ui.widgets.duration_spin_box import DurationSpinBox


class PreferencesDialog(QDialog):
    def __init__(self, i18n: I18n, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.settings = settings
        self.setWindowTitle(i18n.tr("preferences.title"))
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.background_edit = QLineEdit(str(settings.value("reader/background", BACKGROUND)))
        self.background_edit.setMaxLength(32)
        background_help = QLabel(i18n.tr("preferences.background_help"))
        background_help.setObjectName("muted")
        background_help.setWordWrap(True)
        background_layout = QVBoxLayout()
        background_layout.addWidget(self.background_edit)
        background_layout.addWidget(background_help)
        form.addRow(i18n.tr("preferences.reader_background"), background_layout)

        self.thumbnail_size = QSpinBox()
        self.thumbnail_size.setRange(96, 260)
        self.thumbnail_size.setSuffix(i18n.tr("common.px_suffix"))
        self.thumbnail_size.setValue(settings.integer("creator/thumbnail_size", 170))
        form.addRow(i18n.tr("preferences.thumbnail_size"), self.thumbnail_size)

        self.cache_pages = QSpinBox()
        self.cache_pages.setRange(3, 9)
        self.cache_pages.setValue(settings.integer("reader/cache_pages", 5))
        form.addRow(i18n.tr("preferences.cache_pages"), self.cache_pages)

        self.cover_duration = DurationSpinBox()
        self.cover_duration.set_milliseconds(
            settings.integer("creator/cover_duration", DEFAULT_COVER_DURATION_MS)
        )
        self.cover_duration_unit = QLabel(i18n.tr("common.seconds_unit"))
        cover_duration_layout = QHBoxLayout()
        cover_duration_layout.addWidget(self.cover_duration)
        cover_duration_layout.addWidget(self.cover_duration_unit)
        cover_duration_layout.addStretch()
        form.addRow(i18n.tr("preferences.default_cover_duration"), cover_duration_layout)

        self.body_duration = DurationSpinBox()
        self.body_duration.set_milliseconds(
            settings.integer("creator/body_duration", DEFAULT_BODY_DURATION_MS)
        )
        self.body_duration_unit = QLabel(i18n.tr("common.seconds_unit"))
        body_duration_layout = QHBoxLayout()
        body_duration_layout.addWidget(self.body_duration)
        body_duration_layout.addWidget(self.body_duration_unit)
        body_duration_layout.addStretch()
        form.addRow(i18n.tr("preferences.default_body_duration"), body_duration_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.tr("common.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.tr("common.cancel"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self) -> None:
        color = QColor(self.background_edit.text().strip())
        if not color.isValid():
            QMessageBox.warning(
                self,
                self.i18n.tr("preferences.invalid_color_title"),
                self.i18n.tr("preferences.invalid_color_message"),
            )
            return
        self.settings.set_value("reader/background", color.name())
        self.settings.set_value("creator/thumbnail_size", self.thumbnail_size.value())
        self.settings.set_value("reader/cache_pages", self.cache_pages.value())
        self.settings.set_value("creator/cover_duration", self.cover_duration.milliseconds())
        self.settings.set_value("creator/body_duration", self.body_duration.milliseconds())
        self.accept()
