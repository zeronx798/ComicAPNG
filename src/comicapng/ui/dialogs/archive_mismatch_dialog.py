"""Review and recovery choices for untrusted ZIP page bindings."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from comicapng.core.zip_archive import ArchiveDifferences
from comicapng.i18n import I18n
from comicapng.ui.icons import icon


class ArchiveMismatchChoice(StrEnum):
    REMAINING_METADATA = "remaining_metadata"
    IMAGES_ONLY = "images_only"
    CANCEL = "cancel"


class ArchiveMismatchDialog(QDialog):
    def __init__(self, i18n: I18n, differences: ArchiveDifferences, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.choice = ArchiveMismatchChoice.CANCEL
        self.setWindowTitle(i18n.tr("archive.mismatch_title"))
        self.resize(680, 520)

        layout = QVBoxLayout(self)
        message = QLabel(i18n.tr("archive.mismatch_message"))
        message.setWordWrap(True)
        layout.addWidget(message)

        self.review_button = QPushButton(
            icon("metadata"),
            i18n.tr("archive.review_differences"),
        )
        self.review_button.setObjectName("archive_review_differences")
        self.review_button.clicked.connect(self._toggle_details)
        layout.addWidget(self.review_button)

        self.details = QPlainTextEdit()
        self.details.setObjectName("archive_difference_details")
        self.details.setReadOnly(True)
        self.details.setPlainText(self._difference_text(differences))
        self.details.setVisible(False)
        layout.addWidget(self.details, 1)

        buttons = QDialogButtonBox()
        self.remaining_button = buttons.addButton(
            i18n.tr("archive.import_remaining_metadata"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.images_button = buttons.addButton(
            i18n.tr("archive.import_without_metadata"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.cancel_button = buttons.addButton(
            i18n.tr("common.cancel"),
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.remaining_button.setObjectName("archive_import_remaining_metadata")
        self.images_button.setObjectName("archive_import_without_metadata")
        self.cancel_button.setObjectName("archive_cancel_import")
        self.remaining_button.clicked.connect(
            lambda: self._accept_choice(ArchiveMismatchChoice.REMAINING_METADATA)
        )
        self.images_button.clicked.connect(
            lambda: self._accept_choice(ArchiveMismatchChoice.IMAGES_ONLY)
        )
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _difference_text(self, differences: ArchiveDifferences) -> str:
        sections = (
            ("archive.found_images", differences.found),
            ("archive.metadata_references", differences.referenced),
            ("archive.missing_images", differences.missing),
            ("archive.unexpected_images", differences.unexpected),
            ("archive.invalid_references", differences.invalid_references),
        )
        blocks: list[str] = []
        for key, values in sections:
            body = "\n".join(values) if values else self.i18n.tr("metadata.none")
            blocks.append(f"{self.i18n.tr(key)}\n{body}")
        return "\n\n".join(blocks)

    def _toggle_details(self) -> None:
        self.details.setVisible(not self.details.isVisible())

    def _accept_choice(self, choice: ArchiveMismatchChoice) -> None:
        self.choice = choice
        self.accept()
