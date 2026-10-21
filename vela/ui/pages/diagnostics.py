from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...core.ffmpeg_tools import FFmpegInfo
from ...core.logging_setup import get_memory_handler, read_log_tail
from ...core.ytdlp_service import (
    UpdateCheck,
    check_latest_ytdlp,
    environment_report,
    update_ytdlp,
)
from ..context import AppContext
from ..theme import current_palette
from ..widgets import (
    Card,
    ElidedLabel,
    Spinner,
    make_button,
    make_divider,
    make_label,
    refresh_named_icons,
    set_named_icon,
    tone_colors,
)

logger = logging.getLogger(__name__)


class CheckThread(QThread):
    finished_check = Signal(object)

    def run(self) -> None:
        try:
            result = check_latest_ytdlp()
        except Exception as exc:  # noqa: BLE001 - reported in the UI
            result = UpdateCheck(current="unknown", error=str(exc))
        self.finished_check.emit(result)


class InstallThread(QThread):
    finished_install = Signal(bool, str)

    def run(self) -> None:
        try:
            ok, message = update_ytdlp()
        except Exception as exc:  # noqa: BLE001 - reported in the UI
            ok, message = False, f"更新中にエラーが発生しました: {exc}"
        self.finished_install.emit(ok, message)


class DiagnosticsPage(QWidget):
    def __init__(
        self,
        ctx: AppContext,
        *,
        navigate: Callable[[str], None],
        open_logs: Callable[[], None],
        toast: Callable[..., None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._navigate = navigate
        self._open_logs = open_logs
        self._toast = toast
        self._check_thread: CheckThread | None = None
        self._install_thread: InstallThread | None = None
        self._last_check: UpdateCheck | None = None
        self._auto_checked = False
        # Own the timer so it is cancelled with the page instead of firing
        # into a half-destroyed window during shutdown.
        self._auto_check_timer = QTimer(self)
        self._auto_check_timer.setSingleShot(True)
        self._auto_check_timer.timeout.connect(self._auto_check)
        self._build_ui()
        self._render_environment()
        self._load_logs()
        if self.ctx.settings.check_updates:
            self._auto_check_timer.start(1500)

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("pageScroll")
        root.addWidget(self.scroll)
        body = QWidget()
        body.setObjectName("scrollBody")
        self.scroll.setWidget(body)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(34, 26, 34, 48)
        body_layout.setAlignment(Qt.AlignTop)
        wrap = QWidget(body)
        wrap_layout = QHBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        column = QWidget(wrap)
        column.setMaximumWidth(1040)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._column = QVBoxLayout(column)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(18)
        wrap_layout.addStretch(1)
        wrap_layout.addWidget(column, 30)
        wrap_layout.addStretch(1)
        body_layout.addWidget(wrap, 0, Qt.AlignTop)

        header = QHBoxLayout()
        header.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(make_label("診断", "h1"))
        description = make_label(
            "実行環境、FFmpeg、yt-dlp の状態を確認し、問題の切り分けに役立てます。",
            "secondary",
            wrap=True,
        )
        description.setMinimumWidth(120)
        text.addWidget(description)
        header.addLayout(text, 1)
        self.copy_button = make_button("診断情報をコピー", "secondary", icon_name="copy", parent=self)
        self.copy_button.clicked.connect(self._copy_report)
        header.addWidget(self.copy_button)
        logs_button = make_button("ログを開く", "primary", icon_name="file", parent=self)
        logs_button.clicked.connect(self._open_logs)
        header.addWidget(logs_button)
        self._column.addLayout(header)

        self._build_environment()
        self._build_updates()
        self._build_logs()
        self._build_help()
        self._column.addStretch(1)

    def _build_environment(self) -> None:
        card = Card(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(make_label("実行環境", "h2"))
        head.addStretch(1)
        self.env_badge = make_label("", "pill")
        head.addWidget(self.env_badge)
        layout.addLayout(head)
        layout.addWidget(make_divider(card))
        self.env_grid = QGridLayout()
        self.env_grid.setHorizontalSpacing(26)
        self.env_grid.setVerticalSpacing(10)
        self.env_grid.setColumnStretch(1, 1)
        layout.addLayout(self.env_grid)
        self._column.addWidget(card)

    def _build_updates(self) -> None:
        card = Card(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(make_label("yt-dlp の更新", "h2"))
        head.addStretch(1)
        self.update_badge = make_label("未確認", "pill")
        head.addWidget(self.update_badge)
        layout.addLayout(head)
        layout.addWidget(
            make_label(
                "サイトの仕様変更に追従するため、yt-dlp を最新版に保つことをおすすめします。"
                "実行ファイル版では Vela 本体を更新してください。",
                "caption",
                wrap=True,
            )
        )
        versions = QHBoxLayout()
        versions.setSpacing(24)
        self.current_version = self._version_block("現在のバージョン", "—", versions)
        self.latest_version = self._version_block("最新のバージョン", "—", versions)
        versions.addStretch(1)
        layout.addLayout(versions)
        self.update_status = make_label("", "caption", wrap=True)
        layout.addWidget(self.update_status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.spinner = Spinner(card, size=18)
        actions.addWidget(self.spinner)
        actions.addStretch(1)
        self.check_button = make_button("更新を確認", "secondary", icon_name="refresh", parent=card)
        self.check_button.clicked.connect(self._check_updates)
        actions.addWidget(self.check_button)
        self.install_button = make_button("yt-dlp を更新", "primary", icon_name="download", parent=card)
        self.install_button.clicked.connect(self._install_update)
        self.install_button.setEnabled(False)
        actions.addWidget(self.install_button)
        layout.addLayout(actions)
        self._column.addWidget(card)

    def _version_block(self, title: str, value: str, layout: QHBoxLayout) -> QLabel:
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(make_label(title, "caption"))
        label = make_label(value, "h3")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(label)
        layout.addLayout(box)
        return label

    def _build_logs(self) -> None:
        card = Card(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(make_label("最近のログ", "h2"))
        self.log_path = ElidedLabel(str(self.ctx.paths.log_file), card)
        self.log_path.setProperty("role", "caption")
        self.log_path.setProperty("path", True)
        self.log_path.setMaximumWidth(420)
        head.addWidget(self.log_path, 1)
        refresh = make_button("更新", "ghost", icon_name="refresh", parent=card)
        refresh.clicked.connect(self._load_logs)
        head.addWidget(refresh)
        open_folder = make_button("フォルダー", "ghost", icon_name="folder-open", parent=card)
        open_folder.clicked.connect(self._open_log_folder)
        head.addWidget(open_folder)
        layout.addLayout(head)
        self.log_view = QPlainTextEdit(card)
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMinimumHeight(230)
        self.log_view.setAccessibleName("アプリケーションログ")
        layout.addWidget(self.log_view)
        self._column.addWidget(card)

    def _build_help(self) -> None:
        card = Card(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label("よくある問題", "h2"))
        items = (
            (
                "alert-triangle",
                "ダウンロードが失敗する",
                "サイト側の変更やボット確認が原因の場合があります。yt-dlp を更新し、Cookie 設定も確認してください。",
                "設定を開く",
                lambda: self._navigate("settings"),
            ),
            (
                "layers",
                "映像と音声の結合に失敗する",
                "FFmpeg が検出されているか確認してください。同梱の tools/ffmpeg が欠けている場合は再配置が必要です。",
                "再検出",
                self._refresh_ffmpeg,
            ),
            (
                "shield",
                "DRM 保護と表示される",
                "DRM の解除は行いません。公式アプリや配信サービスを利用してください。",
                "ヘルプ",
                self._open_logs,
            ),
        )
        for index, (icon_name, title, body, action_text, callback) in enumerate(items):
            if index:
                layout.addWidget(make_divider(card))
            row = QHBoxLayout()
            row.setSpacing(12)
            badge = QLabel(card)
            set_named_icon(badge, icon_name, color="muted", size=20)
            badge.setFixedSize(22, 22)
            row.addWidget(badge, 0, Qt.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(make_label(title, "h3"))
            text.addWidget(make_label(body, "caption", wrap=True))
            row.addLayout(text, 1)
            button = make_button(action_text, "ghost", parent=card)
            button.clicked.connect(callback)
            row.addWidget(button, 0, Qt.AlignVCenter)
            layout.addLayout(row)
        note = make_label(
            "ログには URL やエラー内容が含まれる場合があります。共有する前に内容を確認してください。"
            "認証情報は自動的に伏字化されますが、完全な秘匿を保証するものではありません。",
            "caption",
            wrap=True,
        )
        layout.addWidget(note)
        self._column.addWidget(card)

    # ------------------------------------------------------------- rendering
    def _render_environment(self) -> None:
        while self.env_grid.count():
            item = self.env_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        report = environment_report(self.ctx.ffmpeg, self.ctx.paths)
        for row, (key, value) in enumerate(report.items()):
            label = make_label(key, "caption")
            label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            if "\\" in value:
                # Long Windows paths do not wrap at sensible points, so elide
                # them instead of forcing the whole diagnostics page wider than
                # the window at its minimum size.
                value_label: QLabel = ElidedLabel(value, self)
                value_label.setProperty("role", "secondary")
                value_label.setProperty("path", True)
                value_label.setMinimumWidth(160)
            else:
                value_label = make_label(value, "secondary", wrap=True)
                value_label.setMinimumWidth(80)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.env_grid.addWidget(label, row, 0)
            self.env_grid.addWidget(value_label, row, 1)
        self._update_env_badge()
        import yt_dlp

        self.current_version.setText(getattr(yt_dlp.version, "__version__", "unknown"))

    def _update_env_badge(self) -> None:
        ffmpeg = self.ctx.ffmpeg
        palette = current_palette()
        if ffmpeg.available and ffmpeg.version:
            self.env_badge.setText("FFmpeg 検出済み")
            self.env_badge.setStyleSheet(
                f"background-color: {palette.success_soft}; color: {palette.success};"
            )
        else:
            self.env_badge.setText("FFmpeg 未検出")
            self.env_badge.setStyleSheet(
                f"background-color: {palette.warning_soft}; color: {palette.warning};"
            )

    def _load_logs(self) -> None:
        text = read_log_tail(self.ctx.paths.log_file, 700)
        if not text:
            handler = get_memory_handler()
            if handler is not None and handler.records:
                text = "\n".join(handler.records[-700:])
        if not text:
            text = "ログはまだありません。"
        self.log_view.setPlainText(text)
        cursor = self.log_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)

    def _refresh_ffmpeg(self) -> None:
        info: FFmpegInfo = self.ctx.refresh_ffmpeg()
        self._render_environment()
        self._load_logs()
        if info.available:
            self._toast("FFmpeg を検出しました", info.status_label(), "success")
        else:
            self._toast(
                "FFmpeg が見つかりません",
                "同梱の tools/ffmpeg を確認するか、設定で場所を指定してください。",
                "warning",
            )

    # --------------------------------------------------------------- updates
    def _auto_check(self) -> None:
        if self._auto_checked:
            return
        self._auto_checked = True
        self._check_updates()

    def _check_updates(self) -> None:
        if self._check_thread is not None and self._check_thread.isRunning():
            return
        self.check_button.setEnabled(False)
        self.spinner.start()
        self.update_status.setText("最新バージョンを確認しています…")
        self.update_badge.setText("確認中")
        thread = CheckThread(self)
        thread.finished_check.connect(self._on_check_finished)
        thread.finished.connect(thread.deleteLater)
        self._check_thread = thread
        thread.start()

    def _on_check_finished(self, result: object) -> None:
        self._check_thread = None
        self.spinner.stop()
        self.check_button.setEnabled(True)
        if not isinstance(result, UpdateCheck):
            self.update_status.setText("更新情報を取得できませんでした。")
            self.update_badge.setText("失敗")
            return
        self._last_check = result
        self.latest_version.setText(result.latest or "—")
        if result.error:
            self.update_status.setText(result.error)
            self.update_badge.setText("確認できません")
            self._set_badge("warning")
            self.install_button.setEnabled(False)
            return
        if result.newer_available:
            self.update_status.setText("新しいバージョンがあります。更新するとサイト対応が改善されます。")
            self.update_badge.setText("更新あり")
            self._set_badge("accent")
            self.install_button.setEnabled(True)
        else:
            self.update_status.setText("最新バージョンを使用しています。")
            self.update_badge.setText("最新")
            self._set_badge("success")
            self.install_button.setEnabled(False)

    def _set_badge(self, tone: str) -> None:
        color, soft = tone_colors(tone)
        self.update_badge.setStyleSheet(f"background-color: {soft}; color: {color};")

    def _install_update(self) -> None:
        if self._install_thread is not None and self._install_thread.isRunning():
            return
        self.install_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.spinner.start()
        self.update_status.setText("yt-dlp を更新しています。しばらくお待ちください…")
        thread = InstallThread(self)
        thread.finished_install.connect(self._on_install_finished)
        thread.finished.connect(thread.deleteLater)
        self._install_thread = thread
        thread.start()

    def _on_install_finished(self, ok: bool, message: str) -> None:
        self._install_thread = None
        self.spinner.stop()
        self.check_button.setEnabled(True)
        self.update_status.setText(message)
        if ok:
            self.update_badge.setText("更新しました")
            self._set_badge("success")
            self._toast("yt-dlp を更新しました", "反映するには Vela を再起動してください。", "success")
            self._load_logs()
            self._render_environment()
        else:
            self.update_badge.setText("更新失敗")
            self._set_badge("danger")
            self.install_button.setEnabled(True)
            self._toast("yt-dlp を更新できませんでした", message, "error")

    # ---------------------------------------------------------------- report
    def _report_text(self) -> str:
        report = environment_report(self.ctx.ffmpeg, self.ctx.paths)
        lines = [f"Vela {__version__} 診断レポート", ""]
        for key, value in report.items():
            lines.append(f"{key}: {value}")
        if self._last_check is not None:
            lines.append("")
            lines.append(
                f"yt-dlp 更新確認: 現在 {self._last_check.current} / 最新 {self._last_check.latest or '不明'}"
                + (f" ({self._last_check.error})" if self._last_check.error else "")
            )
        lines.append("")
        lines.append("---- 最近のログ ----")
        lines.append(read_log_tail(self.ctx.paths.log_file, 200) or "(ログなし)")
        return "\n".join(lines)

    def _copy_report(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self._report_text())
        self._toast(
            "診断情報をコピーしました",
            "問題を報告する際に貼り付けてください。内容に個人情報が含まれていないか確認してください。",
            "success",
        )

    def _open_log_folder(self) -> None:
        folder = self.ctx.paths.logs_dir
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ---------------------------------------------------------------- theming
    def refresh_theme(self) -> None:
        refresh_named_icons(self)
        # Environment values do not change with a theme.  Rebuild only the
        # small badge instead of deleting and recreating the whole grid.
        self._update_env_badge()
        if self._last_check is not None:
            if self._last_check.error:
                self._set_badge("warning")
            elif self._last_check.newer_available:
                self._set_badge("accent")
            else:
                self._set_badge("success")
        self.update()

    def shutdown(self, timeout_ms: int = 2200) -> None:
        self._auto_check_timer.stop()
        for thread in (self._check_thread, self._install_thread):
            if thread is None or not thread.isRunning():
                continue
            thread.requestInterruption()
            if not thread.wait(timeout_ms):
                logger.warning("診断スレッドを停止できませんでした。終了を強制します。")
                thread.terminate()
                thread.wait(600)
        self._check_thread = None
        self._install_thread = None
