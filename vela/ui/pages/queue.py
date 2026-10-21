from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QMenu,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ...core.models import DownloadStatus, QueueItem
from ...core.queue import QueueFilterProxy, QueueModel
from ...core.utils import human_duration, human_eta, human_size, human_speed
from ..context import AppContext
from ..dialogs import ConfirmDialog
from ..icons import icon
from ..theme import current_palette, scaled_font
from ..widgets import (
    Card,
    EmptyState,
    MessageBanner,
    SegmentedControl,
    StatCard,
    fade_in,
    make_button,
    make_icon_button,
    make_label,
    refresh_named_icons,
    tone_colors,
)

logger = logging.getLogger(__name__)

_STATUS_TONES: dict[DownloadStatus, str] = {
    DownloadStatus.QUEUED: "muted",
    DownloadStatus.ANALYZING: "accent",
    DownloadStatus.DOWNLOADING: "accent",
    DownloadStatus.PROCESSING: "accent",
    DownloadStatus.CANCELLING: "warning",
    DownloadStatus.PAUSED: "warning",
    DownloadStatus.COMPLETED: "success",
    DownloadStatus.FAILED: "danger",
    DownloadStatus.CANCELLED: "muted",
}

_STATUS_ICONS: dict[DownloadStatus, str] = {
    DownloadStatus.QUEUED: "clock",
    DownloadStatus.ANALYZING: "search",
    DownloadStatus.DOWNLOADING: "download",
    DownloadStatus.PROCESSING: "layers",
    DownloadStatus.CANCELLING: "x-circle",
    DownloadStatus.PAUSED: "pause",
    DownloadStatus.COMPLETED: "check-circle",
    DownloadStatus.FAILED: "alert-circle",
    DownloadStatus.CANCELLED: "x-circle",
}


_LAYOUT_CACHE: dict[tuple[str, int], dict[str, object]] = {}


def _queue_layout(font: QFont) -> dict[str, object]:
    """Derive row geometry from the actual font metrics.

    Row heights used to be fixed at 108 px.  That is correct for 10 pt text at
    96 DPI but clips Japanese glyphs when Windows text scaling is increased.
    Delegates call this for every visible row on every repaint, so cache by
    the font's Qt cache key (which includes size, weight and DPI).
    """
    cache_key = (font.key(), QFontMetrics(font).height())
    cached = _LAYOUT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    title_font = scaled_font(font, 1.05, QFont.DemiBold)
    meta_font = scaled_font(font, 0.88)
    detail_font = scaled_font(font, 0.86)
    pill_font = scaled_font(font, 0.85, QFont.DemiBold)

    title_h = max(22, QFontMetrics(title_font).height() + 2)
    meta_h = max(18, QFontMetrics(meta_font).height() + 2)
    detail_h = max(18, QFontMetrics(detail_font).height() + 2)
    pill_h = max(22, QFontMetrics(pill_font).height() + 2)

    title_top = 12
    meta_top = title_top + title_h
    bar_top = meta_top + meta_h + 14
    detail_top = bar_top + 12
    row_height = detail_top + detail_h + 12
    layout = {
        "title_font": title_font,
        "meta_font": meta_font,
        "detail_font": detail_font,
        "pill_font": pill_font,
        "title_h": title_h,
        "meta_h": meta_h,
        "detail_h": detail_h,
        "pill_h": pill_h,
        "title_top": title_top,
        "meta_top": meta_top,
        "bar_top": bar_top,
        "detail_top": detail_top,
        "row_height": row_height,
    }
    if len(_LAYOUT_CACHE) > 16:
        _LAYOUT_CACHE.clear()
    _LAYOUT_CACHE[cache_key] = layout
    return layout


