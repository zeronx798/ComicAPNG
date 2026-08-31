#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_PATH="$PROJECT_ROOT/.venv/bin/python"

cd "$PROJECT_ROOT"
"$PYTHON_PATH" -m pip install -e "$PROJECT_ROOT[dev]"
"$PYTHON_PATH" -m pytest
"$PYTHON_PATH" "$PROJECT_ROOT/scripts/check_source_ascii.py"
"$PYTHON_PATH" -m ruff check .
"$PYTHON_PATH" "$PROJECT_ROOT/scripts/validate_packaging.py"
"$PYTHON_PATH" -m PyInstaller --clean --noconfirm "$PROJECT_ROOT/ComicAPNG.spec"
"$PYTHON_PATH" "$PROJECT_ROOT/scripts/validate_frozen_archive.py"

if [ "$(uname -s)" = "Darwin" ]; then
    FROZEN_APP="$PROJECT_ROOT/dist/ComicAPNG.app/Contents/MacOS/ComicAPNG"
else
    FROZEN_APP="$PROJECT_ROOT/dist/ComicAPNG"
fi
QT_QPA_PLATFORM=offscreen "$FROZEN_APP" --packaging-smoke-test
