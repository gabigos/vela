from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from yt_dlp.utils import DownloadError

from .errors import Diagnosis, classify_error
from .ffmpeg_tools import FFmpegInfo
from .logging_setup import YtdlpLogger
from .models import ProgressSnapshot, QueueItem
from .paths import AppPaths
from .security import ensure_within_directory
from .settings import Settings, validate_save_dir
from .ytdlp_service import SafeYoutubeDL

logger = logging.getLogger(__name__)

_EXTENSION_CANDIDATES = (
    "mp4",
    "mkv",
    "webm",
    "mov",
    "flv",
    "avi",
    "mp3",
    "m4a",
    "opus",
    "ogg",
    "aac",
    "flac",
    "wav",
)


class DownloadCancelled(Exception):
    pass


class DownloadPaused(Exception):
    pass


class FFmpegMissingError(RuntimeError):
    pass


@dataclass
class DownloadResult:
    ok: bool = False
    cancelled: bool = False
    paused: bool = False
    skipped_existing: bool = False
    output_path: str = ""
    filesize: int | None = None
    note: str = ""
    error: BaseException | None = None
    diagnosis: Diagnosis | None = None


class DownloadWorker(QObject):
    """Runs one yt-dlp download in a dedicated QThread."""

    started = Signal(str)
    progress = Signal(str, object)
    phase_changed = Signal(str, str)
    finished = Signal(str, object)

    def __init__(
        self,
        item: QueueItem,
        settings_provider,
        paths: AppPaths,
        ffmpeg_provider,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self._settings_provider = settings_provider
        self._paths = paths
        self._ffmpeg_provider = ffmpeg_provider
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._last_emit = 0.0
        self._last_filename = ""
        self._postprocessed_path = ""
        self._skip_target = ""
        self._download_started_at = time.monotonic()

    # Called from the GUI thread; safe to call at any time.
    def request_cancel(self) -> None:
        self._cancel_event.set()

    def request_pause(self) -> None:
        self._pause_event.set()

    def _raise_if_stopped(self, *, allow_pause: bool) -> None:
        if self._cancel_event.is_set():
            raise DownloadCancelled("cancelled")
        if allow_pause and self._pause_event.is_set():
            raise DownloadPaused("paused")

    @Slot()
    def run(self) -> None:
        result = DownloadResult()
        try:
            result = self._download()
        except DownloadCancelled:
            logger.info("ダウンロードをキャンセルしました: %s", self.item.title)
            result = DownloadResult(cancelled=True, note="ユーザーがキャンセルしました。")
        except DownloadPaused:
            logger.info("ダウンロードを一時停止しました: %s", self.item.title)
            result = DownloadResult(
                paused=True,
                note="一時停止しました。再開すると続きからダウンロードします。",
            )
        except Exception as exc:  # noqa: BLE001 - reported through the queue
            diagnosis = classify_error(exc, stage="download")
            logger.error(
                "ダウンロードに失敗しました: %s (%s)",
                self.item.title,
                diagnosis.code,
            )
            logger.debug("ダウンロード例外の詳細", exc_info=exc)
            result = DownloadResult(error=exc, diagnosis=diagnosis)
        finally:
            self.finished.emit(self.item.item_id, result)

    def _download(self) -> DownloadResult:
        item = self.item
        settings: Settings = self._settings_provider()
        ffmpeg: FFmpegInfo = self._ffmpeg_provider()
        save_dir = Path(item.save_dir).expanduser()
        ok, message = validate_save_dir(str(save_dir))
        if not ok:
            raise OSError(message)
        needs_merge = item.requires_ffmpeg or "+" in item.format_selector
        needs_audio_conversion = item.audio_only and item.audio_format in {"mp3", "m4a"}
        if not ffmpeg.available and (needs_merge or needs_audio_conversion):
            raise FFmpegMissingError(
                "FFmpeg が見つかりません。映像と音声の結合や音声変換には FFmpeg が必要です。"
            )

        template = settings.filename_template
        options = self._build_options(settings, ffmpeg, save_dir, template)
        self.started.emit(item.item_id)
        logger.info("ダウンロードを開始します: %s", item.title)
        self._download_started_at = time.monotonic()

        with SafeYoutubeDL(options) as ydl:
            self._raise_if_stopped(allow_pause=False)
            self.phase_changed.emit(item.item_id, "動画情報を確認しています")
            info = ydl.extract_info(item.url, download=False)
            if not info:
                raise DownloadError("動画情報を取得できませんでした。")
            if info.get("_type") == "playlist":
                raise DownloadError("プレイリスト URL は個別の動画に分解してからダウンロードしてください。")

            template, skip_target, skipped = self._resolve_collision(
                ydl, info, settings, save_dir, template
            )
            if skipped:
                path = Path(skip_target)
                size = path.stat().st_size if path.is_file() else None
                return DownloadResult(
                    ok=True,
                    skipped_existing=True,
                    output_path=str(path),
                    filesize=size,
                    note="同名ファイルが存在するため、ダウンロードをスキップしました。",
                )

            self._raise_if_stopped(allow_pause=False)
            result_info = ydl.process_ie_result(info, download=True)
            self._raise_if_stopped(allow_pause=False)
            output_path = self._determine_output_path(ydl, info, result_info, save_dir)

        if output_path and not ensure_within_directory(output_path, save_dir):
            raise DownloadError("保存先以外の場所にファイルが書き込まれたため、処理を中止しました。")
        filesize: int | None = None
        if output_path and Path(output_path).is_file():
            try:
                filesize = Path(output_path).stat().st_size
            except OSError:
                filesize = None
        if not output_path:
            raise DownloadError("出力ファイルの場所を確認できませんでした。")
        if not Path(output_path).is_file():
            raise DownloadError("ダウンロードは完了しましたが、出力ファイルが見つかりません。")
        logger.info("ダウンロードが完了しました: %s -> %s", item.title, output_path)
        return DownloadResult(ok=True, output_path=output_path, filesize=filesize)

    def _build_options(
        self,
        settings: Settings,
        ffmpeg: FFmpegInfo,
        save_dir: Path,
        template: str,
    ) -> dict:
        item = self.item
        options: dict = {
            "format": item.format_selector or "best",
            "outtmpl": template,
            "paths": {"home": str(save_dir)},
            "noplaylist": True,
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "logger": YtdlpLogger("yt_dlp.download"),
            "progress_hooks": [self._on_progress],
            "postprocessor_hooks": [self._on_postprocessor],
            "continuedl": True,
            "nopart": False,
            "windowsfilenames": True,
            "trim_file_name": 150,
            "restrictfilenames": False,
            "overwrites": settings.overwrite == "overwrite",
            "retries": 4,
            "fragment_retries": 4,
            "extractor_retries": 3,
            "file_access_retries": 3,
            "socket_timeout": 25,
            "concurrent_fragment_downloads": 4,
            "cachedir": str(self._paths.ytdlp_cache_dir),
            "no_color": True,
            "noresizebuffer": True,
            "prefer_ffmpeg": True,
            "nocheckcertificate": False,
        }
        if ffmpeg.ffmpeg:
            options["ffmpeg_location"] = str(ffmpeg.ffmpeg)
        if settings.container != "auto" and not item.audio_only:
            options["merge_output_format"] = settings.container
        if settings.rate_limit_mbps > 0:
            options["ratelimit"] = int(settings.rate_limit_mbps) * 1024 * 1024
        if settings.proxy:
            options["proxy"] = settings.proxy
        cookies = Path(settings.cookies_file) if settings.cookies_file else None
        if cookies and cookies.is_file():
            options["cookiefile"] = str(cookies)
        elif cookies:
            logger.warning("Cookie ファイルが見つかりません: %s", cookies)
        if item.audio_only:
            audio_format = item.audio_format or settings.audio_format
            if audio_format in {"mp3", "m4a"}:
                if not ffmpeg.available:
                    raise FFmpegMissingError("音声変換には FFmpeg が必要です。")
                options["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_format,
                        "preferredquality": "192",
                    }
                ]
                options["postprocessor_args"] = {"ffmpeg": ["-loglevel", "error"]}
        return options

    def _candidate_paths(self, ydl: SafeYoutubeDL, info: dict, template: str) -> list[Path]:
        extensions: list[str] = []
        for value in (
            info.get("ext"),
            *(fmt.get("ext") for fmt in info.get("formats") or [] if isinstance(fmt, dict)),
        ):
            ext = str(value or "").lower().strip(".")
            if ext and ext.isalnum() and len(ext) <= 8 and ext not in extensions:
                extensions.append(ext)
        for ext in _EXTENSION_CANDIDATES:
            if ext not in extensions:
                extensions.append(ext)
        paths: list[Path] = []
        original = ydl.params["outtmpl"]
        try:
            ydl.params["outtmpl"]["default"] = template
            for ext in extensions:
                clone = dict(info)
                clone["ext"] = ext
                try:
                    prepared = Path(ydl.prepare_filename(clone))
                except Exception:
                    continue
                if prepared.suffix.lower().lstrip(".") == ext and prepared not in paths:
                    paths.append(prepared)
        finally:
            ydl.params["outtmpl"] = original
        return paths

    def _resolve_collision(
        self,
        ydl: SafeYoutubeDL,
        info: dict,
        settings: Settings,
        save_dir: Path,
        template: str,
    ) -> tuple[str, str, bool]:
        paths = self._candidate_paths(ydl, info, template)
        existing = [path for path in paths if path.is_file()]
        if not existing:
            return template, "", False
        if settings.overwrite == "skip":
            return template, str(existing[0]), True
        if settings.overwrite == "overwrite":
            ydl.params["overwrites"] = True
            return template, "", False
        # rename policy: find the first free numbered name
        head, separator, tail = template.rpartition("%(ext)s")
        if not separator:
            head, tail = template, ""
        for number in range(2, 1000):
            candidate_template = f"{head} ({number}){separator}{tail}"
            candidate_paths = self._candidate_paths(ydl, info, candidate_template)
            if not any(path.is_file() for path in candidate_paths):
                ydl.params["outtmpl"]["default"] = candidate_template
                return candidate_template, "", False
        raise DownloadError("同名ファイルが多すぎるため、保存できませんでした。")

    def _on_progress(self, data: dict) -> None:
        self._raise_if_stopped(allow_pause=True)
        status = data.get("status")
        now = time.monotonic()
        if status == "downloading":
            downloaded = _as_int(data.get("downloaded_bytes"))
            total = _as_int(data.get("total_bytes"))
            estimate = _as_int(data.get("total_bytes_estimate"))
            fragment_index = _as_int(data.get("fragment_index"))
            fragment_count = _as_int(data.get("fragment_count"))
            if total is None and estimate is not None:
                total = estimate
            percent: float | None = None
            if downloaded is not None and total and total > 0:
                percent = min(100.0, max(0.0, downloaded / total * 100.0))
            elif fragment_index is not None and fragment_count:
                percent = min(100.0, max(0.0, fragment_index / fragment_count * 100.0))
            filename = str(data.get("filename") or "")
            if filename:
                self._last_filename = filename
            if now - self._last_emit < 0.18:
                return
            self._last_emit = now
            snapshot = ProgressSnapshot(
                percent=percent,
                downloaded_bytes=downloaded,
                total_bytes=total,
                speed=_as_float(data.get("speed")),
                eta=_as_int(data.get("eta")),
                phase="ダウンロード中",
                fragment_index=fragment_index,
                fragment_count=fragment_count,
            )
            self.progress.emit(self.item.item_id, snapshot)
        elif status == "finished":
            filename = str(data.get("filename") or "")
            if filename:
                self._last_filename = filename
            self.progress.emit(
                self.item.item_id,
                ProgressSnapshot(
                    percent=100.0,
                    downloaded_bytes=_as_int(data.get("downloaded_bytes")),
                    total_bytes=_as_int(data.get("total_bytes")),
                    phase="後処理を準備しています",
                ),
            )
            self.phase_changed.emit(self.item.item_id, "後処理を準備しています")

    def _on_postprocessor(self, data: dict) -> None:
        if self._cancel_event.is_set():
            raise DownloadCancelled("cancelled")
        status = data.get("status")
        name = str(data.get("postprocessor") or "")
        info = data.get("info_dict") or {}
        if status in {"started", "processing"}:
            self.phase_changed.emit(self.item.item_id, _postprocessor_label(name))
        elif status == "finished":
            filepath = str(info.get("filepath") or "")
            if filepath:
                self._postprocessed_path = filepath
            self.phase_changed.emit(self.item.item_id, _postprocessor_label(name))

    def _determine_output_path(
        self,
        ydl: SafeYoutubeDL,
        original_info: dict,
        result_info: dict | None,
        save_dir: Path,
    ) -> str:
        candidates: list[str] = []
        if result_info:
            for download in result_info.get("requested_downloads") or []:
                if isinstance(download, dict):
                    candidates.append(str(download.get("filepath") or ""))
                    candidates.append(str(download.get("_filename") or ""))
            candidates.append(str(result_info.get("filepath") or ""))
        candidates.append(self._postprocessed_path)
        candidates.append(self._last_filename)
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        try:
            fallback = ydl.prepare_filename(original_info)
        except Exception:
            fallback = ""
        if fallback and Path(fallback).is_file():
            return fallback
        # A merged file may use a different extension than the primary stream.
        for candidate in candidates:
            if not candidate:
                continue
            base = Path(candidate)
            for ext in _EXTENSION_CANDIDATES:
                sibling = base.with_suffix(f".{ext}")
                if sibling.is_file():
                    return str(sibling)
        return ""


def _postprocessor_label(name: str) -> str:
    lowered = name.lower()
    if "merge" in lowered:
        return "映像と音声を結合しています"
    if "extractaudio" in lowered or "audio" in lowered:
        return "音声を変換しています"
    if "remux" in lowered:
        return "形式を変換しています"
    if "movefiles" in lowered:
        return "ファイルを保存しています"
    if "videoconvert" in lowered:
        return "動画を変換しています"
    return "後処理を実行しています"


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