class QueueDelegate(QStyledItemDelegate):
    """Paints queue rows as cards without creating one widget per item."""

    action_clicked = Signal(str, str)  # item_id, action

    ROW_HEIGHT = 108
    _ACTION_SIZE = 30
    _ACTION_LABELS = {
        "pause": "一時停止",
        "resume": "再開",
        "cancel": "キャンセル",
        "remove": "キューから削除",
        "retry": "再試行",
        "open": "保存先を開く",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.highlight_id: str | None = None

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        layout = _queue_layout(option.font)
        return QSize(max(280, option.rect.width()), int(layout["row_height"]))

    # ------------------------------------------------------------------ paint
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        item = index.data(QueueModel.ItemRole)
        if not isinstance(item, QueueItem):
            return
        palette = current_palette()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(option.rect).adjusted(2, 3, -2, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        highlighted = item.item_id == self.highlight_id
        background = palette.surface_hover if hovered else palette.card
        if highlighted:
            background = palette.accent_soft
        if selected:
            background = palette.accent_soft
        border = palette.accent if selected or highlighted else (
            palette.border_strong if hovered else palette.border
        )

        painter.setPen(QPen(QColor(border), 1.4 if selected or highlighted else 1.0))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 14, 14)
        if option.state & QStyle.State_HasFocus and selected:
            painter.setPen(QPen(QColor(palette.accent_border), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2.5, 2.5, -2.5, -2.5), 12, 12)

        # A slim accent rail makes the active or selected row identifiable at a
        # glance without relying on the background tint alone.
        if selected or item.status.is_active:
            rail_color = palette.accent if selected or highlighted else palette.accent_border
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(rail_color))
            painter.drawRoundedRect(
                QRectF(rect.left() + 1.5, rect.top() + 18, 3, rect.height() - 36),
                1.5,
                1.5,
            )

        left = rect.left() + 16
        right = rect.right() - 16
        top = rect.top()

        # Status icon bubble
        tone = _STATUS_TONES.get(item.status, "muted")
        tone_color, tone_soft = tone_colors(tone)
        bubble = QRectF(left, top + 16, 40, 40)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tone_soft))
        painter.drawEllipse(bubble)
        glyph = icon(_STATUS_ICONS.get(item.status, "info"), tone_color, 20)
        glyph.paint(
            painter,
            QRect(int(bubble.center().x() - 10), int(bubble.center().y() - 10), 20, 20),
        )

        text_x = left + 54
        layout = _queue_layout(option.font)

        # Status pill (top right)
        pill_font = layout["pill_font"]
        pill_text = item.status.label
        pill_metrics = QFontMetrics(pill_font)
        pill_width = pill_metrics.horizontalAdvance(pill_text) + 20
        pill_rect = QRectF(
            right - pill_width, top + 13, pill_width, int(layout["pill_h"])
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tone_soft))
        painter.drawRoundedRect(pill_rect, 8, 8)
        painter.setFont(pill_font)
        painter.setPen(QColor(tone_color))
        painter.drawText(pill_rect, Qt.AlignCenter, pill_text)

        # Title
        title_font = layout["title_font"]
        title_metrics = QFontMetrics(title_font)
        title_width = max(40, pill_rect.left() - text_x - 14)
        painter.setFont(title_font)
        painter.setPen(QColor(palette.text))
        painter.drawText(
            QRectF(
                text_x,
                top + int(layout["title_top"]),
                title_width,
                int(layout["title_h"]),
            ),
            Qt.AlignLeft | Qt.AlignVCenter,
            title_metrics.elidedText(
                item.title or "（タイトルなし）", Qt.ElideRight, int(title_width)
            ),
        )

        # Metadata
        meta_font = layout["meta_font"]
        meta_metrics = QFontMetrics(meta_font)
        meta_bits = [bit for bit in (item.extractor, item.uploader) if bit]
        if item.duration:
            meta_bits.append(human_duration(item.duration))
        if item.format_label:
            meta_bits.append(item.format_label)
        meta_width = max(40, right - text_x - 4)
        painter.setFont(meta_font)
        painter.setPen(QColor(palette.text_muted))
        painter.drawText(
            QRectF(
                text_x,
                top + int(layout["meta_top"]),
                meta_width,
                int(layout["meta_h"]),
            ),
            Qt.AlignLeft | Qt.AlignVCenter,
            meta_metrics.elidedText(
                "  ·  ".join(meta_bits) or "—", Qt.ElideRight, int(meta_width)
            ),
        )

        # Action buttons
        actions = self._actions_for(item)
        right_end = rect.right() - 16
        for action, rect_action in self._action_rects(
            option.rect, item, option.font
        ).items():
            painter.setPen(QPen(QColor(palette.border), 1))
            painter.setBrush(QColor(palette.surface_alt))
            painter.drawRoundedRect(QRectF(rect_action), 9, 9)
            color = (
                palette.danger
                if action in ("cancel", "remove")
                else palette.text_secondary
            )
            icon_name = {
                "pause": "pause",
                "resume": "play",
                "cancel": "x",
                "remove": "trash",
                "retry": "retry",
                "open": "folder-open",
            }.get(action, "more")
            glyph = icon(icon_name, color, 16)
            glyph.paint(painter, rect_action.adjusted(7, 7, -7, -7))

        actions_left = right_end - (
            len(actions) * self._ACTION_SIZE + max(0, len(actions) - 1) * 4
        )
        content_right = actions_left - 12
        bar_width = max(60, content_right - text_x)
        bar_top = top + int(layout["bar_top"])

        percent = item.percent
        if item.status == DownloadStatus.COMPLETED:
            percent = 100.0
        fill_ratio = 0.0 if percent is None else max(0.0, min(1.0, percent / 100.0))
        bar_color = {
            "success": QColor(palette.success),
            "warning": QColor(palette.warning),
            "danger": QColor(palette.danger),
        }.get(tone, QColor(palette.accent))

        track = QRectF(text_x, bar_top, bar_width, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(palette.border))
        painter.drawRoundedRect(track, 3, 3)
        if fill_ratio > 0:
            fill = QRectF(text_x, bar_top, max(3.0, bar_width * fill_ratio), 6)
            painter.setBrush(bar_color)
            painter.drawRoundedRect(fill, 3, 3)
        elif item.status in (DownloadStatus.ANALYZING, DownloadStatus.DOWNLOADING):
            painter.setBrush(QColor(palette.accent_border))
            painter.drawRoundedRect(
                QRectF(text_x, bar_top, min(48.0, bar_width), 6), 3, 3
            )

        # Bottom status text
        detail_font = layout["detail_font"]
        detail_metrics = QFontMetrics(detail_font)
        detail, detail_tone = self._detail_text(item)
        painter.setFont(detail_font)
        painter.setPen(
            QColor(
                tone_colors(detail_tone)[0]
                if detail_tone != "muted"
                else palette.text_muted
            )
        )
        painter.drawText(
            QRectF(
                text_x,
                top + int(layout["detail_top"]),
                bar_width,
                int(layout["detail_h"]),
            ),
            Qt.AlignLeft | Qt.AlignVCenter,
            detail_metrics.elidedText(detail, Qt.ElideRight, int(bar_width)),
        )
        painter.restore()

    # --------------------------------------------------------------- geometry
    def _actions_for(self, item: QueueItem) -> list[str]:
        status = item.status
        if status.is_active:
            if status in (DownloadStatus.PROCESSING, DownloadStatus.CANCELLING):
                return ["cancel"]
            return ["pause", "cancel"]
        if status == DownloadStatus.PAUSED:
            return ["resume", "remove"]
        if status == DownloadStatus.QUEUED:
            return ["pause", "remove"]
        if status == DownloadStatus.COMPLETED:
            return ["open", "remove"]
        if status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            return ["retry", "remove"]
        return ["remove"]

    def _action_rects(
        self, rect: QRect, item: QueueItem, font: QFont
    ) -> dict[str, QRect]:
        actions = self._actions_for(item)
        size = self._ACTION_SIZE
        gap = 4
        right = rect.right() - 16
        bar_top = int(_queue_layout(font)["bar_top"])
        y = rect.top() + bar_top - 10
        rects: dict[str, QRect] = {}
        for index, action in enumerate(actions):
            x = right - (len(actions) - index) * size - (len(actions) - index - 1) * gap
            rects[action] = QRect(x, y, size, size)
        return rects

    def _detail_text(self, item: QueueItem) -> tuple[str, str]:
        status = item.status
        if status == DownloadStatus.DOWNLOADING:
            bits: list[str] = []
            if item.percent is not None:
                bits.append(f"{item.percent:.1f}%")
            if item.total_bytes:
                bits.append(
                    f"{human_size(item.downloaded_bytes or 0)} / {human_size(item.total_bytes)}"
                )
            elif item.downloaded_bytes:
                bits.append(human_size(item.downloaded_bytes))
            if item.speed:
                bits.append(human_speed(item.speed))
            if item.eta is not None:
                bits.append(human_eta(item.eta))
            return "  ·  ".join(bits) or item.phase or "ダウンロード中", "muted"
        if status == DownloadStatus.ANALYZING:
            return item.phase or "動画情報を確認しています", "muted"
        if status == DownloadStatus.PROCESSING:
            return item.phase or "後処理を実行しています", "muted"
        if status == DownloadStatus.CANCELLING:
            return "キャンセルしています…", "warning"
        if status == DownloadStatus.PAUSED:
            return item.note or "再開すると続きからダウンロードします。", "warning"
        if status == DownloadStatus.QUEUED:
            return "開始待ち", "muted"
        if status == DownloadStatus.COMPLETED:
            size = human_size(item.total_bytes) if item.total_bytes else ""
            note = item.note or ("保存しました" if size else "完了")
            return (f"{note}  ·  {size}" if size and size not in note else note), "success"
        if status == DownloadStatus.FAILED:
            return (
                item.error_title
                or item.error_message
                or "ダウンロードに失敗しました"
            ), "danger"
        if status == DownloadStatus.CANCELLED:
            return item.note or "キャンセルされました", "muted"
        return item.phase or "", "muted"

    # ---------------------------------------------------------------- events
    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        item = index.data(QueueModel.ItemRole)
        if (
            isinstance(item, QueueItem)
            and event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
        ):
            for action, rect in self._action_rects(
                option.rect, item, option.font
            ).items():
                if rect.contains(event.pos()):
                    self.action_clicked.emit(item.item_id, action)
                    return True
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index) -> bool:  # noqa: N802
        item = index.data(QueueModel.ItemRole)
        if isinstance(item, QueueItem) and event.type() == QEvent.ToolTip:
            for action, rect in self._action_rects(
                option.rect, item, option.font
            ).items():
                if rect.contains(event.pos()):
                    QToolTip.showText(
                        event.globalPos(),
                        self._ACTION_LABELS.get(action, action),
                        view,
                    )
                    return True
        return super().helpEvent(event, view, option, index)


