from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CANCELLING = "cancelling"

    @property
    def label(self) -> str:
        return {
            "queued": "待機中",
            "analyzing": "解析中",
            "downloading": "ダウンロード中",
            "processing": "処理中",
            "paused": "一時停止",
            "completed": "完了",
            "failed": "失敗",
            "cancelled": "キャンセル済み",
            "cancelling": "キャンセル中",
        }[self.value]

    @property
    def is_active(self) -> bool:
        return self in {
            DownloadStatus.ANALYZING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PROCESSING,
            DownloadStatus.CANCELLING,
        }

    @property
    def is_final(self) -> bool:
        return self in {
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
        }


@dataclass
class FormatInfo:
    format_id: str
    ext: str = ""
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    filesize: int | None = None
    tbr: float | None = None
    format_note: str = ""
    dynamic_range: str = ""
    protocol: str = ""
    language: str = ""
    audio_bitrate: float | None = None

    @property
    def has_video(self) -> bool:
        return self.vcodec not in (None, "", "none")

    @property
    def has_audio(self) -> bool:
        return self.acodec not in (None, "", "none")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FormatInfo":
        return cls(
            format_id=str(raw.get("format_id") or ""),
            ext=str(raw.get("ext") or ""),
            height=_int(raw.get("height")),
            width=_int(raw.get("width")),
            fps=_float(raw.get("fps")),
            vcodec=raw.get("vcodec"),
            acodec=raw.get("acodec"),
            filesize=_int(raw.get("filesize") or raw.get("filesize_approx")),
            tbr=_float(raw.get("tbr") or raw.get("total_bitrate")),
            format_note=str(raw.get("format_note") or ""),
            dynamic_range=str(raw.get("dynamic_range") or ""),
            protocol=str(raw.get("protocol") or ""),
            language=str(raw.get("language") or ""),
            audio_bitrate=_float(raw.get("abr")),
        )


@dataclass
class PlaylistEntry:
    index: int
    title: str
    url: str
    duration: float | None = None
    uploader: str = ""
    video_id: str = ""
    thumbnail: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any], index: int) -> "PlaylistEntry":
        return cls(
            index=index,
            title=str(raw.get("title") or f"動画 {index + 1}"),
            url=str(raw.get("webpage_url") or raw.get("url") or ""),
            duration=_float(raw.get("duration")),
            uploader=str(raw.get("uploader") or raw.get("channel") or ""),
            video_id=str(raw.get("id") or ""),
            thumbnail=_best_thumbnail(raw.get("thumbnails")) or str(raw.get("thumbnail") or ""),
        )


@dataclass
class VideoInfo:
    url: str
    title: str
    video_id: str = ""
    uploader: str = ""
    duration: float | None = None
    thumbnail: str = ""
    extractor: str = ""
    extractor_key: str = ""
    description: str = ""
    view_count: int | None = None
    upload_date: str = ""
    formats: list[FormatInfo] = field(default_factory=list)
    is_playlist: bool = False
    playlist_title: str = ""
    playlist_count: int | None = None
    entries: list[PlaylistEntry] = field(default_factory=list)
    entry_limit_reached: bool = False
    live_status: str = ""
    webpage_url: str = ""
    age_limit: int = 0

    @property
    def display_site(self) -> str:
        if self.extractor:
            return self.extractor.replace(":", " · ")
        return self.extractor_key.title() if self.extractor_key else "Web"

    @property
    def has_formats(self) -> bool:
        return bool(self.formats)


@dataclass
class FormatOption:
    key: str
    label: str
    selector: str
    kind: str  # preset | video | audio
    ext: str = ""
    height: int | None = None
    fps: float | None = None
    vcodec: str = ""
    acodec: str = ""
    filesize: int | None = None
    note: str = ""
    requires_ffmpeg: bool = False
    audio_format: str = ""  # mp3 / m4a for audio extraction
    audio_only: bool = False

    @property
    def size_text(self) -> str:
        if self.filesize is None:
            return "サイズ不明"
        from .utils import human_size

        return human_size(self.filesize, approximate=True)


@dataclass
class ProgressSnapshot:
    percent: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    phase: str = ""
    fragment_index: int | None = None
    fragment_count: int | None = None


