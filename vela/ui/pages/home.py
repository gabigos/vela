from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontMetrics, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import Diagnosis, classify_error
from ...core.formats import build_format_options, default_option, describe_option, find_option
from ...core.models import FormatOption, PlaylistEntry, QueueItem, VideoInfo
from ...core.security import validate_url
from ...core.settings import validate_save_dir
from ...core.utils import (
    human_count,
    human_duration,
)
from ..context import AppContext
from ..theme import current_palette
from ..thumbnail import ThumbnailWidget
from ..widgets import (
    Card,
    ElidedLabel,
    FlowWidget,
    MessageBanner,
    SegmentedControl,
    Spinner,
    add_shadow,
    fade_in,
    make_button,
    make_divider,
    make_icon_button,
    make_label,
    refresh_named_icons,
    set_named_icon,
    shake,
)

logger = logging.getLogger(__name__)

SUPPORTED_SITES = (
    "YouTube",
    "Vimeo",
    "X / Twitter",
    "TikTok",
    "Instagram",
    "Twitch",
    "Dailymotion",
    "ニコニコ動画",
    "Bandcamp",
    "SoundCloud",
    "Archive.org",
    "ほか 1,700 以上のサイト",
)


class AnalyzeThread(QThread):
    succeeded = Signal(object, int)
    failed = Signal(object, int)
    status = Signal(str, int)

    def __init__(self, analyzer, url: str, generation: int, parent=None) -> None:
        super().__init__(parent)
        self._analyzer = analyzer
        self._url = url
        self._generation = generation
        self._cancelled = threading.Event()

    def request_cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            info = self._analyzer.analyze(
                self._url,
                status_callback=lambda message: self._emit_status(message),
            )
            if not self._cancelled.is_set():
                self.succeeded.emit(info, self._generation)
        except Exception as exc:  # noqa: BLE001 - classified in the UI
            if not self._cancelled.is_set():
                self.failed.emit(exc, self._generation)

    def _emit_status(self, message: str) -> None:
        if not self._cancelled.is_set():
            self.status.emit(message, self._generation)


