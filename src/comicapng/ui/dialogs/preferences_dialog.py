"""Persistent application preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from comicapng.core.models import DEFAULT_BODY_DURATION_MS, DEFAULT_COVER_DURATION_MS
from comicapng.i18n import I18n
from comicapng.plugins.manager import PluginManager
from comicapng.services.settings import AppSettings
from comicapng.ui.theme import BACKGROUND
from comicapng.ui.widgets.duration_spin_box import DurationSpinBox


class PreferencesDialog(QDialog):
    def __init__(
        self,
        i18n: I18n,
        settings: AppSettings,
        parent=None,
        plugin_manager: PluginManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.settings = settings
        self.plugin_manager = plugin_manager
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

        plugins_heading = QLabel(i18n.tr("preferences.plugins"))
        plugins_heading.setObjectName("heading")
        root.addWidget(plugins_heading)
        self.plugin_table = QTableWidget(0, 4)
        self.plugin_table.setHorizontalHeaderLabels(
            [
                i18n.tr("preferences.plugin_enabled"),
                i18n.tr("preferences.plugin_name"),
                i18n.tr("preferences.plugin_version"),
                i18n.tr("preferences.plugin_status"),
            ]
        )
        self.plugin_table.verticalHeader().hide()
        self.plugin_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.plugin_table.setMinimumHeight(150)
        root.addWidget(self.plugin_table)
        if plugin_manager is not None:
            statuses = plugin_manager.statuses()
            self.plugin_table.setRowCount(len(statuses))
            for row, status in enumerate(statuses):
                enabled = QTableWidgetItem()
                enabled.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                )
                enabled.setCheckState(
                    Qt.CheckState.Checked if status.enabled else Qt.CheckState.Unchecked
                )
                enabled.setData(Qt.ItemDataRole.UserRole, status.manifest.plugin_id)
                name = QTableWidgetItem(status.manifest.name)
                version = QTableWidgetItem(status.manifest.version)
                availability = (
                    i18n.tr("preferences.plugin_available")
                    if status.available is True
                    else i18n.tr("preferences.plugin_unavailable")
                    if status.available is False
                    else i18n.tr("preferences.plugin_not_checked")
                )
                state = QTableWidgetItem(availability)
                for column, item in enumerate((enabled, name, version, state)):
                    if column:
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.plugin_table.setItem(row, column, item)

        self.jmcomic_include_cover = QCheckBox(i18n.tr("preferences.jmcomic_include_cover"))
        self.jmcomic_include_cover.setChecked(
            settings.boolean(
                "plugins/org.comicapng.source.jmcomic/include_cover",
                True,
            )
        )
        root.addWidget(self.jmcomic_include_cover)

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
        if self.plugin_manager is not None:
            for row in range(self.plugin_table.rowCount()):
                item = self.plugin_table.item(row, 0)
                plugin_id = str(item.data(Qt.ItemDataRole.UserRole))
                self.plugin_manager.set_enabled(
                    plugin_id,
                    item.checkState() == Qt.CheckState.Checked,
                )
        self.settings.set_value(
            "plugins/org.comicapng.source.jmcomic/include_cover",
            self.jmcomic_include_cover.isChecked(),
        )
        self.accept()
