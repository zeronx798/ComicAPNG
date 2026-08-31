"""Absolute-import entry point for PyInstaller analysis."""

from __future__ import annotations

import sys

from comicapng.app import main

if __name__ == "__main__":
    sys.exit(main())
