from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Property, QPointF, QPropertyAnimation, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.settings import Settings, validate_filename_template, validate_save_dir
from .context import AppContext
from .dialogs import ConfirmDialog, HelpDialog
from .icons import app_icon, logo_pixmap
from .pages.diagnostics import DiagnosticsPage
from .pages.history import HistoryPage
from .pages.home import HomePage
from .pages.queue import QueuePage
from .pages.settings import SettingsPage
from .theme import (
    EASING,
    MOTION_BASE,
    MOTION_FAST,
    animations_enabled,
    apply_window_theme,
    current_palette,
)
from .widgets import (
    MotionButton,
    Spinner,
    ToastHost,
    fade_in,
    make_icon_button,
    make_label,
    refresh_named_icons,
    set_named_icon,
)

logger = logging.getLogger(__name__)

_PAGE_META = {
    "home": ("ホーム", "動画を解析してダウンロード"),
    "queue": ("キュー", "進行中と待機中のダウンロード"),
    "history": ("履歴", "完了したダウンロード"),
    "settings": ("設定", "見た目と動作のカスタマイズ"),
    "diagnostics": ("診断", "環境とログの確認"),
}


class _Backdrop(QWidget):
    """Paints the soft, colour-shifting surface behind the glass panels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = max(1, self.width())
        height = max(1, self.height())
        base = QLinearGradient(0, 0, width, height)
        if palette.is_dark:
            base.setColorAt(0, QColor("#070A14"))
            base.setColorAt(0.48, QColor("#0A1020"))
            base.setColorAt(1, QColor("#05070D"))
        else:
            base.setColorAt(0, QColor("#F8FBFF"))
            base.setColorAt(0.5, QColor("#EDF3FC"))
            base.setColorAt(1, QColor("#FFF7F0"))
        painter.fillRect(self.rect(), QBrush(base))

        if palette.is_dark:
            blobs = (
                (palette.accent, 92, 0.10, 0.02, 0.55),
                (palette.info, 68, 0.92, 0.08, 0.50),
                (palette.success, 48, 0.82, 0.82, 0.58),
                (palette.warning, 30, 0.18, 0.94, 0.44),
            )
        else:
            blobs = (
                (palette.info, 52, 0.92, 0.02, 0.52),
                (palette.accent, 42, 0.05, 0.20, 0.48),
                (palette.warning, 30, 0.78, 0.88, 0.55),
                (palette.success, 34, 0.18, 0.95, 0.42),
            )
        for color_name, alpha, cx, cy, radius in blobs:
            center = QPointF(cx * width, cy * height)
            gradient = QRadialGradient(center, radius * max(width, height))
            inner = QColor(color_name)
            inner.setAlpha(alpha)
            outer = QColor(color_name)
            outer.setAlpha(0)
            gradient.setColorAt(0, inner)
            gradient.setColorAt(1, outer)
            painter.fillRect(self.rect(), QBrush(gradient))
        painter.end()


class _FadeOverlay(QWidget):
    """Lightweight backdrop used to fade a page in without re-compositing it.

    A QGraphicsOpacityEffect on a full page forces Qt to render the whole page
    into an offscreen pixmap for every animation frame.  A solid overlay that
    fades out paints only a rectangle and leaves the page itself at full
    quality.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._opacity = 0.75

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    opacity = Property(float, _get_opacity, _set_opacity)

    def paintEvent(self, event) -> None:  # noqa: N802
        color = QColor(current_palette().bg)
        color.setAlphaF(max(0.0, min(1.0, self._opacity)))
        painter = QPainter(self)
        painter.fillRect(self.rect(), color)
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._current_page = "home"
        self._closing = False
        self._restored = False
        self._fade_animation = QPropertyAnimation(self)
        self._fade_animation.setPropertyName(b"opacity")
        self._fade_animation.setDuration(MOTION_FAST)
        self._fade_animation.setEasingCurve(EASING)
        self._fade_animation.finished.connect(self._finish_page_fade)
        self._fade_overlay: _FadeOverlay | None = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_badges: dict[str, QLabel] = {}
        self.setWindowTitle(f"Vela {__version__} — 動画ダウンローダー")
        self.setWindowIcon(app_icon())
        self.resize(ctx.settings.window_width, ctx.settings.window_height)
        self.setMinimumSize(1040, 700)
        self._build_ui()
        self._connect_signals()
        self._install_shortcuts()
        self._update_nav_icons()
        self._update_activity(0)
        self._update_queue_badge()
        self._sync_theme_button()
        self.navigate(ctx.settings.last_page if ctx.settings.last_page in _PAGE_META else "home", animate=False)

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        central = _Backdrop(self)
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        root.addWidget(self._build_sidebar())

        right = QWidget(central)
        right.setObjectName("contentShell")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(24, 16, 24, 22)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._build_topbar())
        self.stack = QStackedWidget(right)
        self.stack.setObjectName("pageStack")
        right_layout.addWidget(self.stack, 1)
        root.addWidget(right, 1)

        self.home = HomePage(
            self.ctx,
            navigate=self.navigate,
            apply_settings=self.apply_settings,
            open_logs=self.open_logs,
            toast=self.toast,
        )
        self.queue_page = QueuePage(
            self.ctx,
            navigate=self.navigate,
            toast=self.toast,
            open_logs=self.open_logs,
        )
        self.history_page = HistoryPage(
            self.ctx,
            navigate=self.navigate,
            toast=self.toast,
        )
        self.settings_page = SettingsPage(
            self.ctx,
            apply_settings=self.apply_settings,
            open_logs=self.open_logs,
            toast=self.toast,
        )
        self.diagnostics_page = DiagnosticsPage(
            self.ctx,
            navigate=self.navigate,
            open_logs=self.open_logs,
            toast=self.toast,
        )
        for page in (
            self.home,
            self.queue_page,
            self.history_page,
            self.settings_page,
            self.diagnostics_page,
        ):
            self.stack.addWidget(page)

        self.toasts = ToastHost(central)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(self)
        sidebar.setProperty("role", "sidebar")
        sidebar.setFixedWidth(232)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(8)

        brand = QWidget(sidebar)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(2, 0, 2, 0)
        brand_layout.setSpacing(11)
        self._logo = QLabel(brand)
        self._logo.setPixmap(logo_pixmap(38))
        self._logo.setFixedSize(38, 38)
        brand_layout.addWidget(self._logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("Vela", brand)
        name_font = QFont(self.font())
        name_font.setPointSizeF(14)
        name_font.setWeight(QFont.Bold)
        name.setFont(name_font)
        brand_text.addWidget(name)
        brand_text.addWidget(make_label("VIDEO DOWNLOADER", "eyebrow"))
        brand_layout.addLayout(brand_text)
        brand_layout.addStretch(1)
        layout.addWidget(brand)
        layout.addSpacing(16)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_indicator = QFrame(sidebar)
        self._nav_indicator.setObjectName("navIndicator")
        self._nav_indicator.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._nav_indicator.hide()
        self._nav_indicator_animation = QPropertyAnimation(
            self._nav_indicator, b"geometry", self
        )
        self._nav_indicator_animation.setDuration(MOTION_BASE)
        self._nav_indicator_animation.setEasingCurve(EASING)
        for key, (label, description) in _PAGE_META.items():
            button = MotionButton(label, sidebar)
            button.setProperty("variant", "nav")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(42)
            button.setAccessibleName(description)
            button.setToolTip(description)
            button.clicked.connect(lambda _checked=False, page=key: self.navigate(page))
            set_named_icon(button, key if key != "home" else "home", color="muted", size=18)
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button

            row = QWidget(sidebar)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)
            row_layout.addWidget(button, 1)
            badge = QLabel(row)
            badge.setProperty("role", "pill")
            badge.setAlignment(Qt.AlignCenter)
            badge.setMinimumWidth(24)
            badge.hide()
            self._nav_badges[key] = badge
            row_layout.addWidget(badge, 0, Qt.AlignVCenter)
            layout.addWidget(row)

        layout.addStretch(1)

        tip = QFrame(sidebar)
        tip.setProperty("card", True)
        tip.setProperty("subtle", True)
        tip_layout = QVBoxLayout(tip)
        tip_layout.setContentsMargins(12, 11, 12, 11)
        tip_layout.setSpacing(4)
        tip_head = QHBoxLayout()
        tip_head.setSpacing(6)
        shield = QLabel(tip)
        set_named_icon(shield, "shield", color="accent", size=15)
        tip_head.addWidget(shield)
        tip_head.addWidget(make_label("ローカルで安全に", "h3"))
        tip_head.addStretch(1)
        tip_layout.addLayout(tip_head)
        tip_layout.addWidget(
            make_label(
                "設定・履歴・ログは端末内に保存されます。",
                "caption",
                wrap=True,
            )
        )
        layout.addWidget(tip)
        layout.addSpacing(8)

        footer = QHBoxLayout()
        footer.setSpacing(2)
        version = make_label(f"v{__version__}", "caption")
        footer.addWidget(version)
        footer.addStretch(1)
        self.help_button = make_icon_button("help", "使い方とショートカット (F1)", size=16, parent=sidebar)
        self.help_button.clicked.connect(self._show_help)
        footer.addWidget(self.help_button)
        logs_button = make_icon_button("terminal", "ログを開く", size=16, parent=sidebar)
        logs_button.clicked.connect(self.open_logs)
        footer.addWidget(logs_button)
        layout.addLayout(footer)
        return sidebar

    def _build_topbar(self) -> QFrame:
        topbar = QFrame(self)
        topbar.setProperty("role", "topbar")
        topbar.setFixedHeight(62)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(10)
        self._page_title = make_label("ホーム", "h2")
        layout.addWidget(self._page_title)
        self._page_subtitle = make_label("", "caption")
        layout.addWidget(self._page_subtitle, 0, Qt.AlignVCenter)
        layout.addStretch(1)

        self._activity = QWidget(topbar)
        self._activity.setProperty("role", "activity")
        activity_layout = QHBoxLayout(self._activity)
        activity_layout.setContentsMargins(10, 5, 12, 5)
        activity_layout.setSpacing(7)
        self._activity_spinner = Spinner(self._activity, size=14)
        activity_layout.addWidget(self._activity_spinner)
        self._activity_label = make_label("", "caption")
        activity_layout.addWidget(self._activity_label)
        self._activity.hide()
        layout.addWidget(self._activity)
        layout.addSpacing(4)

        self.theme_button = make_icon_button("sun", "ライトテーマに切り替え", size=17, parent=topbar)
        self.theme_button.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_button)
        settings_button = make_icon_button("settings", "設定を開く", size=17, parent=topbar)
        settings_button.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(settings_button)
        return topbar

    # ------------------------------------------------------------- navigation
    def navigate(self, page: str, *, animate: bool = True) -> None:
        if page not in _PAGE_META:
            return
        target = {
            "home": self.home,
            "queue": self.queue_page,
            "history": self.history_page,
            "settings": self.settings_page,
            "diagnostics": self.diagnostics_page,
        }[page]
        changed = page != self._current_page or self.stack.currentWidget() is not target
        self._current_page = page
        self.stack.setCurrentWidget(target)
        button = self._nav_buttons.get(page)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        title, subtitle = _PAGE_META[page]
        self._page_title.setText(title)
        self._page_subtitle.setText(subtitle)
        self._update_nav_icons()
        if button is not None:
            self._move_nav_indicator(button, animate=animate and changed)
        if changed and animate:
            self._fade_in(target)
        if page == "queue":
            self._update_queue_badge()
        if button is not None:
            button.setFocus(Qt.OtherFocusReason)

    def _move_nav_indicator(self, button: QPushButton, *, animate: bool) -> None:
        indicator = getattr(self, "_nav_indicator", None)
        if indicator is None:
            return
        parent = indicator.parentWidget()
        if parent is None:
            return
        target = QRect(button.mapTo(parent, button.rect().topLeft()), button.size())
        target.adjust(0, 1, 0, -1)
        animation = self._nav_indicator_animation
        animation.stop()
        was_visible = indicator.isVisible()
        indicator.show()
        if not animate or not animations_enabled() or not was_visible:
            indicator.setGeometry(target)
            return
        animation.setStartValue(indicator.geometry())
        animation.setEndValue(target)
        animation.start()

    def _sync_nav_indicator(self) -> None:
        button = self._nav_buttons.get(self._current_page)
        if button is not None:
            self._move_nav_indicator(button, animate=False)

    def _fade_in(self, _widget: QWidget) -> None:
        animation = self._fade_animation
        animation.stop()
        if self._fade_overlay is not None:
            self._fade_overlay.hide()
            self._fade_overlay.deleteLater()
            self._fade_overlay = None
        if not animations_enabled():
            return
        overlay = _FadeOverlay(self.stack)
        overlay.setGeometry(self.stack.rect())
        overlay.show()
        overlay.raise_()
        animation.setTargetObject(overlay)
        animation.setStartValue(0.35)
        animation.setEndValue(0.0)
        self._fade_overlay = overlay
        animation.start()

    def _finish_page_fade(self) -> None:
        if self._fade_overlay is not None:
            self._fade_overlay.hide()
            self._fade_overlay.deleteLater()
            self._fade_overlay = None

    # --------------------------------------------------------------- signals
    def _connect_signals(self) -> None:
        self.ctx.queue.notification.connect(self._on_notification)
        self.ctx.queue.active_count_changed.connect(self._update_activity)
        self.ctx.queue.persistence_error.connect(
            lambda message: self.toast("キューを保存できません", message, "warning")
        )
        self.ctx.queue_model.stats_changed.connect(self._update_queue_badge)
        self.ctx.theme.changed.connect(self._on_theme_changed)

    def _on_notification(self, title: str, message: str, kind: str) -> None:
        self.toast(title, message, kind)

    def _update_activity(self, count: int) -> None:
        if count <= 0:
            self._activity_spinner.stop()
            self._activity.hide()
            return
        self._activity_label.setText(f"{count} 件を処理中")
        self._activity_spinner.start()
        if not self._activity.isVisible():
            self._activity.show()
            fade_in(self._activity, duration=140)

    def _update_queue_badge(self) -> None:
        stats = self.ctx.queue_model.stats()
        active = stats["active"] + stats["queued"]
        badge = self._nav_badges.get("queue")
        if badge is not None:
            badge.setText(str(active))
            badge.setVisible(active > 0)
            color, soft = self._badge_colors()
            badge.setStyleSheet(f"background-color: {soft}; color: {color};")
        history_badge = self._nav_badges.get("history")
        if history_badge is not None:
            history_badge.hide()

    def _badge_colors(self) -> tuple[str, str]:
        palette = current_palette()
        if self.ctx.queue.active_count > 0:
            return palette.accent, palette.accent_soft
        return palette.text_muted, palette.surface_alt

    def _update_nav_icons(self) -> None:
        for key, button in self._nav_buttons.items():
            active = key == self._current_page
            set_named_icon(
                button,
                "home" if key == "home" else key,
                color="on_accent" if active else "muted",
                size=18,
            )

    # --------------------------------------------------------------- settings
    def apply_settings(self, changes: dict) -> Settings | None:
        previous = self.ctx.settings
        if not isinstance(changes, dict):
            return None
        if "save_dir" in changes:
            ok, message = validate_save_dir(str(changes["save_dir"]))
            if not ok:
                self.toast("保存先を変更できません", message, "error")
                return None
        if "filename_template" in changes:
            _template, error = validate_filename_template(str(changes["filename_template"]))
            if error:
                self.toast("ファイル名を保存できません", error, "error")
                return None
        if changes.get("cookies_file"):
            cookie = Path(str(changes["cookies_file"])).expanduser()
            if not cookie.is_file():
                self.toast(
                    "Cookie ファイルが見つかりません",
                    "選択したファイルが存在するか確認してください。",
                    "error",
                )
                return None
        data = previous.to_dict()
        data.update(changes)
        candidate, issues = Settings.from_dict(data)
        try:
            self.ctx.store.save(candidate)
        except OSError as exc:
            logger.error("設定を保存できませんでした: %s", exc)
            self.toast(
                "設定を保存できませんでした",
                f"設定ファイルに書き込めません: {exc}",
                "error",
            )
            return None
        self.ctx.settings = candidate
        if candidate.ffmpeg_dir != previous.ffmpeg_dir:
            try:
                info = self.ctx.refresh_ffmpeg()
            except Exception as exc:  # noqa: BLE001
                logger.warning("FFmpeg の再検出に失敗しました: %s", exc)
                info = self.ctx.ffmpeg
            if not info.available:
                self.toast(
                    "FFmpeg を検出できません",
                    "指定したフォルダーに ffmpeg.exe があるか確認してください。",
                    "warning",
                )
        theme_changed = (
            candidate.theme != previous.theme
            or candidate.accent != previous.accent
        )
        animations_changed = candidate.animations != previous.animations
        if theme_changed:
            self.ctx.theme.apply(candidate.theme, candidate.accent, candidate.animations)
        elif animations_changed:
            # The animation switch itself is animated.  Rebuilding the QSS
            # here would freeze that animation for the duration of the
            # application-wide re-polish.
            self.ctx.theme.set_animations(candidate.animations)
        visual_only = set(changes) <= {"theme", "accent", "animations"}
        if visual_only:
            # The theme signal already refreshed every page.  Only the
            # settings controls need a cheap sync to reflect the new value.
            self.settings_page.on_settings_changed()
        else:
            self.ctx.queue.apply_settings()
            for page in (
                self.home,
                self.queue_page,
                self.history_page,
                self.settings_page,
                self.diagnostics_page,
            ):
                callback = getattr(page, "on_settings_changed", None)
                if callback is not None:
                    callback()
        if issues:
            shown = "\n".join(issues[:3])
            self.toast(
                "一部の設定を調整しました",
                shown,
                "warning",
            )
        return candidate

    def _toggle_theme(self) -> None:
        target = "light" if current_palette().is_dark else "dark"
        self.apply_settings({"theme": target})

    def _sync_theme_button(self) -> None:
        dark = current_palette().is_dark
        set_named_icon(
            self.theme_button, "sun" if dark else "moon", color="secondary", size=17
        )
        self.theme_button.setToolTip(
            "ライトテーマに切り替え" if dark else "ダークテーマに切り替え"
        )

    def _on_theme_changed(self, _palette) -> None:
        self.setWindowIcon(app_icon())
        self._logo.setPixmap(logo_pixmap(38))
        self._sync_theme_button()
        for page in (
            self.home,
            self.queue_page,
            self.history_page,
            self.settings_page,
            self.diagnostics_page,
        ):
            refresh = getattr(page, "refresh_theme", None)
            if refresh is not None:
                refresh()
        refresh_named_icons(self)
        self._update_nav_icons()
        self._update_queue_badge()
        self._update_activity(self.ctx.queue.active_count)
        self.toasts.reposition()
        apply_window_theme(self)
        self.centralWidget().update()

    # ---------------------------------------------------------------- helpers
    def toast(
        self,
        title: str,
        message: str = "",
        kind: str = "info",
        *,
        action_label: str = "",
        action_callback=None,
    ) -> None:
        self.toasts.show_toast(
            title,
            message,
            kind,
            action_label=action_label,
            action_callback=action_callback,
        )

    def open_logs(self) -> None:
        log_file = self.ctx.paths.log_file
        if log_file.is_file():
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file))):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.paths.logs_dir)))
            return
        if self.ctx.paths.logs_dir.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.paths.logs_dir)))
        else:
            self.toast("ログを開けません", "ログフォルダーが見つかりませんでした。", "warning")

    def _show_help(self) -> None:
        HelpDialog(self).exec()

    def _install_shortcuts(self) -> None:
        for index, page in enumerate(("home", "queue", "history", "settings", "diagnostics"), start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(lambda page=page: self.navigate(page))
        focus_url = QShortcut(QKeySequence("Ctrl+L"), self)
        focus_url.setContext(Qt.WindowShortcut)
        focus_url.activated.connect(self._focus_url)

        paste = QShortcut(QKeySequence("Ctrl+V"), self)
        paste.setContext(Qt.WindowShortcut)
        paste.activated.connect(self._paste_url)

        help_shortcut = QShortcut(QKeySequence("F1"), self)
        help_shortcut.setContext(Qt.WindowShortcut)
        help_shortcut.activated.connect(self._show_help)

        analyze = QShortcut(QKeySequence("Ctrl+Return"), self)
        analyze.setContext(Qt.WindowShortcut)
        analyze.activated.connect(self.home.analyze)

        find = QShortcut(QKeySequence("Ctrl+F"), self)
        find.setContext(Qt.WindowShortcut)
        find.activated.connect(self._focus_search)

        preferences = QShortcut(QKeySequence("Ctrl+,"), self)
        preferences.setContext(Qt.WindowShortcut)
        preferences.activated.connect(lambda: self.navigate("settings"))

        escape = QShortcut(QKeySequence("Escape"), self)
        escape.setContext(Qt.WindowShortcut)
        escape.activated.connect(self._escape)

    def _focus_search(self) -> None:
        if self.stack.currentWidget() is self.queue_page:
            self.queue_page.search.setFocus()
            self.queue_page.search.selectAll()
            return
        if self.stack.currentWidget() is self.history_page:
            self.history_page.search.setFocus()
            self.history_page.search.selectAll()
            return
        self.navigate("queue")
        self.queue_page.search.setFocus()
        self.queue_page.search.selectAll()

    def _focus_url(self) -> None:
        self.navigate("home")
        self.home.focus_url()

    def _paste_url(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit)) and focus is not self.home.url_input:
            focus.paste()
            return
        self.navigate("home")
        self.home.focus_url(paste=True)

    def _escape(self) -> None:
        if self.stack.currentWidget() is self.home:
            self.home.cancel_analysis()

    # -------------------------------------------------------------- lifecycle
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, lambda: apply_window_theme(self))
        QTimer.singleShot(0, self._sync_nav_indicator)
        if not self._restored:
            self._restored = True
            QTimer.singleShot(260, self._restore_session)

    def _restore_session(self) -> None:
        if self._closing:
            return
        restored = 0
        try:
            restored = self.ctx.queue.load_state(self.ctx.settings.restore_queue)
        except Exception as exc:  # noqa: BLE001
            logger.warning("キューの復元に失敗しました: %s", exc)
        if restored:
            self.toast(
                "前回のキューを復元しました",
                f"{restored} 件の項目を一時停止状態で復元しました。「すべて再開」で再開できます。",
                "info",
                action_label="キューを表示",
                action_callback=lambda: self.navigate("queue"),
            )
            self._update_queue_badge()
        for warning in self.ctx.store.warnings:
            self.toast("設定を確認しました", warning, "warning")
        history_warnings = getattr(self.ctx.history, "warnings", [])
        for warning in history_warnings:
            self.toast("履歴を確認しました", warning, "warning")
        queue_warnings = getattr(self.ctx.queue, "warnings", [])
        for warning in queue_warnings:
            self.toast("キューを確認しました", warning, "warning")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_page_subtitle"):
            self._page_subtitle.setVisible(self.width() >= 1160)
        if getattr(self, "stack", None) is not None and self._fade_overlay is not None:
            self._fade_overlay.setGeometry(self.stack.rect())
        if hasattr(self, "_nav_indicator"):
            self._sync_nav_indicator()
        if hasattr(self, "toasts"):
            self.toasts.reposition()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing:
            event.accept()
            return
        active = self.ctx.queue.active_count
        if active > 0:
            confirmed = ConfirmDialog.ask(
                self,
                "ダウンロード中に終了しますか？",
                f"{active} 件のダウンロードが進行中です。終了するとキャンセルされます。",
                confirm_text="終了する",
                cancel_text="戻る",
                danger=True,
                detail="未完了の項目は保存され、次回起動時に一時停止状態で復元できます（設定が有効な場合）。",
            )
            if not confirmed:
                event.ignore()
                return
        self._closing = True
        self._save_window_state()
        try:
            self.home.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析処理の終了に失敗しました: %s", exc)
        try:
            self.diagnostics_page.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("診断処理の終了に失敗しました: %s", exc)
        try:
            self.ctx.queue.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("キューの終了処理に失敗しました: %s", exc)
        self.ctx.history.close()
        event.accept()

    def _save_window_state(self) -> None:
        settings = self.ctx.settings
        settings.window_width = max(900, self.width())
        settings.window_height = max(600, self.height())
        settings.last_page = self._current_page
        try:
            self.ctx.store.save(settings)
        except OSError as exc:
            logger.warning("ウィンドウ状態を保存できませんでした: %s", exc)
