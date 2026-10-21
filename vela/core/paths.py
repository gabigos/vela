from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def app_root() -> Path:
    """Directory of the executable (frozen) or the repository root (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def resource_root() -> Path:
    """Directory that contains bundled resources (assets, ffmpeg)."""
    bundle = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and bundle:
        return Path(bundle)
    return app_root()


def _standard_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "Vela"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Vela"
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "vela"


class AppPaths:
    """Filesystem layout for application data.

    All mutable user data lives outside the repository by default, in the
    platform's standard application-data directory. A ``portable.flag`` file
    next to the executable (or repository root) switches to a local ``data``
    directory instead, which is useful for USB sticks and testing.
    """

    def __init__(self, data_root: Path | None = None) -> None:
        self.portable = (app_root() / "portable.flag").exists()
        if data_root is not None:
            self.data_dir = Path(data_root).expanduser().resolve()
            self.portable = False
        elif self.portable:
            self.data_dir = app_root() / "data"
        else:
            self.data_dir = _standard_data_dir()

        self.logs_dir = self.data_dir / "logs"
        self.cache_dir = self.data_dir / "cache"
        self.thumbnails_dir = self.cache_dir / "thumbnails"
        self.ytdlp_cache_dir = self.cache_dir / "yt-dlp"
        self.settings_file = self.data_dir / "settings.json"
        self.history_file = self.data_dir / "history.sqlite3"
        self.queue_file = self.data_dir / "queue.json"
        self.log_file = self.logs_dir / "vela.log"

    def ensure(self) -> None:
        for directory in (
            self.data_dir,
            self.logs_dir,
            self.cache_dir,
            self.thumbnails_dir,
            self.ytdlp_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def fallback(self) -> "AppPaths":
        """Return session-only paths in the temp directory (last resort)."""
        fallback_root = Path(tempfile.gettempdir()) / "Vela"
        paths = AppPaths(fallback_root)
        paths.portable = False
        return paths

    def as_dict(self) -> dict[str, str]:
        return {
            "data": str(self.data_dir),
            "logs": str(self.logs_dir),
            "cache": str(self.cache_dir),
            "settings": str(self.settings_file),
            "history": str(self.history_file),
        }


def default_download_dir() -> Path:
    home = Path.home()
    for name in ("Videos", "ビデオ", "Downloads"):
        candidate = home / name
        if candidate.is_dir():
            return candidate / "Vela"
    return home / "VelaDownloads"


def assets_dir() -> Path:
    bundled = resource_root() / "assets"
    if bundled.exists():
        return bundled
    return app_root() / "assets"


def tools_dir() -> Path:
    bundled = resource_root() / "tools"
    if bundled.exists():
        return bundled
    return app_root() / "tools"
