from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from .. import __version__
from .errors import classify_error
from .ffmpeg_tools import FFmpegInfo
from .logging_setup import YtdlpLogger, sanitize_text
from .models import FormatInfo, PlaylistEntry, VideoInfo, _best_thumbnail
from .paths import AppPaths
from .security import resolve_public_host, validate_redirect_target
from .settings import Settings

logger = logging.getLogger(__name__)

PLAYLIST_LIMIT = 500
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class AnalysisError(RuntimeError):
    pass


class URLRejectedError(AnalysisError):
    pass


class SafeYoutubeDL(yt_dlp.YoutubeDL):
    """YoutubeDL with a request guard for non-public and non-HTTP targets."""

    allow_private = False

    def urlopen(self, req):  # type: ignore[override]
        url = ""
        if isinstance(req, str):
            url = req
        else:
            url = getattr(req, "full_url", "") or getattr(req, "url", "")
        if url and not url.startswith(("http://", "https://")):
            raise DownloadError(f"許可されていない URL スキームです: {url.split(':', 1)[0]}")
        if url and not self.allow_private:
            validation = validate_redirect_target(url)
            if not validation:
                raise DownloadError(validation.message or "安全でない URL へのリダイレクトをブロックしました。")
        return super().urlopen(req)


def _base_options(settings: Settings, paths: AppPaths, ffmpeg: FFmpegInfo, *, analysis: bool) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "logger": YtdlpLogger("yt_dlp"),
        "cachedir": str(paths.ytdlp_cache_dir),
        "socket_timeout": 25,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,
        "windowsfilenames": True,
        "trim_file_name": 150,
        "nocheckcertificate": False,
        "noplaylist": not analysis,
        "ignoreerrors": False,
        "no_color": True,
        "consoletitle": False,
        "progress_delta": 0.2,
    }
    if analysis:
        options["extract_flat"] = "in_playlist"
        options["playlistend"] = PLAYLIST_LIMIT
        options["skip_download"] = True
    if ffmpeg.ffmpeg:
        options["ffmpeg_location"] = str(ffmpeg.ffmpeg)
    if settings.proxy:
        options["proxy"] = settings.proxy
    cookies = Path(settings.cookies_file) if settings.cookies_file else None
    if cookies and cookies.is_file():
        options["cookiefile"] = str(cookies)
    elif cookies:
        logger.warning("設定された Cookie ファイルが見つからないため、使用しません: %s", cookies)
    return options


class VideoAnalyzer:
    def __init__(
        self,
        settings_provider,
        paths: AppPaths,
        ffmpeg_provider,
        *,
        allow_private: bool = False,
    ) -> None:
        self._settings_provider = settings_provider
        self._paths = paths
        self._ffmpeg_provider = ffmpeg_provider
        self.allow_private = allow_private

    def analyze(self, url: str, status_callback=None) -> VideoInfo:
        def status(message: str) -> None:
            if status_callback is not None:
                try:
                    status_callback(message)
                except Exception:
                    pass

        settings = self._settings_provider()
        ffmpeg = self._ffmpeg_provider()
        status("URL を確認しています")
        validation = resolve_public_host(url, allow_private=self.allow_private)
        if not validation:
            raise URLRejectedError(validation.message)
        safe_ydl = SafeYoutubeDL
        safe_ydl.allow_private = self.allow_private
        options = _base_options(settings, self._paths, ffmpeg, analysis=True)
        logger.info("解析を開始します: %s", validation.url)
        status("動画情報を取得しています")
        try:
            with safe_ydl(options) as ydl:
                info = ydl.extract_info(validation.url, download=False)
        except DownloadError as exc:
            logger.warning("解析に失敗しました: %s", exc)
            raise AnalysisError(str(exc)) from exc
        except Exception as exc:  # yt-dlp raises a variety of types
            logger.exception("解析中に予期しないエラーが発生しました")
            raise AnalysisError(str(exc)) from exc
        if not info:
            raise AnalysisError("動画情報を取得できませんでした。URL を確認してください。")
        status("プレイリストを整理しています")
        result = _parse_info(info, validation.url)
        logger.info(
            "解析が完了しました: %s (%s)",
            result.title,
            f"{len(result.entries)} 件のプレイリスト" if result.is_playlist else "単一動画",
        )
        return result


