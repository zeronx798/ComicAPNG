"""Editors and viewers for independent EXIF and PNG text metadata."""

from __future__ import annotations

import copy
import json

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from comicapng.core.exceptions import InvalidMetadataError
from comicapng.core.metadata import (
    PRIVATE_METADATA_KEY,
    STANDARD_EXIF_TAGS,
    serialize_exif,
    validate_text_fields,
)
from comicapng.core.models import ComicMetadata, ExifValue
from comicapng.i18n import I18n
from comicapng.ui.icons import danger_icon, icon


class MetadataEditorDialog(QDialog):
    def __init__(self, i18n: I18n, metadata: ComicMetadata, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self._private_metadata = dict(metadata.private_metadata)
        self._source_metadata = copy.deepcopy(metadata.source)
        self.result_metadata = metadata
        self.setWindowTitle(i18n.tr("metadata.title"))
        self.resize(760, 600)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        tabs.addTab(self._build_exif_tab(metadata), i18n.tr("metadata.exif"))
        tabs.addTab(self._build_text_tab(metadata), i18n.tr("metadata.png_text"))
        tabs.addTab(self._build_source_tab(metadata), i18n.tr("metadata.source_information"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.tr("common.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.tr("common.cancel"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_exif_tab(self, metadata: ComicMetadata) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        standard_group = QGroupBox(self.i18n.tr("metadata.standard_fields"))
        standard_layout = QFormLayout(standard_group)
        self.standard_edits: dict[int, QLineEdit] = {}
        for name, tag_id in STANDARD_EXIF_TAGS.items():
            edit = QLineEdit()
            field = metadata.exif_fields.get(tag_id)
            if field is not None:
                edit.setText(field.value)
            edit.setMaxLength(65535)
            edit.setAccessibleName(self.i18n.tr(f"metadata.standard.{name}"))
            standard_layout.addRow(self.i18n.tr(f"metadata.standard.{name}"), edit)
            self.standard_edits[tag_id] = edit
        layout.addWidget(standard_group)

        custom_group = QGroupBox(self.i18n.tr("metadata.custom_exif"))
        custom_layout = QVBoxLayout(custom_group)
        self.exif_table = QTableWidget(0, 3)
        self.exif_table.setHorizontalHeaderLabels(
            [
                self.i18n.tr("metadata.tag_id"),
                self.i18n.tr("metadata.value_type"),
                self.i18n.tr("metadata.value"),
            ]
        )
        self.exif_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        custom_layout.addWidget(self.exif_table)
        controls = QHBoxLayout()
        add_button = QPushButton(icon("add"), self.i18n.tr("common.add"))
        remove_button = QPushButton(danger_icon("delete"), self.i18n.tr("common.remove"))
        add_button.clicked.connect(self._add_exif_row)
        remove_button.clicked.connect(lambda: self._remove_selected_rows(self.exif_table))
        controls.addWidget(add_button)
        controls.addWidget(remove_button)
        controls.addStretch()
        custom_layout.addLayout(controls)
        layout.addWidget(custom_group, 1)
        for tag_id, field in metadata.exif_fields.items():
            if tag_id not in STANDARD_EXIF_TAGS.values():
                self._add_exif_row(tag_id, field)
        return tab

    def _build_text_tab(self, metadata: ComicMetadata) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        info = QLabel(self.i18n.tr("metadata.png_text_help"))
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)
        self.text_table = QTableWidget(0, 2)
        self.text_table.setHorizontalHeaderLabels(
            [self.i18n.tr("metadata.key"), self.i18n.tr("metadata.value")]
        )
        self.text_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.text_table, 1)
        controls = QHBoxLayout()
        add_button = QPushButton(icon("add"), self.i18n.tr("common.add"))
        remove_button = QPushButton(danger_icon("delete"), self.i18n.tr("common.remove"))
        add_button.clicked.connect(self._add_text_row)
        remove_button.clicked.connect(lambda: self._remove_selected_rows(self.text_table))
        controls.addWidget(add_button)
        controls.addWidget(remove_button)
        controls.addStretch()
        layout.addLayout(controls)
        for key, value in metadata.text_fields.items():
            self._add_text_row(key, value)
        return tab

    def _build_source_tab(self, metadata: ComicMetadata) -> QWidget:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(
            json.dumps(metadata.source.to_dict(), ensure_ascii=False, indent=2)
            if metadata.source is not None
            else self.i18n.tr("metadata.none")
        )
        return view

    def _type_combo(self, selected: str = "text") -> QComboBox:
        combo = QComboBox()
        for value_type in ("text", "integer", "rational", "bytes"):
            combo.addItem(self.i18n.tr(f"metadata.type.{value_type}"), value_type)
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        return combo

    def _add_exif_row(self, tag_id: int | None = None, field: ExifValue | None = None) -> None:
        row = self.exif_table.rowCount()
        self.exif_table.insertRow(row)
        self.exif_table.setItem(row, 0, QTableWidgetItem("" if tag_id is None else str(tag_id)))
        combo = self._type_combo(field.value_type if field else "text")
        self.exif_table.setCellWidget(row, 1, combo)
        self.exif_table.setItem(row, 2, QTableWidgetItem(field.value if field else ""))

    def _add_text_row(self, key: str = "", value: str = "") -> None:
        row = self.text_table.rowCount()
        self.text_table.insertRow(row)
        self.text_table.setItem(row, 0, QTableWidgetItem(key))
        self.text_table.setItem(row, 1, QTableWidgetItem(value))

    @staticmethod
    def _remove_selected_rows(table: QTableWidget) -> None:
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    @staticmethod
    def _item_text(
        table: QTableWidget,
        row: int,
        column: int,
        *,
        strip: bool = False,
    ) -> str:
        item = table.item(row, column)
        if item is None:
            return ""
        return item.text().strip() if strip else item.text()

    def _collect_exif(self) -> dict[int, ExifValue]:
        result: dict[int, ExifValue] = {}
        for tag_id, edit in self.standard_edits.items():
            if edit.text():
                result[tag_id] = ExifValue("text", edit.text())
        for row in range(self.exif_table.rowCount()):
            tag_text = self._item_text(self.exif_table, row, 0, strip=True)
            value = self._item_text(self.exif_table, row, 2)
            if not tag_text and not value:
                continue
            try:
                tag_id = int(tag_text, 10)
            except ValueError as exc:
                raise InvalidMetadataError("EXIF tag ID must be an integer") from exc
            if tag_id in result:
                raise InvalidMetadataError("EXIF tag IDs must be unique")
            combo = self.exif_table.cellWidget(row, 1)
            value_type = str(combo.currentData()) if isinstance(combo, QComboBox) else "text"
            result[tag_id] = ExifValue(value_type, value)  # type: ignore[arg-type]
        serialize_exif(result)
        return result

    def _collect_text(self) -> dict[str, str]:
        result: dict[str, str] = {}
        folded_keys: set[str] = set()
        for row in range(self.text_table.rowCount()):
            key = self._item_text(self.text_table, row, 0, strip=True)
            value = self._item_text(self.text_table, row, 1)
            if not key and not value:
                continue
            if key == PRIVATE_METADATA_KEY:
                raise InvalidMetadataError("The ComicAPNG metadata key is reserved")
            folded = key.casefold()
            if folded in folded_keys:
                raise InvalidMetadataError("PNG text keys must be unique")
            folded_keys.add(folded)
            result[key] = value
        validate_text_fields(result)
        return result

    def _save(self) -> None:
        try:
            self.result_metadata = ComicMetadata(
                exif_fields=self._collect_exif(),
                text_fields=self._collect_text(),
                private_metadata=self._private_metadata,
                source=self._source_metadata,
            )
        except InvalidMetadataError as exc:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(self.i18n.tr("metadata.invalid_title"))
            box.setText(self.i18n.tr("metadata.invalid_message"))
            box.setDetailedText(str(exc))
            box.exec()
            return
        self.accept()


class MetadataViewerDialog(QDialog):
    def __init__(self, i18n: I18n, metadata: ComicMetadata, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("metadata.title"))
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        exif_view = QPlainTextEdit()
        exif_view.setReadOnly(True)
        exif_view.setPlainText(
            "\n".join(
                f"{tag_id}: {field.value}" for tag_id, field in sorted(metadata.exif_fields.items())
            )
            or i18n.tr("metadata.none")
        )
        tabs.addTab(exif_view, i18n.tr("metadata.exif"))

        text_view = QPlainTextEdit()
        text_view.setReadOnly(True)
        text_view.setPlainText(
            "\n".join(f"{key}: {value}" for key, value in metadata.text_fields.items())
            or i18n.tr("metadata.none")
        )
        tabs.addTab(text_view, i18n.tr("metadata.png_text"))

        private_view = QPlainTextEdit()
        private_view.setReadOnly(True)
        private_view.setPlainText(
            json.dumps(metadata.private_metadata, ensure_ascii=False, indent=2)
            if metadata.private_metadata
            else i18n.tr("metadata.none")
        )
        tabs.addTab(private_view, i18n.tr("metadata.private"))

        source_view = QPlainTextEdit()
        source_view.setReadOnly(True)
        source_view.setPlainText(
            json.dumps(metadata.source.to_dict(), ensure_ascii=False, indent=2)
            if metadata.source is not None
            else i18n.tr("metadata.none")
        )
        tabs.addTab(source_view, i18n.tr("metadata.source_information"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(i18n.tr("common.close"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
