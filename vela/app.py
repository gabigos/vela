from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_ID, APP_NAME, ORG_NAME, __version__
from .core.ffmpeg_tools import discover_ffmpeg
from .core.history import HistoryStore
from .core.logging_setup import setup_logging
from .core.paths import AppPaths
from .core.queue import QueueManager, QueueModel
from .core.settings import Settings, SettingsStore
from .core.ytdlp_service import VideoAnalyzer
from .ui.context import AppContext
from .ui.icons import app_icon
from .ui.main_window import MainWindow
from .ui.theme import ThemeManager
from .ui.thumbnail import ThumbnailLoader

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    app: QApplication
    window: MainWindow
    ctx: AppContext
    paths: AppPaths


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vela",
        description="Vela — yt-dlp を利用した Windows 向け動画ダウンローダー",
    )
    parser.add_argument("--version", action="store_true", help="バージョンを表示して終了します")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="画面を構築して終了する起動確認モード（開発向け）",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        help="設定・履歴・ログの保存先を指定します（開発・ポータブル用途）",
    )
    parser.add_argument("--debug", action="store_true", help="デバッグログを出力します")
    return parser.parse_args(argv)


def _build_paths(data_dir: str | None) -> AppPaths:
    paths = AppPaths(Path(data_dir) if data_dir else None)
    try:
        paths.ensure()
    except OSError:
        paths = paths.fallback()
        paths.ensure()
    return paths


def create_runtime(
    app: QApplication,
    paths: AppPaths,
    *,
    store: SettingsStore | None = None,
    settings: Settings | None = None,
) -> Runtime:
    """Build the application object graph and main window.

    Kept separate from :func:`run` so tests and tooling can construct the UI
    without entering the Qt event loop.
    """
    store = store or SettingsStore(paths.settings_file)
    settings = settings or store.load()
    theme = ThemeManager(app, paths.cache_dir / "ui")
    theme.apply(settings.theme, settings.accent, settings.animations)

    history = HistoryStore(paths.history_file, limit=settings.history_limit)
    ffmpeg = discover_ffmpeg(settings.ffmpeg_dir or None)
    model = QueueModel()
    queue = QueueManager(
        model,
        lambda: ctx.settings,
        paths,
        lambda: ctx.ffmpeg,
        history,
    )
    analyzer = VideoAnalyzer(lambda: ctx.settings, paths, lambda: ctx.ffmpeg)
    thumbnails = ThumbnailLoader(paths.thumbnails_dir)
    ctx = AppContext(
        paths=paths,
        store=store,
        settings=settings,
        history=history,
        queue_model=model,
        queue=queue,
        analyzer=analyzer,
        thumbnails=thumbnails,
        theme=theme,
        ffmpeg=ffmpeg,
    )
    window = MainWindow(ctx)
    app.setWindowIcon(app_icon())
    app.aboutToQuit.connect(history.close)
    return Runtime(app=app, window=window, ctx=ctx, paths=paths)


def _install_exception_hook() -> None:
    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical(
            "未処理の例外が発生しました:\n%s",
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )
        try:
            QMessageBox.critical(
                None,
                "Vela — 予期しないエラー",
                "予期しないエラーが発生しました。\n"
                "作業中の内容は可能な範囲で保存されています。\n\n"
                f"{exc_type.__name__}: {exc}\n\n"
                "詳しい情報はログに記録されています。診断画面またはログファイルを確認してください。",
            )
        except Exception:
            pass

    sys.excepthook = hook


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    smoke_dir: Path | None = None
    data_dir = args.data_dir
    if args.smoke_test and not data_dir:
        smoke_dir = Path(tempfile.mkdtemp(prefix="vela-smoke-"))
        data_dir = str(smoke_dir)

    _set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    app.setDesktopFileName("vela")
    app.setQuitOnLastWindowClosed(True)

    paths = _build_paths(data_dir)
    setup_logging(paths.log_file, level=logging.DEBUG if args.debug else logging.INFO)
    _install_exception_hook()
    logger.info("Vela %s を起動します (%s)", __version__, paths.data_dir)

    try:
        runtime = create_runtime(app, paths)
    except Exception:
        logger.exception("アプリケーションを初期化できませんでした")
        QMessageBox.critical(
            None,
            "Vela を起動できません",
            "アプリケーションの初期化中にエラーが発生しました。\n"
            f"ログを確認してください: {paths.log_file}",
        )
        return 1

    window = runtime.window
    window.show()

    if args.smoke_test:
        result = _run_smoke_test(app, runtime)
        shutil.rmtree(smoke_dir, ignore_errors=True) if smoke_dir else None
        return result

    logger.info("メイン画面を表示しました")
    code = app.exec()
    logger.info("Vela を終了します (code=%s)", code)
    return int(code)


def _run_smoke_test(app: QApplication, runtime: Runtime) -> int:
    try:
        app.processEvents()
        window = runtime.window
        pages = ("home", "queue", "history", "settings", "diagnostics")
        for page in pages:
            window.navigate(page, animate=False)
            app.processEvents()
        QTimer.singleShot(0, app.quit)
        app.processEvents()
        count = window.stack.count()
        ffmpeg = runtime.ctx.ffmpeg
        summary = (
            f"{APP_NAME} {__version__} / {count} pages / "
            f"theme={runtime.ctx.theme.palette.mode} / data={runtime.paths.data_dir} / "
            f"ffmpeg={'ok' if ffmpeg.available else 'missing'}"
        )
        print(f"SMOKE OK: {summary}")
        logger.info("スモークテストが完了しました: %s", summary)
        window._closing = True  # noqa: SLF001 - avoid the interactive close prompt
        window.close()
        app.processEvents()
        return 0 if count == len(pages) else 2
    except Exception:
        logger.exception("スモークテストに失敗しました")
        print("SMOKE FAILED", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
