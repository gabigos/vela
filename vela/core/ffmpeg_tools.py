from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import app_root, resource_root

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass(frozen=True)
class FFmpegInfo:
    ffmpeg: Path | None = None
    ffprobe: Path | None = None
    version: str = ""
    source: str = "not-found"

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg)

    @property
    def probe_available(self) -> bool:
        return bool(self.ffprobe)

    @property
    def directory(self) -> Path | None:
        return self.ffmpeg.parent if self.ffmpeg else None

    def status_label(self) -> str:
        if not self.available:
            return "未検出"
        version = self.version.replace("ffmpeg version ", "").split()[0] if self.version else ""
        return f"FFmpeg {version}".strip()


def _candidate_bins(configured: str | None = None) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []

    def add(directory: Path | None, source: str) -> None:
        if directory is None:
            return
        for candidate in (directory, directory / "bin"):
            if candidate.name.lower() in {"ffmpeg.exe", "ffmpeg"}:
                candidate = candidate.parent
            if candidate not in [item[0] for item in candidates]:
                candidates.append((candidate, source))

    if configured:
        path = Path(os.path.expandvars(os.path.expanduser(configured)))
        if path.is_file():
            path = path.parent
        add(path, "設定")
    env_dir = os.environ.get("VELA_FFMPEG_DIR")
    if env_dir:
        add(Path(env_dir), "環境変数")
    add(resource_root() / "tools" / "ffmpeg" / "bin", "同梱")
    add(app_root() / "tools" / "ffmpeg" / "bin", "同梱")
    if getattr(sys, "frozen", False):
        add(Path(sys.executable).resolve().parent / "tools" / "ffmpeg" / "bin", "同梱")
        add(Path(sys.executable).resolve().parent / "ffmpeg" / "bin", "同梱")
    which = shutil.which("ffmpeg")
    if which:
        add(Path(which).parent, "システム")
    return candidates


def discover_ffmpeg(configured: str | None = None, *, probe_version: bool = True) -> FFmpegInfo:
    for directory, source in _candidate_bins(configured):
        ffmpeg = directory / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if not ffmpeg.is_file():
            continue
        ffprobe = directory / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        version = _version(ffmpeg) if probe_version else ""
        return FFmpegInfo(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe if ffprobe.is_file() else None,
            version=version,
            source=source,
        )
    return FFmpegInfo()


def _version(executable: Path) -> str:
    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
        first = (completed.stdout or "").splitlines()
        return first[0].strip() if first else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def ffprobe_media(path: str | Path, ffprobe: Path | None, timeout: int = 20) -> dict | None:
    if not ffprobe:
        return None
    try:
        completed = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
        if completed.returncode != 0:
            return None
        return json.loads(completed.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def ffmpeg_environment(ffmpeg: FFmpegInfo) -> dict[str, str]:
    env = os.environ.copy()
    if ffmpeg.directory:
        current = env.get("PATH", "")
        env["PATH"] = f"{ffmpeg.directory}{os.pathsep}{current}"
    return env
