from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.ffmpeg_tools import FFmpegInfo, discover_ffmpeg
from ..core.history import HistoryStore
from ..core.paths import AppPaths
from ..core.queue import QueueManager, QueueModel
from ..core.settings import Settings, SettingsStore
from ..core.ytdlp_service import VideoAnalyzer
from .theme import ThemeManager
from .thumbnail import ThumbnailLoader

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    paths: AppPaths
    store: SettingsStore
    settings: Settings
    history: HistoryStore
    queue_model: QueueModel
    queue: QueueManager
    analyzer: VideoAnalyzer
    thumbnails: ThumbnailLoader
    theme: ThemeManager
    ffmpeg: FFmpegInfo

    def settings_getter(self) -> Settings:
        return self.settings

    def ffmpeg_getter(self) -> FFmpegInfo:
        return self.ffmpeg

    def refresh_ffmpeg(self) -> FFmpegInfo:
        self.ffmpeg = discover_ffmpeg(self.settings.ffmpeg_dir or None)
        return self.ffmpeg