class UrlLineEdit(QLineEdit):
    urlDropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            self._set_drag_active(True)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        text = ""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.scheme() in ("http", "https"):
                    text = url.toString()
                    break
        if not text and event.mimeData().hasText():
            text = event.mimeData().text().strip()
        if text:
            self.setText(text)
            self.urlDropped.emit(text)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class HomePage(QWidget):
    def __init__(
        self,
        ctx: AppContext,
        *,
        navigate: Callable[[str], None],
        apply_settings: Callable[[dict], object],
        open_logs: Callable[[], None],
        toast: Callable[..., None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._navigate = navigate
        self._apply_settings = apply_settings
        self._open_logs = open_logs
        self._toast = toast
        self._generation = 0
        self._threads: set[AnalyzeThread] = set()
        self._current_thread: AnalyzeThread | None = None
        self._video: VideoInfo | None = None
        self._options: list[FormatOption] = []
        self._selected_option: FormatOption | None = None
        self._selected_key = "best"
        self._format_table: QTableWidget | None = None
        self._format_updating = False
        self._table_wrap: QWidget | None = None
        self._format_segment: SegmentedControl | None = None
        self._summary_label: QLabel | None = None
        self._format_note: QLabel | None = None
        self._ffmpeg_warning: QWidget | None = None
        self._download_button: QPushButton | None = None
        self._save_label: ElidedLabel | None = None
        self._playlist_quality: SegmentedControl | None = None
        self._playlist_table: QTableWidget | None = None
        self._playlist_select_all: QCheckBox | None = None
        self._playlist_download_button: QPushButton | None = None
        self._playlist_count_label: QLabel | None = None
        self._playlist_info: VideoInfo | None = None
        self._playlist_updating = False
        self._thumb_widgets: dict[str, list[ThumbnailWidget]] = {}
        self._current_diagnosis: Diagnosis | None = None
        self._build_ui()
        ctx.thumbnails.loaded.connect(self._on_thumbnail_loaded)
        ctx.thumbnails.failed.connect(self._on_thumbnail_failed)
        self.analyze_button.clicked.connect(self._start_analysis)
        self.paste_button.clicked.connect(self._paste_clipboard)
        self.clear_button.clicked.connect(self._clear_url)
        self.url_input.returnPressed.connect(self._start_analysis)
        self.url_input.textChanged.connect(self._clear_inline_error)
        self.url_input.urlDropped.connect(lambda _text: self._start_analysis())
        self.url_input.textChanged.connect(self._on_url_changed)
        self._on_url_changed(self.url_input.text())

    # ------------------------------------------------------------------ UI
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
        center = QWidget(body)
        center_layout = QHBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        column = QWidget(center)
        column.setMaximumWidth(1120)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._column_layout = QVBoxLayout(column)
        self._column_layout.setContentsMargins(0, 0, 0, 0)
        self._column_layout.setSpacing(20)
        center_layout.addStretch(1)
        center_layout.addWidget(column, 30)
        center_layout.addStretch(1)
        body_layout.addWidget(center, 0, Qt.AlignTop)
        self._column = column

        hero = QWidget(column)
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(2, 4, 2, 0)
        hero_layout.setSpacing(10)
        eyebrow = make_label("UNIVERSAL VIDEO DOWNLOADER", "eyebrow")
        self._hero_title = QLabel(column)
        self._hero_title.setProperty("role", "display")
        self._hero_title.setTextFormat(Qt.TextFormat.RichText)
        self._hero_title.setWordWrap(True)
        self._update_hero_title()
        subtitle = make_label(
            "URL を貼り付けるだけ。幅広いサイトに対応し、最高画質から音声のみまで選べます。",
            "secondary",
            wrap=True,
        )
        subtitle.setMaximumWidth(720)
        hero_layout.addWidget(eyebrow)
        hero_layout.addWidget(self._hero_title)
        hero_layout.addWidget(subtitle)
        self._column_layout.addWidget(hero)

        self.url_card = Card(column)
        url_layout = QVBoxLayout(self.url_card)
        url_layout.setContentsMargins(18, 16, 18, 14)
        url_layout.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        link_icon = QLabel(self.url_card)
        set_named_icon(link_icon, "link", color="muted", size=20)
        row.addWidget(link_icon)
        self.url_input = UrlLineEdit(self.url_card)
        self.url_input.setObjectName("urlInput")
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url_input.setAccessibleName("動画の URL")
        self.url_input.setMinimumHeight(48)
        row.addWidget(self.url_input, 1)
        self.clear_button = make_icon_button("x", "入力をクリア", size=15, parent=self.url_card)
        self.clear_button.setFixedSize(32, 32)
        row.addWidget(self.clear_button)
        self.paste_button = make_button(
            "貼り付け", "secondary", icon_name="clipboard", parent=self.url_card
        )
        self.paste_button.setMinimumHeight(42)
        row.addWidget(self.paste_button)
        self.analyze_button = make_button(
            "解析", "primary", icon_name="arrow-right", parent=self.url_card
        )
        self.analyze_button.setMinimumHeight(42)
        self.analyze_button.setMinimumWidth(104)
        row.addWidget(self.analyze_button)
        url_layout.addLayout(row)
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(2, 0, 2, 0)
        hint_row.setSpacing(14)
        hint_row.addWidget(make_label("Ctrl+V で貼り付け", "caption"))
        hint_row.addWidget(make_label("Ctrl+Enter で解析", "caption"))
        hint_row.addStretch(1)
        hint_row.addWidget(make_label("ドラッグ＆ドロップにも対応", "caption"))
        url_layout.addLayout(hint_row)
        self._inline_error = make_label("", "danger", wrap=True)
        self._inline_error.setVisible(False)
        url_layout.addWidget(self._inline_error)
        self._column_layout.addWidget(self.url_card)
        add_shadow(self.url_card, blur=38, alpha=42, y_offset=10)

        self._hero_extra = QWidget(column)
        extra_layout = QVBoxLayout(self._hero_extra)
        extra_layout.setContentsMargins(0, 2, 0, 0)
        extra_layout.setSpacing(16)
        features = QHBoxLayout()
        features.setSpacing(12)
        features.addWidget(
            self._feature_card("sparkles", "高画質をそのまま", "8K までの映像と音声を、必要に応じて結合して保存します。")
        )
        features.addWidget(
            self._feature_card("layers", "まとめて管理", "プレイリストや複数の URL をキューで一括管理できます。")
        )
        features.addWidget(
            self._feature_card("shield", "安全なローカル処理", "履歴や設定は端末内に保存。不要な送信は行いません。")
        )
        extra_layout.addLayout(features)
        sites_card = QFrame(self._hero_extra)
        sites_card.setProperty("role", "inset")
        sites_layout = QVBoxLayout(sites_card)
        sites_layout.setContentsMargins(14, 12, 14, 14)
        sites_layout.setSpacing(9)
        sites_layout.addWidget(make_label("yt-dlp が対応するサイトの例", "caption"))
        chips = FlowWidget(sites_card, spacing=7)
        flow = chips.flow
        for site in SUPPORTED_SITES:
            label = make_label(site, "pill")
            label.setContentsMargins(0, 0, 0, 0)
            flow.addWidget(label)
        sites_layout.addWidget(chips)
        extra_layout.addWidget(sites_card)
        self._column_layout.addWidget(self._hero_extra)

        self.loading_card = Card(column)
        loading_layout = QHBoxLayout(self.loading_card)
        loading_layout.setContentsMargins(20, 20, 20, 20)
        loading_layout.setSpacing(16)
        self.spinner = Spinner(self.loading_card, size=28)
        loading_layout.addWidget(self.spinner, 0, Qt.AlignVCenter)
        loading_text = QVBoxLayout()
        loading_text.setSpacing(3)
        loading_text.addWidget(make_label("動画情報を取得しています", "h3"))
        self.loading_status = make_label("URL を確認しています", "caption")
        loading_text.addWidget(self.loading_status)
        loading_layout.addLayout(loading_text, 1)
        self.cancel_analysis_button = make_button(
            "中止", "ghost", icon_name="x", parent=self.loading_card
        )
        self.cancel_analysis_button.clicked.connect(self._cancel_analysis)
        loading_layout.addWidget(self.cancel_analysis_button)
        self.loading_card.hide()
        self._column_layout.addWidget(self.loading_card)

        self.error_banner = MessageBanner(column)
        self.error_banner.action_clicked.connect(self._open_logs)
        self.error_banner.hide()
        self._column_layout.addWidget(self.error_banner)

        self.result_host = QWidget(column)
        self.result_layout = QVBoxLayout(self.result_host)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(18)
        self.result_host.hide()
        self._column_layout.addWidget(self.result_host)

        footer = QWidget(column)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(2, 4, 2, 0)
        footer_layout.setSpacing(7)
        shield = QLabel(footer)
        set_named_icon(shield, "shield", color="muted", size=14)
        footer_layout.addWidget(shield)
        footer_layout.addWidget(
            make_label(
                "ダウンロードする権利のあるコンテンツのみを保存してください。DRM の解除は行いません。",
                "caption",
                wrap=True,
            ),
            1,
        )
        self._column_layout.addWidget(footer)
        self._column_layout.addStretch(1)
        self._set_busy(False)

    def _update_hero_title(self) -> None:
        accent = current_palette().accent
        self._hero_title.setText(
            f'動画を、<span style="color:{accent}">あなたのライブラリへ。</span>'
        )

    def _feature_card(self, icon_name: str, title: str, description: str) -> Card:
        card = Card(self)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(12)
        badge = QLabel(card)
        badge.setProperty("role", "featureIcon")
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignCenter)
        set_named_icon(badge, icon_name, color="accent", size=19)
        layout.addWidget(badge, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(make_label(title, "h3"))
        desc = make_label(description, "caption", wrap=True)
        text.addWidget(desc)
        layout.addLayout(text, 1)
        return card

    # ------------------------------------------------------------- analysis
    def _set_busy(self, busy: bool) -> None:
        self.analyze_button.setEnabled(not busy)
        self.paste_button.setEnabled(not busy)
        self.url_input.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
        self.analyze_button.setText("解析中…" if busy else "解析")
        self.loading_card.setVisible(busy)
        if busy:
            self.spinner.start()
            self.error_banner.hide()
            fade_in(self.loading_card, duration=150)
        else:
            self.spinner.stop()

    def _on_url_changed(self, text: str) -> None:
        self.clear_button.setVisible(bool(text.strip()))
        self._clear_inline_error()

    def _clear_inline_error(self) -> None:
        if self._inline_error.isVisible():
            self._inline_error.hide()
            self.url_input.setProperty("invalid", False)
            self.url_input.style().unpolish(self.url_input)
            self.url_input.style().polish(self.url_input)

    def _show_inline_error(self, message: str) -> None:
        self._inline_error.setText(message)
        self._inline_error.show()
        self.url_input.setProperty("invalid", True)
        self.url_input.style().unpolish(self.url_input)
        self.url_input.style().polish(self.url_input)
        shake(self.url_card)
        self.url_input.setFocus()

    def _start_analysis(self) -> None:
        if self._current_thread is not None and self._current_thread.isRunning():
            return
        raw = self.url_input.text().strip()
        validation = validate_url(raw)
        if not validation:
            self._show_inline_error(validation.message)
            return
        self._clear_inline_error()
        self._generation += 1
        generation = self._generation
        self._set_busy(True)
        self.loading_status.setText("URL を確認しています")
        self.result_host.hide()
        self.error_banner.hide()
        self._hero_extra.show()
        self._video = None
        self._playlist_info = None
        self._current_diagnosis = None
        thread = AnalyzeThread(self.ctx.analyzer, validation.url, generation, self)
        thread.status.connect(self._on_analysis_status)
        thread.succeeded.connect(self._on_analysis_succeeded)
        thread.failed.connect(self._on_analysis_failed)
        thread.finished.connect(self._on_analysis_thread_finished)
        self._threads.add(thread)
        self._current_thread = thread
        thread.start()
        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.loading_card, 0, 24))

    def _cancel_analysis(self) -> None:
        self._generation += 1
        if self._current_thread is not None:
            self._current_thread.request_cancel()
        self._set_busy(False)
        self.loading_card.hide()
        self._toast("解析を中止しました", "URL を変更して、もう一度お試しください。", "info")

    def _on_analysis_status(self, message: str, generation: int) -> None:
        if generation == self._generation:
            self.loading_status.setText(message)

    def _on_analysis_succeeded(self, info: object, generation: int) -> None:
        if generation != self._generation or not isinstance(info, VideoInfo):
            return
        self._set_busy(False)
        self._video = info
        self._current_diagnosis = None
        self._hero_extra.hide()
        self.error_banner.hide()
        self._render_result(info)
        self.result_host.show()
        fade_in(self.result_host, duration=190)
        QTimer.singleShot(80, lambda: self.scroll.ensureWidgetVisible(self.result_host, 0, 40))
        logger.info("解析結果を表示しました: %s", info.title)

    def _on_analysis_failed(self, error: object, generation: int) -> None:
        if generation != self._generation:
            return
        self._set_busy(False)
        diagnosis = classify_error(error if isinstance(error, BaseException) else str(error), stage="analysis")
        self._current_diagnosis = diagnosis
        self.error_banner.show_message(
            "error",
            diagnosis.title,
            diagnosis.summary,
            diagnosis.remedy,
            "ログを開く",
        )
        self._hero_extra.show()
        self.result_host.hide()
        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.error_banner, 0, 24))

    def _on_analysis_thread_finished(self) -> None:
        thread = self.sender()
        if isinstance(thread, AnalyzeThread):
            self._threads.discard(thread)
            if thread is self._current_thread:
                self._current_thread = None
                if self.loading_card.isVisible():
                    self._set_busy(False)
            thread.deleteLater()

    # -------------------------------------------------------------- results
    def _clear_result(self) -> None:
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._thumb_widgets.clear()
        self._format_table = None
        self._format_updating = False
        self._table_wrap = None
        self._format_segment = None
        self._summary_label = None
        self._format_note = None
        self._ffmpeg_warning = None
        self._download_button = None
        self._save_label = None
        self._playlist_table = None
        self._playlist_quality = None
        self._playlist_download_button = None
        self._playlist_count_label = None
        self._playlist_info = None
        self._playlist_select_all = None

    def _render_result(self, info: VideoInfo) -> None:
        self._clear_result()
        if info.is_playlist:
            self._render_playlist(info)
        else:
            self._render_video(info)

    def _render_video(self, info: VideoInfo) -> None:
        self._options = build_format_options(info)
        selected = find_option(self._options, self._selected_key) or default_option(self._options)
        self._selected_option = selected
        self._playlist_info = None

        video_card = Card(self.result_host)
        video_layout = QHBoxLayout(video_card)
        video_layout.setContentsMargins(18, 18, 18, 18)
        video_layout.setSpacing(20)
        thumb = ThumbnailWidget(video_card)
        thumb.setFixedSize(310, 174)
        self._register_thumbnail(thumb, info.thumbnail)
        video_layout.addWidget(thumb, 0, Qt.AlignTop)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(self._pill(info.display_site))
        if info.duration:
            chips.addWidget(self._pill(human_duration(info.duration)))
        if info.upload_date and len(info.upload_date) == 8:
            chips.addWidget(
                self._pill(f"{info.upload_date[:4]}/{info.upload_date[4:6]}/{info.upload_date[6:]}")
            )
        if info.view_count:
            chips.addWidget(self._pill(f"{human_count(info.view_count)} 回視聴"))
        if info.live_status:
            live = self._pill("ライブ配信")
            live.setStyleSheet(
                f"background-color: {current_palette().warning_soft}; color: {current_palette().warning};"
            )
            chips.addWidget(live)
        chips.addStretch(1)
        info_layout.addLayout(chips)
        title = make_label(info.title, "videoTitle", wrap=True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(title)
        if info.uploader:
            uploader = make_label(info.uploader, "secondary")
            uploader.setTextInteractionFlags(Qt.TextSelectableByMouse)
            info_layout.addWidget(uploader)
        description = info.description.strip()
        if description:
            collapsed = description[:240].replace("\n", " ")
            if len(description) > 240:
                collapsed += "…"
            desc_label = make_label(collapsed, "caption", wrap=True)
            desc_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            toggle = make_button("説明を表示", "link", parent=video_card)
            expanded = {"value": False}

            def toggle_description() -> None:
                expanded["value"] = not expanded["value"]
                desc_label.setText(
                    description.replace("\n", " ") if expanded["value"] else collapsed
                )
                toggle.setText("説明を閉じる" if expanded["value"] else "説明を表示")

            toggle.clicked.connect(toggle_description)
            info_layout.addWidget(desc_label)
            info_layout.addWidget(toggle, 0, Qt.AlignLeft)
        info_layout.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_page = make_button("元のページを開く", "ghost", icon_name="external", parent=video_card)
        open_page.clicked.connect(lambda: self._open_url(info.webpage_url or info.url))
        actions.addWidget(open_page)
        actions.addStretch(1)
        info_layout.addLayout(actions)
        video_layout.addLayout(info_layout, 1)
        self.result_layout.addWidget(video_card)

        self._render_format_card(info)

    def _render_format_card(self, info: VideoInfo) -> None:
        card = Card(self.result_host)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(make_label("画質と形式", "h2"))
        head.addStretch(1)
        head.addWidget(make_label("利用可能な形式から1つ選択", "caption"))
        layout.addLayout(head)

        segment = SegmentedControl(
            [
                ("best", "最高画質"),
                ("mp4", "MP4"),
                ("audio", "音声のみ"),
                ("custom", "形式を選ぶ"),
            ],
            value=self._segment_value_for(self._selected_option),
            parent=card,
            compact=True,
        )
        segment.changed.connect(self._on_segment_changed)
        self._format_segment = segment
        layout.addWidget(segment)

        summary_box = QFrame(card)
        summary_box.setProperty("role", "inset")
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(3)
        summary_label = make_label("", "secondary", wrap=True)
        summary_layout.addWidget(summary_label)
        note_label = make_label("", "caption", wrap=True)
        summary_layout.addWidget(note_label)
        self._summary_label = summary_label
        self._format_note = note_label
        layout.addWidget(summary_box)

        warning = QWidget(card)
        warning_layout = QHBoxLayout(warning)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.setSpacing(8)
        warning_icon = QLabel(warning)
        set_named_icon(warning_icon, "alert-triangle", color="warning", size=16)
        warning_layout.addWidget(warning_icon, 0, Qt.AlignTop)
        warning_label = make_label(
            "FFmpeg が検出されていません。映像と音声の結合が必要な形式では失敗する場合があります。",
            "warning",
            wrap=True,
        )
        warning_layout.addWidget(warning_label, 1)
        diag_button = make_button("診断", "ghost", parent=warning)
        diag_button.clicked.connect(lambda: self._navigate("diagnostics"))
        warning_layout.addWidget(diag_button)
        warning.hide()
        self._ffmpeg_warning = warning
        layout.addWidget(warning)

        table_wrap = QWidget(card)
        table_layout = QVBoxLayout(table_wrap)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table = QTableWidget(0, 6, table_wrap)
        table.setHorizontalHeaderLabels(
            ["選択", "画質", "形式", "コーデック", "サイズ", "種類"]
        )
        table.verticalHeader().setVisible(False)
        # Only the checkable first column is interactive.  Row/cell clicks
        # must not change the selection or paint a focus rectangle.
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.NoFocus)
        table.setAlternatingRowColors(False)
        table.setMinimumHeight(196)
        table.setMaximumHeight(250)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        table.itemChanged.connect(self._on_format_item_changed)
        table_layout.addWidget(table)
        self._format_table = table
        self._table_wrap = table_wrap
        self._populate_format_table()
        table_wrap.setVisible(self._segment_value_for(self._selected_option) == "custom")
        layout.addWidget(table_wrap)

        layout.addWidget(make_divider(card))
        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        folder = QLabel(card)
        set_named_icon(folder, "folder", color="accent", size=19)
        save_row.addWidget(folder)
        save_text = QVBoxLayout()
        save_text.setSpacing(1)
        save_text.addWidget(make_label("保存先", "caption"))
        self._save_label = ElidedLabel(self._current_save_dir(), card)
        self._save_label.setProperty("role", "secondary")
        self._save_label.setProperty("path", True)
        save_text.addWidget(self._save_label)
        save_row.addLayout(save_text, 1)
        change_dir = make_button("変更", "secondary", parent=card)
        change_dir.clicked.connect(self._choose_save_dir)
        save_row.addWidget(change_dir)
        open_dir = make_icon_button("folder-open", "保存先を開く", size=16, parent=card)
        open_dir.clicked.connect(lambda: self._open_path(self._current_save_dir()))
        save_row.addWidget(open_dir)
        layout.addLayout(save_row)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(make_label("キューに追加して順番に処理します", "caption"), 1)
        download = make_button("ダウンロードを開始", "primary", icon_name="download", parent=card)
        download.setMinimumHeight(42)
        download.setMinimumWidth(200)
        download.clicked.connect(self._download_single)
        self._download_button = download
        bottom.addWidget(download)
        layout.addLayout(bottom)

        self.result_layout.addWidget(card)
        self._apply_format_selection(self._selected_option or default_option(self._options), sync_segment=True)

    def _render_playlist(self, info: VideoInfo) -> None:
        self._playlist_info = info
        self._options = []
        header = Card(self.result_host)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 18, 18, 18)
        header_layout.setSpacing(20)
        thumb = ThumbnailWidget(header)
        thumb.setFixedSize(260, 146)
        self._register_thumbnail(thumb, info.thumbnail)
        header_layout.addWidget(thumb, 0, Qt.AlignTop)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(7)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(self._pill("プレイリスト"))
        chips.addWidget(self._pill(f"{info.playlist_count or len(info.entries)} 本"))
        chips.addStretch(1)
        info_layout.addLayout(chips)
        title = make_label(info.playlist_title or info.title, "videoTitle", wrap=True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(title)
        if info.uploader:
            info_layout.addWidget(make_label(info.uploader, "secondary"))
        info_layout.addWidget(
            make_label(
                "ダウンロードする動画を選択してください。画質は各動画で利用可能な最良の形式を自動選択します。",
                "caption",
                wrap=True,
            )
        )
        if info.entry_limit_reached:
            limit = make_label(
                "一度に取得できる件数の上限（500 件）に達したため、一部のみ表示しています。",
                "warning",
                wrap=True,
            )
            info_layout.addWidget(limit)
        info_layout.addStretch(1)
        open_page = make_button("元のページを開く", "ghost", icon_name="external", parent=header)
        open_page.clicked.connect(lambda: self._open_url(info.webpage_url or info.url))
        info_layout.addWidget(open_page, 0, Qt.AlignLeft)
        header_layout.addLayout(info_layout, 1)
        self.result_layout.addWidget(header)

        card = Card(self.result_host)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(make_label("動画を選択", "h2"))
        top.addStretch(1)
        self._playlist_select_all = QCheckBox("すべて選択", card)
        self._playlist_select_all.setChecked(True)
        self._playlist_select_all.stateChanged.connect(self._toggle_all_playlist)
        top.addWidget(self._playlist_select_all)
        layout.addLayout(top)
        table = QTableWidget(len(info.entries), 4, card)
        table.setHorizontalHeaderLabels(["選択", "タイトル", "時間", "投稿者"])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setMinimumHeight(220)
        table.setMaximumHeight(320)
        header_view = table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        row_height = max(40, QFontMetrics(table.font()).height() + 23)
        for row, entry in enumerate(info.entries):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked)
            table.setItem(row, 0, check)
            title_item = QTableWidgetItem(entry.title)
            title_item.setToolTip(entry.title)
            table.setItem(row, 1, title_item)
            table.setItem(row, 2, QTableWidgetItem(human_duration(entry.duration)))
            table.setItem(row, 3, QTableWidgetItem(entry.uploader or info.uploader or "—"))
            table.setRowHeight(row, row_height)
        table.itemChanged.connect(self._on_playlist_item_changed)
        self._playlist_table = table
        layout.addWidget(table)

        quality_row = QHBoxLayout()
        quality_row.setSpacing(10)
        quality_row.addWidget(make_label("画質", "caption"))
        segment = SegmentedControl(
            [("best", "最高画質"), ("mp4", "MP4"), ("audio", "音声のみ")],
            value="best",
            parent=card,
            compact=True,
        )
        segment.setMaximumWidth(340)
        self._playlist_quality = segment
        quality_row.addWidget(segment, 1)
        layout.addLayout(quality_row)

        layout.addWidget(make_divider(card))
        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        folder = QLabel(card)
        set_named_icon(folder, "folder", color="accent", size=19)
        save_row.addWidget(folder)
        save_text = QVBoxLayout()
        save_text.setSpacing(1)
        save_text.addWidget(make_label("保存先", "caption"))
        self._save_label = ElidedLabel(self._current_save_dir(), card)
        self._save_label.setProperty("role", "secondary")
        self._save_label.setProperty("path", True)
        save_text.addWidget(self._save_label)
        save_row.addLayout(save_text, 1)
        change_dir = make_button("変更", "secondary", parent=card)
        change_dir.clicked.connect(self._choose_save_dir)
        save_row.addWidget(change_dir)
        layout.addLayout(save_row)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self._playlist_count_label = make_label("", "caption")
        bottom.addWidget(self._playlist_count_label, 1)
        download = make_button("選択した動画をダウンロード", "primary", icon_name="download", parent=card)
        download.setMinimumHeight(42)
        download.clicked.connect(self._download_playlist)
        self._playlist_download_button = download
        bottom.addWidget(download)
        layout.addLayout(bottom)
        self.result_layout.addWidget(card)
        self._update_playlist_count()

    # --------------------------------------------------------- format logic
    def _populate_format_table(self) -> None:
        table = self._format_table
        if table is None:
            return
        table.setRowCount(0)
        row_height = max(34, QFontMetrics(table.font()).height() + 17)
        selected_key = self._selected_option.key if self._selected_option else ""
        self._format_updating = True
        try:
            for option in self._options:
                if option.kind == "preset":
                    continue
                row = table.rowCount()
                table.insertRow(row)
                if option.kind == "audio":
                    kind = "音声のみ"
                    quality = option.label.replace("音声のみ（", "").replace("）", "")
                elif option.height:
                    kind = "映像＋音声" if not option.requires_ffmpeg else "映像のみ"
                    quality = option.label
                else:
                    kind = "映像のみ" if option.requires_ffmpeg else "映像＋音声"
                    quality = option.label
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check.setData(Qt.UserRole, option.key)
                check.setCheckState(
                    Qt.Checked if option.key == selected_key else Qt.Unchecked
                )
                table.setItem(row, 0, check)
                items = [
                    quality,
                    (option.ext or "—").upper(),
                    " / ".join(
                        part for part in (option.vcodec, option.acodec) if part
                    )
                    or "—",
                    option.size_text if option.filesize else "—",
                    kind,
                ]
                for column, text in enumerate(items, start=1):
                    item = QTableWidgetItem(text)
                    item.setData(Qt.UserRole, option.key)
                    if column == 2:
                        item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, column, item)
                table.setRowHeight(row, row_height)
        finally:
            self._format_updating = False
        self._sync_format_table()

    def _sync_format_table(self) -> None:
        table = self._format_table
        if table is None:
            return
        selected_key = self._selected_option.key if self._selected_option else ""
        self._format_updating = True
        try:
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is None:
                    continue
                checked = item.data(Qt.UserRole) == selected_key
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        finally:
            self._format_updating = False

    def _segment_value_for(self, option: FormatOption | None) -> str:
        if option is None:
            return "best"
        if option.key == "best":
            return "best"
        if option.key == "mp4":
            return "mp4"
        if option.kind == "audio":
            return "audio"
        return "custom"

    def _on_segment_changed(self, value: str) -> None:
        if value == "custom":
            self._show_table(True)
            detailed = [option for option in self._options if option.kind != "preset"]
            if detailed:
                current = self._selected_option
                if current is None or current.kind == "preset":
                    self._apply_format_selection(detailed[0], sync_segment=False)
                else:
                    self._sync_format_table()
            return
        self._show_table(False)
        if value == "best":
            option = find_option(self._options, "best")
        elif value == "mp4":
            option = find_option(self._options, "mp4")
        else:
            audio_key = {
                "mp3": "audio_mp3",
                "m4a": "audio_m4a",
                "original": "audio_original",
            }.get(self.ctx.settings.audio_format, "audio_original")
            option = find_option(self._options, audio_key) or find_option(
                self._options, "audio_original"
            )
        if option is not None:
            self._apply_format_selection(option, sync_segment=False)

    def _show_table(self, visible: bool) -> None:
        if self._table_wrap is not None:
            self._table_wrap.setVisible(visible)
            if visible:
                self._sync_format_table()

    def _on_format_item_changed(self, item: QTableWidgetItem) -> None:
        if self._format_updating or item.column() != 0:
            return
        table = self._format_table
        if table is None:
            return
        option = find_option(self._options, str(item.data(Qt.UserRole) or ""))
        if option is None:
            return
        # The format table is a single-choice control.  A checkable item can
        # technically be unchecked by the user, so restore the clicked item
        # and clear every other checkbox.
        self._format_updating = True
        try:
            for row in range(table.rowCount()):
                other = table.item(row, 0)
                if other is not None:
                    other.setCheckState(
                        Qt.Checked if other is item else Qt.Unchecked
                    )
        finally:
            self._format_updating = False
        self._apply_format_selection(option, sync_segment=True)

    def _apply_format_selection(self, option: FormatOption, *, sync_segment: bool) -> None:
        self._selected_option = option
        self._selected_key = option.key
        if self._summary_label is not None:
            self._summary_label.setText(f"選択中: {describe_option(option)}")
        if self._format_note is not None:
            bits = [option.note] if option.note else []
            if option.requires_ffmpeg:
                bits.append("FFmpeg で映像と音声を結合します")
            if option.kind == "audio":
                bits.append("音声ファイルのみを保存します")
            self._format_note.setText(" · ".join(bits))
        if sync_segment and self._format_segment is not None:
            self._format_segment.set_value(self._segment_value_for(option), emit=False)
        self._sync_format_table()
        if self._ffmpeg_warning is not None:
            show_warning = bool(option.requires_ffmpeg and not self.ctx.ffmpeg.available)
            self._ffmpeg_warning.setVisible(show_warning)
        if self._download_button is not None:
            missing_audio_ffmpeg = (
                option.kind == "audio"
                and option.audio_format in ("mp3", "m4a")
                and not self.ctx.ffmpeg.available
            )
            self._download_button.setEnabled(not missing_audio_ffmpeg)
            self._download_button.setToolTip(
                "音声変換には FFmpeg が必要です。診断画面を確認してください。"
                if missing_audio_ffmpeg
                else ""
            )

    # ---------------------------------------------------------- download ops
    def _current_save_dir(self) -> str:
        return self.ctx.settings.save_dir

    def _download_single(self) -> None:
        info = self._video
        option = self._selected_option
        if info is None or info.is_playlist or option is None:
            return
        item = QueueItem(
            url=info.webpage_url or info.url,
            title=info.title,
            save_dir=self._current_save_dir(),
            format_selector=option.selector,
            format_label=describe_option(option),
            uploader=info.uploader,
            duration=info.duration,
            extractor=info.display_site,
            thumbnail=info.thumbnail,
            video_id=info.video_id,
            audio_only=option.kind == "audio",
            audio_format=option.audio_format,
            requires_ffmpeg=option.requires_ffmpeg,
        )
        self.ctx.queue.enqueue(item)
        self._toast(
            "キューに追加しました",
            info.title,
            "success",
            action_label="キューを表示",
            action_callback=lambda: self._navigate("queue"),
        )

    def _download_playlist(self) -> None:
        info = self._playlist_info
        table = self._playlist_table
        segment = self._playlist_quality
        if info is None or table is None:
            return
        selected_entries = self._selected_playlist_entries()
        if not selected_entries:
            self._toast("動画が選択されていません", "ダウンロードする動画にチェックを入れてください。", "info")
            return
        quality = segment.selected() if segment else "best"
        if quality == "best":
            key = "best"
        elif quality == "mp4":
            key = "mp4"
        else:
            key = {
                "mp3": "audio_mp3",
                "m4a": "audio_m4a",
                "original": "audio_original",
            }.get(self.ctx.settings.audio_format, "audio_original")
        options = build_format_options(VideoInfo(url=info.url, title=info.title))
        option = find_option(options, key) or default_option(options)
        items: list[QueueItem] = []
        for entry in selected_entries:
            items.append(
                QueueItem(
                    url=entry.url,
                    title=entry.title,
                    save_dir=self._current_save_dir(),
                    format_selector=option.selector,
                    format_label=describe_option(option),
                    uploader=entry.uploader or info.uploader,
                    duration=entry.duration,
                    extractor=info.display_site,
                    thumbnail=entry.thumbnail or info.thumbnail,
                    video_id=entry.video_id,
                    audio_only=option.kind == "audio",
                    audio_format=option.audio_format,
                    requires_ffmpeg=option.requires_ffmpeg,
                    playlist_title=info.playlist_title or info.title,
                )
            )
        self.ctx.queue.enqueue_many(items)
        self._toast(
            f"{len(items)} 件をキューに追加しました",
            info.playlist_title or info.title,
            "success",
            action_label="キューを表示",
            action_callback=lambda: self._navigate("queue"),
        )

    def _selected_playlist_entries(self) -> list[PlaylistEntry]:
        info = self._playlist_info
        table = self._playlist_table
        if info is None or table is None:
            return []
        result: list[PlaylistEntry] = []
        for row in range(min(table.rowCount(), len(info.entries))):
            item = table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                result.append(info.entries[row])
        return result

    def _playlist_checked_count(self) -> int:
        return len(self._selected_playlist_entries())

    def _on_playlist_item_changed(self, item: QTableWidgetItem) -> None:
        if self._playlist_updating or item.column() != 0:
            return
        self._update_playlist_count()

    def _toggle_all_playlist(self, state: int) -> None:
        table = self._playlist_table
        if table is None or self._playlist_updating:
            return
        self._playlist_updating = True
        try:
            check_state = Qt.Checked if state else Qt.Unchecked
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None:
                    item.setCheckState(check_state)
        finally:
            self._playlist_updating = False
        self._update_playlist_count()

    def _update_playlist_count(self) -> None:
        count = self._playlist_checked_count()
        if self._playlist_count_label is not None:
            self._playlist_count_label.setText(f"{count} 件を選択中")
        if self._playlist_download_button is not None:
            self._playlist_download_button.setText(f"選択した {count} 件をダウンロード")
            self._playlist_download_button.setEnabled(count > 0)
        if self._playlist_select_all is not None:
            total = self._playlist_table.rowCount() if self._playlist_table else 0
            desired = count == total and total > 0
            if self._playlist_select_all.isChecked() != desired:
                self._playlist_updating = True
                try:
                    self._playlist_select_all.setChecked(desired)
                finally:
                    self._playlist_updating = False

    # ------------------------------------------------------------- utilities
    def _pill(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "pill")
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _register_thumbnail(self, widget: ThumbnailWidget, url: str) -> None:
        if not url:
            return
        widget.set_url(url)
        cached = self.ctx.thumbnails.load(url)
        if cached is not None:
            widget.set_pixmap(cached)
        self._thumb_widgets.setdefault(url, []).append(widget)

    def _on_thumbnail_loaded(self, url: str, pixmap: QPixmap) -> None:
        for widget in self._thumb_widgets.get(url, []):
            widget.set_pixmap(pixmap)

    def _on_thumbnail_failed(self, url: str) -> None:
        for widget in self._thumb_widgets.get(url, []):
            widget.set_url(url)
            widget.update()

    def _paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if not text:
            self._toast("クリップボードが空です", "URL をコピーしてから貼り付けてください。", "info")
            return
        self.url_input.setText(text)
        self.url_input.setFocus()
        if validate_url(text):
            self._start_analysis()

    def _clear_url(self) -> None:
        self.url_input.clear()
        self._clear_inline_error()
        self.result_host.hide()
        self.error_banner.hide()
        self._hero_extra.show()
        self._video = None
        self._playlist_info = None
        self.url_input.setFocus()

    def _choose_save_dir(self) -> None:
        current = self._current_save_dir()
        directory = QFileDialog.getExistingDirectory(self, "保存先フォルダーを選択", current)
        if not directory:
            return
        ok, message = validate_save_dir(directory)
        if not ok:
            self._toast("保存先を変更できません", message, "error")
            return
        saved = self._apply_settings({"save_dir": str(Path(directory))})
        if saved is not None:
            self._toast("保存先を変更しました", str(Path(directory)), "success")
            if self._save_label is not None:
                self._save_label.setText(str(Path(directory)))

    def _open_url(self, url: str) -> None:
        if not url:
            return
        parsed = validate_url(url, allow_private=True)
        if parsed:
            QDesktopServices.openUrl(QUrl(parsed.url))

    def _open_path(self, path: str) -> None:
        candidate = Path(path) if path else None
        if candidate and candidate.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))

    def refresh_theme(self) -> None:
        self._update_hero_title()
        add_shadow(self.url_card, blur=38, alpha=42, y_offset=10)
        refresh_named_icons(self)
        if self._video is not None:
            # Re-rendering rebuilds the widgets, so preserve any playlist
            # selection/quality the user already made.
            state = self._capture_playlist_state() if self._video.is_playlist else None
            self._render_result(self._video)
            if state is not None:
                self._restore_playlist_state(state)
        elif self._playlist_info is not None:
            state = self._capture_playlist_state()
            self._render_result(self._playlist_info)
            self._restore_playlist_state(state)
        if self._current_diagnosis is not None and self.error_banner.isVisible():
            diagnosis = self._current_diagnosis
            self.error_banner.show_message(
                "error", diagnosis.title, diagnosis.summary, diagnosis.remedy, "ログを開く"
            )

    def _capture_playlist_state(self) -> dict | None:
        table = self._playlist_table
        if table is None or self._playlist_info is None:
            return None
        checked = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            checked.append(item is not None and item.checkState() == Qt.Checked)
        quality = self._playlist_quality.selected() if self._playlist_quality else "best"
        return {"checked": checked, "quality": quality}

    def _restore_playlist_state(self, state: dict | None) -> None:
        if not state:
            return
        table = self._playlist_table
        if table is None:
            return
        self._playlist_updating = True
        try:
            for row, flag in enumerate(state.get("checked") or []):
                item = table.item(row, 0)
                if item is not None:
                    item.setCheckState(Qt.Checked if flag else Qt.Unchecked)
        finally:
            self._playlist_updating = False
        quality = state.get("quality")
        if quality and self._playlist_quality is not None:
            self._playlist_quality.set_value(quality, emit=False)
        self._update_playlist_count()

    def on_settings_changed(self) -> None:
        if self._save_label is not None:
            self._save_label.setText(self._current_save_dir())
        if self._format_segment is not None and self._selected_option is not None:
            self._format_segment.set_value(self._segment_value_for(self._selected_option), emit=False)
        if self._video is not None and not self._video.is_playlist:
            self._render_result(self._video)

    def analyze(self) -> None:
        if self.analyze_button.isEnabled():
            self._start_analysis()

    def focus_url(self, *, paste: bool = False) -> None:
        self.url_input.setFocus()
        self.url_input.selectAll()
        if paste:
            self._paste_clipboard()

    def cancel_analysis(self) -> bool:
        if self.loading_card.isVisible():
            self._cancel_analysis()
            return True
        return False

    def shutdown(self, timeout_ms: int = 3500) -> None:
        threads = list(self._threads)
        for thread in threads:
            thread.request_cancel()
        import time

        start = time.monotonic()
        for thread in threads:
            remaining = max(200, int(timeout_ms - (time.monotonic() - start) * 1000))
            if not thread.wait(remaining):
                logger.warning("解析スレッドを停止できませんでした。終了します。")
                thread.terminate()
                thread.wait(500)
        self._threads.clear()
        self._current_thread = None
