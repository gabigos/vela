"""Generate offscreen screenshots for visual review (development helper)."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

if os.environ.get("VELA_SHOT_OFFSCREEN") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vela.app import create_runtime  # noqa: E402
from vela.core.models import DownloadStatus, QueueItem  # noqa: E402
from vela.core.paths import AppPaths  # noqa: E402
from vela.core.queue import QueueModel  # noqa: E402

DATA_DIR = ROOT / "tools" / "screenshot-data"
SHOT_DIR = ROOT / "tools" / "screenshots"
OUTPUT_DIR = ROOT / "tools" / "screenshot-output"
# Use a neutral path in screenshots instead of the developer's home directory.
DISPLAY_SAVE_DIR = r"C:\Users\Public\Downloads\Vela"
DISPLAY_FILE_DIR = Path("tools") / "screenshot-output"


def _items() -> list[QueueItem]:
    common = dict(
        save_dir=DISPLAY_SAVE_DIR,
        extractor="YouTube",
    )
    return [
        QueueItem(
            url="https://example.com/watch?v=vela-demo-1",
            title="【4K】夜の街を歩く — シネマティック・ウォーク",
            format_selector="bestvideo+bestaudio/best",
            format_label="4K 2160p · MP4 · 映像＋音声",
            uploader="Studio Vela",
            duration=754,
            thumbnail="",
            status=DownloadStatus.DOWNLOADING,
            downloaded_bytes=176_160_768,
            total_bytes=412_516_352,
            speed=3_355_443,
            eta=46,
            percent=42.7,
            phase="ダウンロード中",
            **common,
        ),
        QueueItem(
            url="https://example.com/watch?v=vela-demo-2",
            title="Lo-fi Beats to Study / Relax — 2 Hour Mix",
            format_selector="bestaudio/best",
            format_label="音声のみ（MP3 192kbps）",
            uploader="Chill Room",
            duration=7200,
            thumbnail="",
            audio_only=True,
            audio_format="mp3",
            status=DownloadStatus.QUEUED,
            **common,
        ),
        QueueItem(
            url="https://example.com/watch?v=vela-demo-3",
            title="Vela の使い方：プレイリストをまとめて保存する",
            format_selector="best",
            format_label="1080p · MP4",
            uploader="Vela Channel",
            duration=642,
            thumbnail="",
            status=DownloadStatus.PAUSED,
            percent=68.2,
            downloaded_bytes=141_557_760,
            total_bytes=207_618_048,
            phase="一時停止中",
            note="再開すると続きからダウンロードします。",
            **common,
        ),
        QueueItem(
            url="https://example.com/watch?v=vela-demo-4",
            title="Sintel — Blender Open Movie (1080p)",
            format_selector="best",
            format_label="1080p · MP4 · 映像＋音声",
            uploader="Blender Foundation",
            duration=888,
            thumbnail="",
            status=DownloadStatus.COMPLETED,
            percent=100.0,
            total_bytes=327_155_712,
            downloaded_bytes=327_155_712,
            output_path=str(OUTPUT_DIR / "sintel.mp4"),
            phase="完了",
            **common,
        ),
        QueueItem(
            url="https://example.com/watch?v=vela-demo-5",
            title="ライブ配信アーカイブ：深夜のコードレビュー",
            format_selector="best",
            format_label="720p · MP4",
            uploader="Dev Night",
            duration=5412,
            thumbnail="",
            status=DownloadStatus.FAILED,
            percent=12.4,
            error_code="AUTH_REQUIRED",
            error_title="ログインが必要です",
            error_message="この動画はログインや年齢確認などの認証を求めています。",
            error_remedy="自分が利用権を持つアカウントの Cookie ファイルを設定画面で指定してください。",
            phase="失敗",
            **common,
        ),
    ]


def main() -> int:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("sintel.mp4", "night.mp4"):
        path = OUTPUT_DIR / name
        if not path.exists():
            path.write_bytes(b"\x00" * 2048)

    app = QApplication(sys.argv[:1])
    paths = AppPaths(DATA_DIR)
    paths.ensure()
    runtime = create_runtime(app, paths)
    ctx = runtime.ctx
    window = runtime.window
    ctx.settings.save_dir = DISPLAY_SAVE_DIR
    window.settings_page.on_settings_changed()
    window.resize(1440, 920)

    now = time.time()
    samples = [
        (
            "【4K】夜の街を歩く — シネマティック・ウォーク",
            "Studio Vela",
            754,
            412_516_352,
            str(DISPLAY_FILE_DIR / "night.mp4"),
            now - 2400,
        ),
        (
            "Lo-fi Beats to Study / Relax — 2 Hour Mix",
            "Chill Room",
            7200,
            96_468_992,
            str(DISPLAY_FILE_DIR / "lofi.mp3"),
            now - 86_400,
        ),
        (
            "Vela の使い方：プレイリストをまとめて保存する",
            "Vela Channel",
            642,
            207_618_048,
            str(DISPLAY_FILE_DIR / "guide.mp4"),
            now - 3 * 86_400,
        ),
        (
            "Sintel — Blender Open Movie (1080p)",
            "Blender Foundation",
            888,
            327_155_712,
            str(DISPLAY_FILE_DIR / "sintel.mp4"),
            now - 20 * 86_400,
        ),
    ]
    for title, uploader, duration, size, filepath, completed in samples:
        ctx.history.add(
            title=title,
            url="https://example.com/watch?v=demo",
            filepath=filepath,
            save_dir=DISPLAY_SAVE_DIR,
            filesize=size,
            duration=duration,
            extractor="YouTube",
            created_at=completed - 300,
            completed_at=completed,
        )

    model: QueueModel = ctx.queue_model
    model.add_items(_items())
    window.queue_page._refresh_stats()  # noqa: SLF001 - screenshot helper
    window.history_page.reload()
    window.show()
    app.processEvents()

    pages = ("home", "queue", "history", "settings", "diagnostics")
    for mode in ("dark", "light"):
        ctx.settings.theme = mode
        ctx.theme.apply(mode, "indigo", True)
        app.processEvents()
        for page in pages:
            window.navigate(page, animate=False)
            app.processEvents()
            pixmap = window.grab()
            target = SHOT_DIR / f"{mode}-{page}.png"
            pixmap.save(str(target))
            print(f"saved {target} ({pixmap.width()}x{pixmap.height()})")
    window._closing = True  # noqa: SLF001
    window.close()
    ctx.history.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