class QueuePage(QWidget):
    def __init__(
        self,
        ctx: AppContext,
        *,
        navigate: Callable[[str], None],
        toast: Callable[..., None],
        open_logs: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._navigate = navigate
        self._toast = toast
        self._open_logs = open_logs
        self._model: QueueModel = ctx.queue_model
        self._search_action = None
        self._proxy = QueueFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._empty_action = "add"
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(220)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.setInterval(1100)
        self._highlight_timer.timeout.connect(self._clear_highlight)
        self._build_ui()
        self._model.stats_changed.connect(self._schedule_stats)
        self._model.item_added.connect(self._on_item_added)
        self._model.item_removed.connect(lambda _item_id: self._schedule_stats())
        self._proxy.rowsInserted.connect(lambda *_: self._sync_view_state())
        self._proxy.rowsRemoved.connect(lambda *_: self._sync_view_state())
        self._proxy.modelReset.connect(self._sync_view_state)
        self._proxy.layoutChanged.connect(self._sync_view_state)
        self._refresh_stats()
        self._sync_view_state()
        self._update_action_states()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 22)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        header_text = QVBoxLayout()
        header_text.setSpacing(3)
        header_text.addWidget(make_label("ダウンロードキュー", "h1"))
        header_text.addWidget(
            make_label(
                "進行中のダウンロードと待機中の項目をまとめて管理します。",
                "secondary",
            )
        )
        header.addLayout(header_text, 1)

        self.resume_all_button = make_button(
            "すべて再開",
            "secondary",
            icon_name="play",
            parent=self,
            tooltip="停止中の項目を再開します",
        )
        self.resume_all_button.clicked.connect(self._resume_all)
        header.addWidget(self.resume_all_button)
        self.pause_all_button = make_button(
            "すべて停止",
            "secondary",
            icon_name="pause",
            parent=self,
            tooltip="待機中・進行中の項目を一時停止します",
        )
        self.pause_all_button.clicked.connect(self._pause_all)
        header.addWidget(self.pause_all_button)
        self.clear_button = make_button(
            "完了を削除",
            "ghost",
            icon_name="trash",
            parent=self,
            tooltip="完了した項目をキューから取り除きます",
        )
        self.clear_button.clicked.connect(self._clear_finished)
        header.addWidget(self.clear_button)
        root.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self._cards = {
            "active": StatCard("download", "処理中", "accent", self),
            "queued": StatCard("clock", "待機中", "muted", self),
            "completed": StatCard("check-circle", "完了", "success", self),
            "failed": StatCard("alert-circle", "失敗", "danger", self),
        }
        for card in self._cards.values():
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            stats.addWidget(card, 1)
        root.addLayout(stats)

        toolbar = Card(self)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(10)
        self.filter = SegmentedControl(
            [
                ("all", "すべて"),
                ("active", "処理中"),
                ("queued", "待機"),
                ("paused", "一時停止"),
                ("completed", "完了"),
                ("failed", "失敗"),
            ],
            value="all",
            parent=toolbar,
            compact=True,
        )
        self.filter.setMinimumWidth(400)
        self.filter.changed.connect(self._on_filter_changed)
        toolbar_layout.addWidget(self.filter, 0)
        toolbar_layout.addStretch(1)

        self.search = QLineEdit(toolbar)
        self.search.setPlaceholderText("タイトル・サイトで検索")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("キューを検索")
        self.search.setMinimumHeight(34)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._proxy.set_search)
        self.search.textChanged.connect(lambda _text: self._sync_view_state())
        toolbar_layout.addWidget(self.search, 0)

        self.selection_buttons = QWidget(toolbar)
        selection_layout = QHBoxLayout(self.selection_buttons)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(4)
        self.pause_button = make_icon_button(
            "pause", "選択項目を一時停止", size=16, parent=self.selection_buttons
        )
        self.pause_button.clicked.connect(self._pause_selected)
        self.resume_button = make_icon_button(
            "play", "選択項目を再開", size=16, parent=self.selection_buttons
        )
        self.resume_button.clicked.connect(self._resume_selected)
        self.open_button = make_icon_button(
            "folder-open", "保存先を開く", size=16, parent=self.selection_buttons
        )
        self.open_button.clicked.connect(self._open_selected)
        self.remove_button = make_icon_button(
            "trash", "選択項目を削除", size=16, parent=self.selection_buttons
        )
        self.remove_button.clicked.connect(self._remove_selected)
        for button in (
            self.pause_button,
            self.resume_button,
            self.open_button,
            self.remove_button,
        ):
            selection_layout.addWidget(button)
        toolbar_layout.addWidget(self.selection_buttons)
        root.addWidget(toolbar)

        self.banner = MessageBanner(self)
        self.banner.action_clicked.connect(self._retry_selected)
        root.addWidget(self.banner)

        self.list_card = Card(self)
        list_layout = QVBoxLayout(self.list_card)
        list_layout.setContentsMargins(6, 6, 6, 6)
        list_layout.setSpacing(0)
        self.stack = QStackedWidget(self.list_card)
        self.list = QListView(self.stack)
        self.list.setModel(self._proxy)
        self.list.setObjectName("queueList")
        self.list.setAccessibleName("ダウンロードキュー")
        self.delegate = QueueDelegate(self.list)
        self.delegate.action_clicked.connect(self._on_row_action)
        self.list.setItemDelegate(self.delegate)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(0)
        self.list.setFocusPolicy(Qt.StrongFocus)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self.list.doubleClicked.connect(self._on_double_click)
        self.list.selectionModel().selectionChanged.connect(
            lambda *_: self._on_selection_changed()
        )
        self.stack.addWidget(self.list)

        self.empty = EmptyState(
            "download-cloud",
            "キューは空です",
            "ホーム画面で URL を解析し、ダウンロードを追加するとここに表示されます。",
            action_text="動画を追加",
            parent=self.stack,
        )
        self.empty.action_clicked.connect(self._on_empty_action)
        self.stack.addWidget(self.empty)
        list_layout.addWidget(self.stack)
        root.addWidget(self.list_card, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        self.count_label = make_label("", "caption")
        footer.addWidget(self.count_label, 1)
        footer.addWidget(
            make_label("ダブルクリックで保存先を開く  ·  Delete で削除", "caption")
        )
        root.addLayout(footer)

    # --------------------------------------------------------------- helpers
    def _schedule_stats(self) -> None:
        if not self._stats_timer.isActive():
            self._stats_timer.start()

    def _on_item_added(self, item: QueueItem) -> None:
        self._schedule_stats()
        if getattr(self, "delegate", None) is not None:
            self.delegate.highlight_id = item.item_id
            self.list.viewport().update()
            self._highlight_timer.start()

    def _clear_highlight(self) -> None:
        if getattr(self, "delegate", None) is not None:
            self.delegate.highlight_id = None
            self.list.viewport().update()

    def _refresh_stats(self) -> None:
        stats = self._model.stats()
        self._cards["active"].set_value(stats["active"])
        self._cards["queued"].set_value(stats["queued"])
        self._cards["completed"].set_value(stats["completed"])
        self._cards["failed"].set_value(stats["failed"] + stats["cancelled"])
        self._sync_view_state()

    def _sync_view_state(self) -> None:
        count = self._proxy.rowCount()
        total = self._model.rowCount()
        if count == 0:
            if total == 0:
                self._empty_action = "add"
                self.empty.set_content(
                    "download-cloud",
                    "キューは空です",
                    "ホーム画面で URL を解析し、ダウンロードを追加するとここに表示されます。",
                    "動画を追加",
                )
            else:
                self._empty_action = "clear"
                self.empty.set_content(
                    "search",
                    "条件に一致する項目がありません",
                    "検索語やフィルターを変更すると、ほかの項目を表示できます。",
                    "条件をクリア",
                )
            self.stack.setCurrentWidget(self.empty)
            fade_in(self.empty, duration=140)
        else:
            self.stack.setCurrentWidget(self.list)
        self.count_label.setText(
            f"{count} 件を表示中" if count != total else f"{total} 件"
        )
        self._update_action_states()

    def _selected_items(self) -> list[QueueItem]:
        selection = self.list.selectionModel()
        if selection is None:
            return []
        items: list[QueueItem] = []
        for index in selection.selectedRows():
            source = self._proxy.mapToSource(index)
            item = self._model.item_at(source.row())
            if item is not None:
                items.append(item)
        return items

    def _on_selection_changed(self) -> None:
        self._update_action_states()
        self._update_banner()

    def _update_banner(self) -> None:
        items = self._selected_items()
        if len(items) != 1:
            self.banner.hide()
            return
        item = items[0]
        if item.status == DownloadStatus.FAILED and (
            item.error_title or item.error_message
        ):
            self.banner.show_message(
                "error",
                item.error_title or "ダウンロードに失敗しました",
                item.error_message,
                item.error_remedy,
            )
            self.banner.set_action("再試行", "retry")
            self.banner.show()
            return
        if item.status == DownloadStatus.COMPLETED and item.output_path:
            from pathlib import Path

            try:
                exists = Path(item.output_path).is_file()
            except OSError:
                exists = False
            if not exists:
                self.banner.show_message(
                    "warning",
                    "保存したファイルが見つかりません",
                    "移動または削除された可能性があります。保存先フォルダーを確認してください。",
                    "設定の保存先を開くか、もう一度ダウンロードしてください。",
                )
                self.banner.set_action("フォルダーを開く", "folder-open")
                self.banner.show()
                return
        self.banner.hide()

    def _update_action_states(self) -> None:
        items = self._selected_items()
        self.selection_buttons.setVisible(bool(items))
        can_pause = any(
            item.status
            in (
                DownloadStatus.QUEUED,
                DownloadStatus.DOWNLOADING,
                DownloadStatus.ANALYZING,
            )
            for item in items
        )
        can_resume = any(
            item.status
            in (
                DownloadStatus.PAUSED,
                DownloadStatus.FAILED,
                DownloadStatus.CANCELLED,
            )
            for item in items
        )
        can_open = any(
            item.status == DownloadStatus.COMPLETED and item.output_path
            for item in items
        )
        self.pause_button.setEnabled(can_pause)
        self.resume_button.setEnabled(can_resume)
        self.open_button.setEnabled(can_open)
        self.remove_button.setEnabled(bool(items))
        counts = self._model.stats()
        self.clear_button.setEnabled(counts["completed"] + counts["cancelled"] > 0)
        self.pause_all_button.setEnabled(counts["active"] + counts["queued"] > 0)
        self.resume_all_button.setEnabled(
            counts["paused"] + counts["failed"] + counts["cancelled"] > 0
        )

    # --------------------------------------------------------------- actions
    def _on_row_action(self, item_id: str, action: str) -> None:
        if action == "pause":
            self.ctx.queue.pause(item_id)
        elif action == "resume":
            self.ctx.queue.resume(item_id)
        elif action == "retry":
            self.ctx.queue.retry(item_id)
        elif action == "cancel":
            self.ctx.queue.cancel(item_id)
        elif action == "remove":
            self.ctx.queue.remove(item_id)
        elif action == "open":
            self._open_item(item_id)

    def _pause_selected(self) -> None:
        for item in self._selected_items():
            self.ctx.queue.pause(item.item_id)
        self._refresh_stats()

    def _resume_selected(self) -> None:
        for item in self._selected_items():
            self.ctx.queue.resume(item.item_id)
        self._refresh_stats()

    def _retry_selected(self) -> None:
        items = self._selected_items()
        if len(items) == 1 and items[0].status == DownloadStatus.COMPLETED:
            self._open_item(items[0].item_id)
            return
        for item in items:
            if item.status.is_final:
                self.ctx.queue.retry(item.item_id)
        self._refresh_stats()

    def _remove_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        if any(item.status.is_active for item in items):
            confirmed = ConfirmDialog.ask(
                self,
                "進行中の項目を削除しますか？",
                "選択した項目には進行中のダウンロードが含まれています。削除するとダウンロードはキャンセルされます。",
                confirm_text="削除する",
                danger=True,
                detail="保存済みのファイルは削除されません。",
            )
            if not confirmed:
                return
        for item in items:
            self.ctx.queue.remove(item.item_id)
        self._refresh_stats()
        self._toast("キューから削除しました", f"{len(items)} 件の項目を削除しました。", "info")

    def _open_selected(self) -> None:
        for item in self._selected_items():
            self._open_item(item.item_id)

    def _open_item(self, item_id: str) -> None:
        item = self._model.find(item_id)
        path = self.ctx.queue.open_folder(item_id)
        if not path:
            self._toast(
                "フォルダーを開けません",
                "保存先が見つかりませんでした。設定を確認してください。",
                "warning",
            )
            return
        if item is not None:
            logger.debug("保存先を開きました: %s", path)

    def _pause_all(self) -> None:
        self.ctx.queue.pause_all()
        self._refresh_stats()

    def _resume_all(self) -> None:
        self.ctx.queue.resume_all()
        self._refresh_stats()

    def _clear_finished(self) -> None:
        stats = self._model.stats()
        count = stats["completed"] + stats["cancelled"]
        if count == 0:
            self._toast(
                "削除する項目がありません", "完了したダウンロードはまだありません。", "info"
            )
            return
        confirmed = ConfirmDialog.ask(
            self,
            "完了した項目を削除しますか？",
            f"{count} 件の完了・キャンセル済み項目をキューから取り除きます。",
            confirm_text="削除する",
            detail="履歴と保存済みのファイルは残ります。",
        )
        if not confirmed:
            return
        removed = self.ctx.queue.clear_finished()
        self._refresh_stats()
        self._toast("キューを整理しました", f"{removed} 件の項目を削除しました。", "success")

    def _on_filter_changed(self, mode: str) -> None:
        self._proxy.set_mode(mode)
        self._sync_view_state()

    def _on_empty_action(self) -> None:
        if self._empty_action == "clear":
            self.search.clear()
            self.filter.set_value("all", emit=False)
            self._proxy.set_mode("all")
            self._proxy.set_search("")
            self._sync_view_state()
        else:
            self._navigate("home")

    def _on_double_click(self, index) -> None:
        source = self._proxy.mapToSource(index)
        item = self._model.item_at(source.row())
        if item is None:
            return
        if item.status == DownloadStatus.COMPLETED:
            self._open_item(item.item_id)
        elif item.status == DownloadStatus.PAUSED:
            self.ctx.queue.resume(item.item_id)
        elif item.status == DownloadStatus.QUEUED:
            self.ctx.queue.pause(item.item_id)
        elif item.status == DownloadStatus.FAILED:
            self.ctx.queue.retry(item.item_id)

    def _show_context_menu(self, position) -> None:
        index = self.list.indexAt(position)
        if index.isValid() and not self.list.selectionModel().isSelected(index):
            self.list.setCurrentIndex(index)
        items = self._selected_items()
        if not items:
            return
        first = items[0]
        menu = QMenu(self)
        if first.status == DownloadStatus.COMPLETED:
            open_action = menu.addAction(
                icon("folder-open", current_palette().text_secondary, 16),
                "保存先を開く",
            )
            open_action.triggered.connect(self._open_selected)
            page_action = menu.addAction(
                icon("external", current_palette().text_secondary, 16),
                "元のページを開く",
            )
            page_action.triggered.connect(lambda: self._open_source(first.url))
        else:
            label = "再開" if first.status == DownloadStatus.PAUSED else "一時停止"
            play_action = menu.addAction(
                icon(
                    "play" if first.status == DownloadStatus.PAUSED else "pause",
                    current_palette().text_secondary,
                    16,
                ),
                label,
            )
            play_action.triggered.connect(
                self._resume_selected
                if first.status == DownloadStatus.PAUSED
                else self._pause_selected
            )
            if first.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                retry_action = menu.addAction(
                    icon("retry", current_palette().text_secondary, 16), "再試行"
                )
                retry_action.triggered.connect(self._retry_selected)
        menu.addSeparator()
        copy_action = menu.addAction(
            icon("copy", current_palette().text_secondary, 16), "URL をコピー"
        )
        copy_action.triggered.connect(lambda: self._copy_url(first.url))
        menu.addSeparator()
        remove_action = menu.addAction(
            icon("trash", current_palette().danger, 16), "キューから削除"
        )
        remove_action.triggered.connect(self._remove_selected)
        menu.exec(self.list.viewport().mapToGlobal(position))

    def _open_source(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ...core.security import validate_url

        validation = validate_url(url, allow_private=True)
        if validation:
            QDesktopServices.openUrl(QUrl(validation.url))

    def _copy_url(self, url: str) -> None:
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(url)
            self._toast("URL をコピーしました", "クリップボードから貼り付けられます。", "success")

    # --------------------------------------------------------------- keyboard
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Delete:
            self._remove_selected()
            return
        if event.key() == Qt.Key_Space:
            items = self._selected_items()
            for item in items:
                if item.status == DownloadStatus.PAUSED:
                    self.ctx.queue.resume(item.item_id)
                elif item.status in (
                    DownloadStatus.QUEUED,
                    DownloadStatus.DOWNLOADING,
                    DownloadStatus.ANALYZING,
                ):
                    self.ctx.queue.pause(item.item_id)
            if items:
                self._refresh_stats()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- theming
    def refresh_theme(self) -> None:
        refresh_named_icons(self)
        self._refresh_search_icon()
        for card in self._cards.values():
            card.refresh_theme()
        self.empty.refresh_theme()
        self.filter.refresh_theme()
        self.list.viewport().update()

    def _refresh_search_icon(self) -> None:
        pixmap = icon("search", current_palette().text_muted, 15)
        if self._search_action is None:
            self._search_action = self.search.addAction(pixmap, QLineEdit.LeadingPosition)
            self._search_action.setEnabled(False)
        else:
            self._search_action.setIcon(pixmap)

    def on_settings_changed(self) -> None:
        # MainWindow already applied queue settings before notifying pages.
        self._refresh_stats()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_search_icon()
        self._refresh_stats()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()
