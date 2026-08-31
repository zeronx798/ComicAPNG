#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON_PATH="$PROJECT_ROOT/.venv/bin/python"
elif [ -x "$PROJECT_ROOT/.venv/Scripts/python.exe" ]; then
    PYTHON_PATH="$PROJECT_ROOT/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_PATH=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    PYTHON_PATH=$(command -v python)
else
    echo "Python 3.11 or newer was not found. Create .venv and install the project dependencies." >&2
    exit 1
fi

if ! "$PYTHON_PATH" -c 'import sys; assert sys.version_info >= (3, 11); import PIL, PySide6, platformdirs, qtawesome'; then
    echo "ComicAPNG dependencies are unavailable. Run: python -m pip install -e ." >&2
    exit 1
fi

PATH_SEPARATOR=$("$PYTHON_PATH" -c 'import os; print(os.pathsep)')
SOURCE_PATH="$PROJECT_ROOT/src"
if [ "$PATH_SEPARATOR" = ";" ] && command -v cygpath >/dev/null 2>&1; then
    SOURCE_PATH=$(cygpath -w "$SOURCE_PATH")
fi

if [ -n "${PYTHONPATH:-}" ]; then
    PYTHONPATH="$SOURCE_PATH$PATH_SEPARATOR$PYTHONPATH"
else
    PYTHONPATH="$SOURCE_PATH"
fi
export PYTHONPATH

if [ "${1:-}" = "--check" ]; then
    if ! "$PYTHON_PATH" -c 'import comicapng'; then
        echo "ComicAPNG could not be imported from the source tree." >&2
        exit 1
    fi
    echo "ComicAPNG source environment is ready."
    exit 0
fi

exec "$PYTHON_PATH" -m comicapng "$@"
