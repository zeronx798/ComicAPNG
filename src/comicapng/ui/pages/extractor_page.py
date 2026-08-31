"""Extract APNG comic workflow."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from comicapng.core.apng_reader import ApngDocument
from comicapng.core.extractor import extract_apng
from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.ui.dialogs.error_dialog import show_error
from comicapng.ui.dialogs.metadata_dialog import MetadataViewerDialog
from comicapng.ui.icons import icon
from comicapng.ui.workers import Worker


class ExtractorPage(QWidget):
    status_message = Signal(str)

    def __init__(self, i18n: I18n, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.settings = settings
        self.thread_pool = QThreadPool.globalInstance()
        self.document: ApngDocument | None = None
        self._active_worker: Worker | None = None
        self._progress_dialog: QProgressDialog | None = None
        self.setAcceptDrops(True)
        self._build_ui()
        self._update_actions()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 22, 30, 22)
        root.setSpacing(16)
        heading = QLabel(self.i18n.tr("extractor.title"))
        heading.setObjectName("heading")
        root.addWidget(heading)

        panel = QFrame()
        panel.setObjectName("panel")
        form = QFormLayout(panel)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(12)

        source_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setReadOnly(True)
        self.source_edit.setPlaceholderText(self.i18n.tr("extractor.source_placeholder"))
        source_button = QPushButton(icon("open"), self.i18n.tr("extractor.choose_source"))
        source_button.clicked.connect(self._choose_source)
        source_row.addWidget(self.source_edit, 1)
        source_row.addWidget(source_button)
        form.addRow(self.i18n.tr("extractor.input"), source_row)

        self.type_value = QLabel(self.i18n.tr("common.not_available"))
        self.frames_value = QLabel(self.i18n.tr("common.not_available"))
        self.canvas_value = QLabel(self.i18n.tr("common.not_available"))
        self.metadata_value = QLabel(self.i18n.tr("common.not_available"))
        self.metadata_value.setWordWrap(True)
        form.addRow(self.i18n.tr("extractor.file_type"), self.type_value)
        form.addRow(self.i18n.tr("extractor.frame_count"), self.frames_value)
        form.addRow(self.i18n.tr("extractor.canvas_size"), self.canvas_value)
        form.addRow(self.i18n.tr("extractor.metadata_summary"), self.metadata_value)

        self.metadata_button = QPushButton(icon("metadata"), self.i18n.tr("metadata.view"))
        self.metadata_button.clicked.connect(self._view_metadata)
        form.addRow("", self.metadata_button)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText(self.i18n.tr("extractor.output_placeholder"))
        self.output_edit.textChanged.connect(self._update_actions)
        output_button = QPushButton(icon("folder"), self.i18n.tr("extractor.choose_output"))
        output_button.clicked.connect(self._choose_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(output_button)
        form.addRow(self.i18n.tr("extractor.output"), output_row)

        self.restore_bounds = QCheckBox(self.i18n.tr("extractor.restore_bounds"))
        self.restore_bounds.setToolTip(self.i18n.tr("extractor.restore_bounds_help"))
        self.overwrite = QCheckBox(self.i18n.tr("common.allow_overwrite"))
        options = QHBoxLayout()
        options.addWidget(self.restore_bounds)
        options.addWidget(self.overwrite)
        options.addStretch()
        form.addRow(self.i18n.tr("extractor.options"), options)

        self.extract_button = QPushButton(icon("extract"), self.i18n.tr("extractor.extract"))
        self.extract_button.setObjectName("primary")
        self.extract_button.clicked.connect(self._start_extraction)
        form.addRow("", self.extract_button)
        root.addWidget(panel)

        help_label = QLabel(self.i18n.tr("extractor.drop_help"))
        help_label.setObjectName("muted")
        help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(help_label)
        root.addStretch()

    def _choose_source(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            self.i18n.tr("extractor.choose_source"),
            str(self.settings.last_directory("extractor_input")),
            self.i18n.tr("files.apng_filter"),
        )
        if selected:
            self.set_input(Path(selected))

    def set_input(self, path: Path) -> None:
        try:
            document = ApngDocument(path)
        except Exception as exc:
            show_error(
                self,
                self.i18n,
                "extractor.open_error_title",
                "extractor.open_error",
                str(exc),
            )
            return
        self.document = document
        self.source_edit.setText(str(path))
        self.settings.set_last_directory("extractor_input", path)
        self.type_value.setText(
            self.i18n.tr("extractor.type_apng")
            if document.info.is_animated
            else self.i18n.tr("extractor.type_static")
        )
        self.frames_value.setText(str(document.info.frame_count))
        self.canvas_value.setText(
            self.i18n.tr(
                "extractor.dimensions",
                width=document.info.canvas_size[0],
                height=document.info.canvas_size[1],
            )
        )
        metadata = document.info.metadata
        self.metadata_value.setText(
            self.i18n.tr(
                "extractor.metadata_counts",
                exif=len(metadata.exif_fields),
                text=len(metadata.text_fields),
                private=self.i18n.tr("common.yes")
                if metadata.private_metadata
                else self.i18n.tr("common.no"),
            )
        )
        if not self.output_edit.text():
            self.output_edit.setText(str(path.parent / f"{path.stem}_pages"))
        self._update_actions()

    def _choose_output(self) -> None:
        start = self.output_edit.text() or str(self.settings.last_directory("extractor_output"))
        selected = QFileDialog.getExistingDirectory(
            self,
            self.i18n.tr("extractor.choose_output"),
            start,
        )
        if selected:
            self.output_edit.setText(selected)
            self.settings.set_last_directory("extractor_output", Path(selected))
            self._update_actions()

    def _view_metadata(self) -> None:
        if self.document is None:
            return
        MetadataViewerDialog(self.i18n, self.document.info.metadata, self).exec()

    def _start_extraction(self) -> None:
        if self.document is None or self._active_worker is not None:
            return
        output_text = self.output_edit.text().strip()
        if not output_text:
            return
        source = self.document.path
        output = Path(output_text)
        overwrite = self.overwrite.isChecked()
        restore_bounds = self.restore_bounds.isChecked()
        self.settings.set_last_directory("extractor_output", output)

        def task(cancel_event: Event, progress):
            return extract_apng(
                source,
                output,
                overwrite=overwrite,
                restore_original_bounds=restore_bounds,
                progress=progress,
                cancel_event=cancel_event,
            )

        worker = Worker(task)
        self._active_worker = worker
        dialog = QProgressDialog(
            self.i18n.tr("extractor.extracting"),
            self.i18n.tr("common.cancel"),
            0,
            self.document.info.frame_count,
            self,
        )
        dialog.setWindowTitle(self.i18n.tr("extractor.extracting"))
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(worker.cancel)
        worker.signals.progress.connect(
            lambda current, total: self._update_progress(dialog, current, total)
        )
        worker.signals.result.connect(self._extraction_complete)
        worker.signals.error.connect(self._worker_error)
        worker.signals.canceled.connect(
            lambda: self.status_message.emit(self.i18n.tr("common.cancelled"))
        )
        worker.signals.finished.connect(self._operation_finished)
        self._progress_dialog = dialog
        self._update_actions()
        dialog.show()
        self.thread_pool.start(worker)

    def _update_progress(self, dialog: QProgressDialog, current: int, total: int) -> None:
        dialog.setValue(current)
        dialog.setLabelText(self.i18n.tr("extractor.progress", current=current, total=total))

    def _extraction_complete(self, result: object) -> None:
        paths = result  # type: ignore[assignment]
        output = Path(self.output_edit.text())
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(self.i18n.tr("extractor.complete_title"))
        box.setText(self.i18n.tr("extractor.complete", count=len(paths), path=str(output)))
        box.exec()
        self.status_message.emit(
            self.i18n.tr("extractor.complete", count=len(paths), path=str(output))
        )

    def _worker_error(self, _error_type: str, details: str) -> None:
        show_error(self, self.i18n, "common.error_title", "common.operation_failed", details)

    def _operation_finished(self) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
        self._progress_dialog = None
        self._active_worker = None
        self._update_actions()

    def _update_actions(self) -> None:
        self.metadata_button.setEnabled(self.document is not None)
        self.extract_button.setEnabled(
            self.document is not None
            and bool(self.output_edit.text().strip())
            and self._active_worker is None
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.set_input(paths[0])
            event.acceptProposedAction()
            return
        super().dropEvent(event)
