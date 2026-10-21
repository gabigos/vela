"""Entry point used by ``python main.py`` and PyInstaller builds."""

from __future__ import annotations

from vela.app import main

if __name__ == "__main__":
    raise SystemExit(main())