@dataclass
class QueueItem:
    url: str
    title: str
    save_dir: str
    format_selector: str
    format_label: str
    item_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    uploader: str = ""
    duration: float | None = None
    extractor: str = ""
    thumbnail: str = ""
    video_id: str = ""
    audio_only: bool = False
    audio_format: str = ""
    requires_ffmpeg: bool = False
    playlist_title: str = ""
    status: DownloadStatus = DownloadStatus.QUEUED
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    percent: float | None = None
    phase: str = ""
    output_path: str = ""
    error_code: str = ""
    error_title: str = ""
    error_message: str = ""
    error_remedy: str = ""
    note: str = ""
    added_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    attempts: int = 0

    @property
    def is_active(self) -> bool:
        return self.status.is_active

    @property
    def is_final(self) -> bool:
        return self.status.is_final

    @property
    def status_label(self) -> str:
        return self.status.label

    def reset_for_retry(self) -> None:
        self.status = DownloadStatus.QUEUED
        self.downloaded_bytes = None
        self.total_bytes = None
        self.speed = None
        self.eta = None
        self.percent = None
        self.phase = ""
        self.error_code = ""
        self.error_title = ""
        self.error_message = ""
        self.error_remedy = ""
        self.note = ""
        self.output_path = ""
        self.started_at = None
        self.finished_at = None

    def to_persisted_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "url": self.url,
            "title": self.title,
            "save_dir": self.save_dir,
            "format_selector": self.format_selector,
            "format_label": self.format_label,
            "uploader": self.uploader,
            "duration": self.duration,
            "extractor": self.extractor,
            "thumbnail": self.thumbnail,
            "video_id": self.video_id,
            "audio_only": self.audio_only,
            "audio_format": self.audio_format,
            "requires_ffmpeg": self.requires_ffmpeg,
            "playlist_title": self.playlist_title,
            "status": DownloadStatus.PAUSED.value,
            "added_at": self.added_at,
            "attempts": self.attempts,
            "note": self.note,
        }

    @classmethod
    def from_persisted_dict(cls, raw: dict[str, Any]) -> "QueueItem | None":
        try:
            status = DownloadStatus(str(raw.get("status") or "paused"))
            if status not in (DownloadStatus.PAUSED, DownloadStatus.QUEUED):
                status = DownloadStatus.PAUSED
            return cls(
                item_id=str(raw.get("item_id") or uuid.uuid4().hex),
                url=str(raw["url"]),
                title=str(raw.get("title") or "動画"),
                save_dir=str(raw.get("save_dir") or ""),
                format_selector=str(raw.get("format_selector") or "best"),
                format_label=str(raw.get("format_label") or "最高画質（自動）"),
                uploader=str(raw.get("uploader") or ""),
                duration=_float(raw.get("duration")),
                extractor=str(raw.get("extractor") or ""),
                thumbnail=str(raw.get("thumbnail") or ""),
                video_id=str(raw.get("video_id") or ""),
                audio_only=bool(raw.get("audio_only")),
                audio_format=str(raw.get("audio_format") or ""),
                requires_ffmpeg=bool(raw.get("requires_ffmpeg")),
                playlist_title=str(raw.get("playlist_title") or ""),
                status=status,
                added_at=float(raw.get("added_at") or time.time()),
                attempts=int(raw.get("attempts") or 0),
                note=str(raw.get("note") or "前回の終了時に中断されました。再開できます。"),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def progress_snapshot(self) -> ProgressSnapshot:
        return ProgressSnapshot(
            percent=self.percent,
            downloaded_bytes=self.downloaded_bytes,
            total_bytes=self.total_bytes,
            speed=self.speed,
            eta=self.eta,
            phase=self.phase,
        )


def _int(value: object) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _best_thumbnail(thumbnails: object) -> str:
    if not isinstance(thumbnails, list):
        return ""
    best_url = ""
    best_area = -1
    for item in thumbnails:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        width = _int(item.get("width")) or 0
        height = _int(item.get("height")) or 0
        area = width * height
        preference = _int(item.get("preference")) or 0
        score = (preference, area)
        if score >= (0, best_area) and area >= best_area:
            best_area = area
            best_url = url
    return best_url