def _parse_info(info: dict[str, Any], requested_url: str) -> VideoInfo:
    is_playlist = info.get("_type") == "playlist" or (
        "entries" in info and info.get("_type") not in {"url", "url_transparent"}
    )
    thumbnail = _best_thumbnail(info.get("thumbnails")) or str(info.get("thumbnail") or "")
    base = VideoInfo(
        url=requested_url,
        title=str(info.get("title") or "無題の動画"),
        video_id=str(info.get("id") or ""),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=_number(info.get("duration")),
        thumbnail=thumbnail,
        extractor=str(info.get("extractor") or ""),
        extractor_key=str(info.get("extractor_key") or ""),
        description=str(info.get("description") or ""),
        view_count=_integer(info.get("view_count")),
        upload_date=str(info.get("upload_date") or ""),
        live_status=str(info.get("live_status") or ("is_live" if info.get("is_live") else "")),
        webpage_url=str(info.get("webpage_url") or requested_url),
        age_limit=_integer(info.get("age_limit")) or 0,
    )
    if not is_playlist:
        raw_formats = info.get("formats") or []
        formats = [FormatInfo.from_dict(item) for item in raw_formats if isinstance(item, dict)]
        if not formats and info.get("url"):
            formats = [
                FormatInfo(
                    format_id=str(info.get("format_id") or "best"),
                    ext=str(info.get("ext") or ""),
                    height=_integer(info.get("height")),
                    width=_integer(info.get("width")),
                    fps=_number(info.get("fps")),
                    vcodec=info.get("vcodec"),
                    acodec=info.get("acodec"),
                    filesize=_integer(info.get("filesize") or info.get("filesize_approx")),
                    format_note=str(info.get("format_note") or ""),
                    protocol=str(info.get("protocol") or ""),
                )
            ]
        base.formats = formats
        return base

    base.is_playlist = True
    base.playlist_title = str(info.get("title") or "プレイリスト")
    entries: list[PlaylistEntry] = []
    raw_entries = info.get("entries") or []
    total_seen = 0
    for raw_entry in raw_entries:
        total_seen += 1
        if total_seen > PLAYLIST_LIMIT:
            break
        if not isinstance(raw_entry, dict):
            continue
        if raw_entry.get("_type") in {"playlist", "multi_video"}:
            continue
        entry = PlaylistEntry.from_dict(raw_entry, len(entries))
        if not entry.url:
            entry.url = _fallback_entry_url(raw_entry, info)
        if not entry.url:
            continue
        if not entry.thumbnail:
            entry.thumbnail = thumbnail
        entries.append(entry)
    base.entries = entries
    declared = info.get("playlist_count")
    base.playlist_count = _integer(declared) or len(entries)
    base.entry_limit_reached = bool(
        total_seen > PLAYLIST_LIMIT or (base.playlist_count or 0) > len(entries)
    )
    if not entries:
        raise AnalysisError("プレイリスト内にダウンロードできる動画が見つかりませんでした。")
    return base


def _fallback_entry_url(entry: dict[str, Any], playlist_info: dict[str, Any]) -> str:
    entry_id = entry.get("id")
    if not entry_id:
        return ""
    extractor = str(playlist_info.get("extractor_key") or "").lower()
    if "youtube" in extractor:
        return f"https://www.youtube.com/watch?v={entry_id}"
    if "vimeo" in extractor:
        return f"https://vimeo.com/{entry_id}"
    return ""


def _integer(value: object) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)  # type: ignore[arg-type]
        if not math.isfinite(number):
            return None
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)  # type: ignore[arg-type]
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class UpdateCheck:
    current: str
    latest: str = ""
    newer_available: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.latest) and not self.error


def parse_version(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text or "")
    return tuple(int(part) for part in parts[:6]) or (0,)


def check_latest_ytdlp() -> UpdateCheck:
    current = getattr(yt_dlp.version, "__version__", "unknown")
    request = urllib.request.Request(
        "https://pypi.org/pypi/yt-dlp/json",
        headers={"User-Agent": f"Vela/{__version__}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        latest = str(payload.get("info", {}).get("version") or "")
        if not latest:
            return UpdateCheck(current, error="最新バージョンを取得できませんでした。")
        return UpdateCheck(
            current=current,
            latest=latest,
            newer_available=parse_version(latest) > parse_version(current),
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return UpdateCheck(current, error=f"更新情報を取得できませんでした: {exc}")


def update_ytdlp() -> tuple[bool, str]:
    if getattr(sys, "frozen", False):
        return (
            False,
            "実行ファイル版では yt-dlp のみを差し替えることはできません。新しいバージョンの Vela を配布元から入手してください。",
        )
    command = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"]
    logger.info("yt-dlp の更新を開始します")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=_CREATE_NO_WINDOW,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("yt-dlp の更新に失敗しました: %s", exc)
        return False, f"更新コマンドを実行できませんでした: {exc}"
    output = sanitize_text((completed.stdout or "") + "\n" + (completed.stderr or ""), 4000)
    if completed.returncode == 0:
        logger.info("yt-dlp の更新が完了しました。再起動が必要です。")
        return True, "yt-dlp を更新しました。変更を反映するには Vela を再起動してください。\n\n" + output.strip()
    logger.error("yt-dlp の更新に失敗しました (code=%s)", completed.returncode)
    return False, f"更新に失敗しました（終了コード {completed.returncode}）。\n\n{output.strip()}"


def environment_report(ffmpeg: FFmpegInfo | None, paths: AppPaths) -> dict[str, str]:
    import platform

    try:
        import PySide6

        pyside = PySide6.__version__
    except Exception:  # pragma: no cover
        pyside = "unknown"
    try:
        extractor_count = str(len(yt_dlp.extractor.gen_extractors()))
    except Exception:
        extractor_count = "unknown"
    return {
        "Vela": __version__,
        "Python": platform.python_version(),
        "PySide6 / Qt": pyside,
        "yt-dlp": getattr(yt_dlp.version, "__version__", "unknown"),
        "対応 Extractor 数": extractor_count,
        "FFmpeg": (ffmpeg.version if ffmpeg and ffmpeg.version else "未検出"),
        "FFmpeg の場所": str(ffmpeg.ffmpeg) if ffmpeg and ffmpeg.ffmpeg else "—",
        "OS": platform.platform(),
        "データフォルダー": str(paths.data_dir),
        "ログ": str(paths.log_file),
        "実行モード": "実行ファイル" if getattr(sys, "frozen", False) else "ソース",
    }


def make_diagnosis(error: BaseException | str, *, stage: str = "download"):
    return classify_error(error, stage=stage)
