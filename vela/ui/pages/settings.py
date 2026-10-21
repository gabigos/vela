from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.ffmpeg_tools import FFmpegInfo, discover_ffmpeg
from ...core.settings import (
    DEFAULT_FILENAME_TEMPLATE,
    Settings,
    validate_filename_template,
    validate_proxy,
    validate_save_dir,
)
from ...core.utils import human_size
from ..context import AppContext
from ..dialogs import ConfirmDialog
from ..icons import icon
from ..theme import ACCENT_LABELS, ACCENTS, current_palette
from ..widgets import (
    Card,
    ElidedLabel,
    SegmentedControl,
    Stepper,
    Switch,
    fade_in,
    make_button,
    make_divider,
    make_icon_button,
    make_label,
    refresh_named_icons,
    tone_colors,
)

logger = logging.getLogger(__name__)


class ColorSwatch(QAbstractButton):
    def __init__(self, name: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setCheckable(True)
        self.setFixedSize(38, 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(ACCENT_LABELS.get(name, name))
        self.setAccessibleName(f"アクセントカラー: {ACCENT_LABELS.get(name, name)}")
        self.setFocusPolicy(Qt.StrongFocus)

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = QRectF(self.rect()).center()
        if self.isChecked():
            painter.setPen(QPen(QColor(palette.text), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, 17, 17)
        elif self.hasFocus():
            painter.setPen(QPen(QColor(palette.accent), 1.5, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, 17, 17)
        elif self.underMouse():
            painter.setPen(QPen(QColor(palette.accent_border), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, 17, 17)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(center, 12, 12)
        if self.isChecked():
            painter.setPen(QPen(QColor("#FFFFFF"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(int(center.x() - 5), int(center.y()), int(center.x() - 1), int(center.y() + 4))
            painter.drawLine(int(center.x() - 1), int(center.y() + 4), int(center.x() + 6), int(center.y() - 4))
        painter.end()


class SettingsPage(QWidget):
    def __init__(
        self,
        ctx: AppContext,
        *,
        apply_settings: Callable[[dict], object],
        open_logs: Callable[[], None],
        toast: Callable[..., None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._apply_settings = apply_settings
        self._open_logs = open_logs
        self._toast = toast
        self._loading = False
        self._section_badges: list[tuple[QLabel, str]] = []
        self._saved_timer = QTimer(self)
        self._saved_timer.setSingleShot(True)
        self._saved_timer.setInterval(1800)
        self._saved_timer.timeout.connect(self._reset_saved_label)
        self._build_ui()
        self._sync_from_settings()
        self._render_ffmpeg(self.ctx.ffmpeg)

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
        column.setMaximumWidth(1020)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._column = QVBoxLayout(column)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(18)
        wrap_layout.addStretch(1)
        wrap_layout.addWidget(column, 30)
        wrap_layout.addStretch(1)
        body_layout.addWidget(wrap, 0, Qt.AlignTop)

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(3)
        header_text.addWidget(make_label("設定", "h1"))
        header_text.addWidget(make_label("見た目とダウンロードの動作をカスタマイズします。", "secondary"))
        header.addLayout(header_text, 1)
        self.saved_label = make_label("変更は自動的に保存されます", "caption")
        header.addWidget(self.saved_label, 0, Qt.AlignBottom)
        self._column.addLayout(header)

        self._build_appearance()
        self._build_downloads()
        self._build_network()
        self._build_history()
        self._build_advanced()
        self._build_reset()
        self._column.addStretch(1)

    def _section(self, icon_name: str, title: str, description: str) -> tuple[Card, QVBoxLayout]:
        card = Card(self)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(12)
        badge = QLabel(card)
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignCenter)
        color, soft = tone_colors("accent")
        badge.setStyleSheet(f"background-color: {soft}; border-radius: 10px;")
        badge.setPixmap(icon(icon_name, color, 19).pixmap(19, 19))
        self._section_badges.append((badge, icon_name))
        head.addWidget(badge, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(make_label(title, "h2"))
        text.addWidget(make_label(description, "caption", wrap=True))
        head.addLayout(text, 1)
        outer.addLayout(head)
        outer.addWidget(make_divider(card))
        content = QVBoxLayout()
        content.setSpacing(14)
        outer.addLayout(content)
        self._column.addWidget(card)
        return card, content

    def _row(self, title: str, description: str, control: QWidget, parent: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(make_label(title, "h3"))
        caption = make_label(description, "caption", wrap=True)
        text.addWidget(caption)
        row.addLayout(text, 1)
        control.setParent(parent)
        row.addWidget(control, 0, Qt.AlignVCenter)
        return row

    # ------------------------------------------------------------- appearance
    def _build_appearance(self) -> None:
        _card, content = self._section(
            "palette", "外観", "テーマとアクセントカラーは即座に反映されます。"
        )
        theme_row = QHBoxLayout()
        theme_text = QVBoxLayout()
        theme_text.setSpacing(2)
        theme_text.addWidget(make_label("テーマ", "h3"))
        theme_text.addWidget(make_label("システムに合わせるか、ダーク・ライトを固定できます。", "caption"))
        theme_row.addLayout(theme_text, 1)
        self.theme_control = SegmentedControl(
            [("system", "システム"), ("dark", "ダーク"), ("light", "ライト")],
            value=self.ctx.settings.theme,
            compact=True,
            icon_names={"system": "monitor", "dark": "moon", "light": "sun"},
        )
        self.theme_control.setMaximumWidth(360)
        self.theme_control.changed.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_control, 0, Qt.AlignVCenter)
        content.addLayout(theme_row)

        accent_row = QHBoxLayout()
        accent_text = QVBoxLayout()
        accent_text.setSpacing(2)
        accent_text.addWidget(make_label("アクセントカラー", "h3"))
        accent_text.addWidget(make_label("ボタンや進捗バーなどの強調色を選びます。", "caption"))
        accent_row.addLayout(accent_text, 1)
        swatches = QWidget()
        swatches_layout = QHBoxLayout(swatches)
        swatches_layout.setContentsMargins(0, 0, 0, 0)
        swatches_layout.setSpacing(6)
        self._accent_group = QButtonGroup(self)
        self._accent_group.setExclusive(True)
        self._swatches: dict[str, ColorSwatch] = {}
        mode = current_palette().mode
        for name in ACCENTS:
            color = ACCENTS[name][mode][0]
            swatch = ColorSwatch(name, color, swatches)
            swatch.clicked.connect(lambda _checked=False, value=name: self._on_accent_changed(value))
            self._accent_group.addButton(swatch)
            self._swatches[name] = swatch
            swatches_layout.addWidget(swatch)
        accent_row.addWidget(swatches, 0, Qt.AlignVCenter)
        content.addLayout(accent_row)

        self.animations_switch = Switch(checked=self.ctx.settings.animations)
        self.animations_switch.toggled.connect(self._on_animations_toggled)
        content.addLayout(
            self._row(
                "アニメーション",
                "画面遷移や通知の動きを有効にします。動作を軽くしたい場合はオフにしてください。",
                self.animations_switch,
                _card,
            )
        )

    # -------------------------------------------------------------- downloads
    def _build_downloads(self) -> None:
        card, content = self._section(
            "download", "ダウンロード", "保存先、ファイル形式、同時実行数などを設定します。"
        )
        folder_box = QWidget(card)
        folder_layout = QHBoxLayout(folder_box)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(8)
        self.save_dir_label = ElidedLabel(self.ctx.settings.save_dir, folder_box)
        self.save_dir_label.setProperty("role", "secondary")
        self.save_dir_label.setProperty("path", True)
        self.save_dir_label.setMinimumWidth(260)
        folder_layout.addWidget(self.save_dir_label, 1)
        choose = make_button("変更", "secondary", parent=folder_box)
        choose.clicked.connect(self._choose_save_dir)
        folder_layout.addWidget(choose)
        open_dir = make_icon_button("folder-open", "保存先を開く", size=16, parent=folder_box)
        open_dir.clicked.connect(self._open_save_dir)
        folder_layout.addWidget(open_dir)
        content.addLayout(
            self._row(
                "保存先フォルダー",
                "ダウンロードしたファイルを保存する場所です。",
                folder_box,
                card,
            )
        )

        self.template_input = QLineEdit(card)
        self.template_input.setMinimumWidth(360)
        self.template_input.setPlaceholderText(DEFAULT_FILENAME_TEMPLATE)
        self.template_input.setAccessibleName("ファイル名テンプレート")
        self.template_input.editingFinished.connect(self._commit_template)
        template_box = QWidget(card)
        template_layout = QVBoxLayout(template_box)
        template_layout.setContentsMargins(0, 0, 0, 0)
        template_layout.setSpacing(4)
        template_layout.addWidget(self.template_input)
        template_layout.addWidget(
            make_label(
                "例: %(title).150B [%(id)s].%(ext)s  ·  %(ext)s は必須です",
                "caption",
                wrap=True,
            )
        )
        content.addLayout(
            self._row(
                "ファイル名",
                "yt-dlp の出力テンプレートを使用できます。パス区切り文字は使用できません。",
                template_box,
                card,
            )
        )

        self.container_control = SegmentedControl(
            [("auto", "自動"), ("mp4", "MP4"), ("mkv", "MKV")],
            value=self.ctx.settings.container,
            compact=True,
        )
        self.container_control.setMaximumWidth(300)
        self.container_control.changed.connect(lambda value: self._commit({"container": value}))
        content.addLayout(
            self._row(
                "コンテナ形式",
                "映像と音声を結合するときの形式です。「自動」はサイトの配信形式に従います。",
                self.container_control,
                card,
            )
        )

        self.overwrite_control = SegmentedControl(
            [("rename", "連番を付ける"), ("overwrite", "上書き"), ("skip", "スキップ")],
            value=self.ctx.settings.overwrite,
            compact=True,
        )
        self.overwrite_control.setMaximumWidth(360)
        self.overwrite_control.changed.connect(lambda value: self._commit({"overwrite": value}))
        content.addLayout(
            self._row(
                "同名ファイル",
                "同じ名前のファイルがすでにある場合の動作を選びます。",
                self.overwrite_control,
                card,
            )
        )

        self.concurrency_stepper = Stepper(1, 6, self.ctx.settings.concurrency, suffix="件", parent=card)
        self.concurrency_stepper.valueChanged.connect(
            lambda value: self._commit({"concurrency": value})
        )
        content.addLayout(
            self._row(
                "同時ダウンロード数",
                "回線やサイトの制限に合わせて調整してください。増やすと失敗しやすくなる場合があります。",
                self.concurrency_stepper,
                card,
            )
        )

        self.rate_stepper = Stepper(
            0,
            1000,
            self.ctx.settings.rate_limit_mbps,
            step=5,
            suffix="Mbps（0 で無制限）",
            parent=card,
        )
        self.rate_stepper.valueChanged.connect(
            lambda value: self._commit({"rate_limit_mbps": value})
        )
        content.addLayout(
            self._row(
                "速度制限",
                "1 本あたりの最大ダウンロード速度を制限します。",
                self.rate_stepper,
                card,
            )
        )

        self.audio_control = SegmentedControl(
            [("mp3", "MP3"), ("m4a", "M4A"), ("original", "元の形式")],
            value=self.ctx.settings.audio_format,
            compact=True,
        )
        self.audio_control.setMaximumWidth(340)
        self.audio_control.changed.connect(lambda value: self._commit({"audio_format": value}))
        content.addLayout(
            self._row(
                "音声のみの形式",
                "音声のみを選んだときの保存形式です。MP3 / M4A への変換には FFmpeg を使用します。",
                self.audio_control,
                card,
            )
        )

    # ---------------------------------------------------------------- network
    def _build_network(self) -> None:
        card, content = self._section(
            "globe", "ネットワークと認証", "プロキシや Cookie ファイルを必要な場合のみ設定します。"
        )
        self.proxy_input = QLineEdit(card)
        self.proxy_input.setPlaceholderText("http://127.0.0.1:8080")
        self.proxy_input.setMinimumWidth(380)
        self.proxy_input.setAccessibleName("プロキシ URL")
        self.proxy_input.editingFinished.connect(self._commit_proxy)
        content.addLayout(
            self._row(
                "プロキシ",
                "HTTP / HTTPS / SOCKS5 に対応しています。空欄の場合は直接接続します。",
                self.proxy_input,
                card,
            )
        )

        cookie_box = QWidget(card)
        cookie_layout = QHBoxLayout(cookie_box)
        cookie_layout.setContentsMargins(0, 0, 0, 0)
        cookie_layout.setSpacing(8)
        self.cookies_label = ElidedLabel(self.ctx.settings.cookies_file or "未設定", cookie_box)
        self.cookies_label.setProperty("role", "secondary")
        self.cookies_label.setProperty("path", True)
        self.cookies_label.setMinimumWidth(260)
        cookie_layout.addWidget(self.cookies_label, 1)
        choose_cookie = make_button("選択", "secondary", parent=cookie_box)
        choose_cookie.clicked.connect(self._choose_cookies)
        cookie_layout.addWidget(choose_cookie)
        clear_cookie = make_button("解除", "ghost", parent=cookie_box)
        clear_cookie.clicked.connect(lambda: self._commit({"cookies_file": ""}))
        cookie_layout.addWidget(clear_cookie)
        content.addLayout(
            self._row(
                "Cookie ファイル",
                "自分が利用権を持つアカウントの Netscape 形式 Cookie を指定できます。他人の認証情報は使用しないでください。",
                cookie_box,
                card,
            )
        )

    # ---------------------------------------------------------------- history
    def _build_history(self) -> None:
        card, content = self._section(
            "history", "履歴と起動", "履歴の保存件数と、起動時のキュー復元を設定します。"
        )
        self.history_stepper = Stepper(
            50, 20000, self.ctx.settings.history_limit, step=50, suffix="件", parent=card
        )
        self.history_stepper.valueChanged.connect(
            lambda value: self._commit({"history_limit": value})
        )
        content.addLayout(
            self._row(
                "履歴の保存件数",
                "上限を超えた古い履歴は自動的に削除されます。",
                self.history_stepper,
                card,
            )
        )
        self.restore_switch = Switch(checked=self.ctx.settings.restore_queue)
        self.restore_switch.toggled.connect(lambda value: self._commit({"restore_queue": value}))
        content.addLayout(
            self._row(
                "前回のキューを復元",
                "終了時に未完了だった項目を、次回起動時に一時停止状態で復元します。",
                self.restore_switch,
                card,
            )
        )
        self.updates_switch = Switch(checked=self.ctx.settings.check_updates)
        self.updates_switch.toggled.connect(lambda value: self._commit({"check_updates": value}))
        content.addLayout(
            self._row(
                "起動時に yt-dlp の更新を確認",
                "新しいバージョンがある場合に診断画面で通知します。外部への通信が発生します。",
                self.updates_switch,
                card,
            )
        )

    # --------------------------------------------------------------- advanced
    def _build_advanced(self) -> None:
        card, content = self._section(
            "terminal", "詳細", "FFmpeg の場所とアプリのデータフォルダーを確認できます。"
        )
        ffmpeg_box = QWidget(card)
        ffmpeg_layout = QHBoxLayout(ffmpeg_box)
        ffmpeg_layout.setContentsMargins(0, 0, 0, 0)
        ffmpeg_layout.setSpacing(8)
        ffmpeg_text = QVBoxLayout()
        ffmpeg_text.setSpacing(1)
        self.ffmpeg_status = make_label("確認中…", "secondary", wrap=True)
        self.ffmpeg_path = ElidedLabel("", ffmpeg_box)
        self.ffmpeg_path.setProperty("role", "caption")
        self.ffmpeg_path.setProperty("path", True)
        self.ffmpeg_path.setMinimumWidth(240)
        ffmpeg_text.addWidget(self.ffmpeg_status)
        ffmpeg_text.addWidget(self.ffmpeg_path)
        ffmpeg_layout.addLayout(ffmpeg_text, 1)
        choose_ffmpeg = make_button("場所を指定", "secondary", parent=ffmpeg_box)
        choose_ffmpeg.clicked.connect(self._choose_ffmpeg)
        ffmpeg_layout.addWidget(choose_ffmpeg)
        detect = make_button("再検出", "ghost", parent=ffmpeg_box)
        detect.clicked.connect(lambda: self._detect_ffmpeg(show_toast=True))
        ffmpeg_layout.addWidget(detect)
        content.addLayout(
            self._row(
                "FFmpeg",
                "通常は同梱の FFmpeg を使用します。別の FFmpeg を使う場合のみ指定してください。",
                ffmpeg_box,
                card,
            )
        )

        data_box = QWidget(card)
        data_layout = QHBoxLayout(data_box)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(8)
        self.data_label = ElidedLabel(str(self.ctx.paths.data_dir), data_box)
        self.data_label.setProperty("role", "caption")
        self.data_label.setProperty("path", True)
        self.data_label.setMinimumWidth(260)
        data_layout.addWidget(self.data_label, 1)
        open_data = make_icon_button("folder-open", "データフォルダーを開く", size=16, parent=data_box)
        open_data.clicked.connect(self._open_data_dir)
        data_layout.addWidget(open_data)
        logs = make_button("ログを開く", "ghost", icon_name="file", parent=data_box)
        logs.clicked.connect(self._open_logs)
        data_layout.addWidget(logs)
        content.addLayout(
            self._row(
                "データフォルダー",
                "設定・履歴・ログ・サムネイルのキャッシュが保存されています。",
                data_box,
                card,
            )
        )

    def _build_reset(self) -> None:
        card = Card(self)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(make_label("設定を初期化", "h3"))
        text.addWidget(
            make_label(
                "テーマ、保存先、ネットワーク設定などをすべて既定値に戻します。履歴とファイルは削除されません。",
                "caption",
                wrap=True,
            )
        )
        layout.addLayout(text, 1)
        reset = make_button("初期設定に戻す", "danger", icon_name="rotate-ccw", parent=card)
        reset.clicked.connect(self._reset_settings)
        layout.addWidget(reset)
        self._column.addWidget(card)

    # --------------------------------------------------------------- syncing
    def _sync_from_settings(self) -> None:
        settings = self.ctx.settings
        self._loading = True
        try:
            self.theme_control.set_value(settings.theme, emit=False, animate=False)
            for name, swatch in self._swatches.items():
                swatch.setChecked(name == settings.accent)
            for switch, value in (
                (self.animations_switch, settings.animations),
                (self.restore_switch, settings.restore_queue),
                (self.updates_switch, settings.check_updates),
            ):
                switch.blockSignals(True)
                switch.setChecked(value)
                switch.blockSignals(False)
            self.save_dir_label.setText(settings.save_dir)
            self.template_input.setText(settings.filename_template)
            self._mark_invalid(self.template_input, False)
            self.container_control.set_value(settings.container, emit=False, animate=False)
            self.overwrite_control.set_value(settings.overwrite, emit=False, animate=False)
            self.concurrency_stepper.set_value(settings.concurrency)
            self.rate_stepper.set_value(settings.rate_limit_mbps)
            self.audio_control.set_value(settings.audio_format, emit=False, animate=False)
            self.proxy_input.setText(settings.proxy)
            self._mark_invalid(self.proxy_input, False)
            self.cookies_label.setText(settings.cookies_file or "未設定")
            self.history_stepper.set_value(settings.history_limit)
        finally:
            self._loading = False

    def _mark_invalid(self, widget: QWidget, invalid: bool) -> None:
        """Toggle the red error outline used by line edits."""
        if bool(widget.property("invalid")) == invalid:
            return
        widget.setProperty("invalid", invalid)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _commit(self, changes: dict) -> object | None:
        if self._loading:
            return None
        result = self._apply_settings(changes)
        if result is None:
            self._sync_from_settings()
            return None
        self._sync_from_settings()
        self._flash_saved()
        return result

    def _flash_saved(self) -> None:
        self.saved_label.setText("✓ 保存しました")
        self.saved_label.setProperty("role", "success")
        self.saved_label.style().unpolish(self.saved_label)
        self.saved_label.style().polish(self.saved_label)
        fade_in(self.saved_label, duration=140)
        self._saved_timer.start()

    def _reset_saved_label(self) -> None:
        self.saved_label.setText("変更は自動的に保存されます")
        self.saved_label.setProperty("role", "caption")
        self.saved_label.style().unpolish(self.saved_label)
        self.saved_label.style().polish(self.saved_label)

    # --------------------------------------------------------------- handlers
    def _on_theme_changed(self, value: str) -> None:
        self._commit({"theme": value})

    def _on_accent_changed(self, value: str) -> None:
        self._commit({"accent": value})

    def _on_animations_toggled(self, value: bool) -> None:
        self._commit({"animations": value})

    def _commit_template(self) -> None:
        if self._loading:
            return
        raw = self.template_input.text().strip()
        template, error = validate_filename_template(raw)
        if error:
            self._mark_invalid(self.template_input, True)
            self._toast("ファイル名を保存できません", error, "error")
            return
        self._mark_invalid(self.template_input, False)
        if template != raw:
            self.template_input.setText(template)
        self._commit({"filename_template": template})

    def _commit_proxy(self) -> None:
        if self._loading:
            return
        value = self.proxy_input.text().strip()
        if value and not validate_proxy(value):
            self._mark_invalid(self.proxy_input, True)
            self._toast(
                "プロキシを保存できません",
                "http://、https://、socks5:// のいずれかで始まる形式で入力してください。",
                "error",
            )
            return
        self._mark_invalid(self.proxy_input, False)
        self._commit({"proxy": value})

    def _choose_save_dir(self) -> None:
        current = self.ctx.settings.save_dir
        directory = QFileDialog.getExistingDirectory(self, "保存先フォルダーを選択", current)
        if not directory:
            return
        ok, message = validate_save_dir(directory)
        if not ok:
            self._toast("保存先を変更できません", message, "error")
            return
        self._commit({"save_dir": str(Path(directory))})

    def _open_save_dir(self) -> None:
        folder = Path(self.ctx.settings.save_dir)
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self._toast("保存先を開けません", "保存先フォルダーが見つかりません。", "warning")

    def _open_data_dir(self) -> None:
        folder = self.ctx.paths.data_dir
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _choose_cookies(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Cookie ファイルを選択",
            str(Path.home()),
            "Cookie ファイル (*.txt);;すべてのファイル (*.*)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                head = handle.read(512)
        except OSError as exc:
            self._toast("Cookie ファイルを読み込めません", str(exc), "error")
            return
        if "\t" not in head and "Netscape" not in head:
            self._toast(
                "形式を確認してください",
                "Netscape 形式（タブ区切り）の Cookie ファイルを選択してください。",
                "warning",
            )
            return
        self._commit({"cookies_file": str(path)})

    def _choose_ffmpeg(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "FFmpeg のフォルダーを選択", str(Path.home())
        )
        if not directory:
            return
        candidate = Path(directory)
        # Validate before persisting: discover_ffmpeg falls back to the bundled
        # build, so a missing folder would otherwise look like a success.
        info = discover_ffmpeg(str(candidate), probe_version=False)
        if info.ffmpeg is None or info.source != "設定":
            self._toast(
                "FFmpeg が見つかりません",
                "選択したフォルダーに ffmpeg.exe（または ffmpeg）がありません。",
                "error",
            )
            return
        result = self._commit({"ffmpeg_dir": str(candidate)})
        if result is not None:
            # apply_settings already refreshed ctx.ffmpeg; avoid a second
            # blocking ffmpeg -version subprocess.
            self._render_ffmpeg(self.ctx.ffmpeg, show_toast=True)

    def _render_ffmpeg(self, info: FFmpegInfo, *, show_toast: bool = False) -> None:
        if info.available:
            size = ""
            try:
                size = human_size(info.ffmpeg.stat().st_size) if info.ffmpeg else ""
            except OSError:
                size = ""
            self.ffmpeg_status.setText(info.status_label())
            role = "success"
            self.ffmpeg_path.setText(f"{info.ffmpeg}  ·  {info.source}" + (f"  ·  {size}" if size else ""))
            if show_toast:
                self._toast("FFmpeg を検出しました", info.status_label(), "success")
        else:
            self.ffmpeg_status.setText("FFmpeg が見つかりません")
            role = "warning"
            self.ffmpeg_path.setText(
                "映像と音声の結合、音声の変換には FFmpeg が必要です。同梱の tools/ffmpeg を確認してください。"
            )
            if show_toast:
                self._toast(
                    "FFmpeg が見つかりません",
                    "診断画面で検出状況を確認してください。",
                    "warning",
                )
        if self.ffmpeg_status.property("role") != role:
            self.ffmpeg_status.setProperty("role", role)
            self.ffmpeg_status.style().unpolish(self.ffmpeg_status)
            self.ffmpeg_status.style().polish(self.ffmpeg_status)

    def _detect_ffmpeg(self, *, show_toast: bool) -> None:
        try:
            info = self.ctx.refresh_ffmpeg()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FFmpeg の検出に失敗しました: %s", exc)
            info = self.ctx.ffmpeg
        self._render_ffmpeg(info, show_toast=show_toast)

    def _reset_settings(self) -> None:
        confirmed = ConfirmDialog.ask(
            self,
            "設定を初期化しますか？",
            "すべての設定を既定値に戻します。",
            confirm_text="初期化する",
            danger=True,
            detail="履歴、キュー、保存済みのファイルは削除されません。",
        )
        if not confirmed:
            return
        # Apply first and only persist if it succeeds; store.reset() would write
        # defaults to disk before validation, leaving disk and UI out of sync.
        result = self._apply_settings(Settings().to_dict())
        if result is None:
            return
        self._sync_from_settings()
        self._render_ffmpeg(self.ctx.ffmpeg)
        self._toast("設定を初期化しました", "既定の設定で再開します。", "success")

    # ---------------------------------------------------------------- helpers
    def on_settings_changed(self) -> None:
        self._sync_from_settings()
        palette = current_palette()
        for name, swatch in self._swatches.items():
            swatch.set_color(ACCENTS[name][palette.mode][0])
        self._render_ffmpeg(self.ctx.ffmpeg)

    def refresh_theme(self) -> None:
        refresh_named_icons(self)
        color, soft = tone_colors("accent")
        for badge, icon_name in self._section_badges:
            badge.setStyleSheet(f"background-color: {soft}; border-radius: 10px;")
            badge.setPixmap(icon(icon_name, color, 19).pixmap(19, 19))
        palette = current_palette()
        for name, swatch in self._swatches.items():
            swatch.set_color(ACCENTS[name][palette.mode][0])
        self._render_ffmpeg(self.ctx.ffmpeg)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_from_settings()
        self._render_ffmpeg(self.ctx.ffmpeg)

    def focus_search(self) -> None:
        self.template_input.setFocus()
        self.template_input.selectAll()
