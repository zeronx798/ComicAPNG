"""Generate the platform bundle icon from the configured qtawesome glyph."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from comicapng.ui.icons import accent_icon  # noqa: E402

CANVAS_SIZE = 1024
GLYPH_SIZE = 820


def main() -> int:
    application = QApplication.instance() or QApplication([])
    canvas = QPixmap(CANVAS_SIZE, CANVAS_SIZE)
    canvas.fill(Qt.GlobalColor.transparent)
    glyph = accent_icon("book").pixmap(QSize(GLYPH_SIZE, GLYPH_SIZE))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    offset = (CANVAS_SIZE - GLYPH_SIZE) // 2
    painter.drawPixmap(offset, offset, glyph)
    painter.end()

    project_root = Path(__file__).resolve().parents[1]
    destination = project_root / "src/comicapng/resources/icons/ComicAPNG.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(destination), "PNG"):
        raise RuntimeError(f"Could not write application icon: {destination}")
    application.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
