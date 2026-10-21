from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
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
    QVBoxLayout,
    QWidget,
)

from ...core.history import HistoryEntry
from ...core.utils import human_duration, human_size, relative_time
from ..context import AppContext
from ..dialogs import ConfirmDialog
from ..icons import icon
from ..theme import current_palette, path_font, scaled_font
from ..widgets import (
    Card,
    EmptyState,
    StatCard,
    fade_in,
    make_button,
    make_label,
    refresh_named_icons,
)

logger = logging.getLogger(__name__)


class HistoryModel(QAbstractListModel):
    EntryRole = int(Qt.UserRole) + 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[HistoryEntry] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == self.EntryRole:
            return entry
        if role == Qt.DisplayRole:
            return entry.title
        if role == Qt.ToolTipRole:
            return f"{entry.title}\n{entry.filepath or entry.save_dir}"
        return None

    def set_entries(self, entries: list[HistoryEntry]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def entries(self) -> list[HistoryEntry]:
        return list(self._entries)

    def entry_at(self, row: int) -> HistoryEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None


_LAYOUT_CACHE: dict[tuple[str, int], dict[str, object]] = {}


def _history_layout(font: QFont) -> dict[str, object]:
    """Derive row geometry from the actual font metrics.

    Keeps Japanese titles and paths fully visible when the user increases
    Windows text scaling instead of clipping them inside a fixed 94 px row.
    The delegate asks for the same layout several times per row and frame,
    so cache it by the Qt font cache key.
    """
    cache_key = (font.key(), QFontMetrics(font).height())
    cached = _LAYOUT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    title_font = scaled_font(font, 1.06, QFont.DemiBold)
    meta_font = scaled_font(font, 0.88)
    pill_font = scaled_font(font, 0.84, QFont.DemiBold)

    location_font = path_font(meta_font)
    title_h = max(22, QFontMetrics(title_font).height() + 2)
    meta_h = max(18, QFontMetrics(meta_font).height() + 2)
    location_h = max(meta_h, QFontMetrics(location_font).height() + 2)
    pill_h = max(21, QFontMetrics(pill_font).height() + 2)

    title_top = 12
    meta_top = title_top + title_h + 4
    location_top = meta_top + meta_h + 2
    row_height = location_top + location_h + 18
    layout = {
        "title_font": title_font,
        "meta_font": meta_font,
        "location_font": location_font,
        "pill_font": pill_font,
        "title_h": title_h,
        "meta_h": meta_h,
        "location_h": location_h,
        "pill_h": pill_h,
        "title_top": title_top,
        "meta_top": meta_top,
        "location_top": location_top,
        "row_height": row_height,
    }
    if len(_LAYOUT_CACHE) > 16:
        _LAYOUT_CACHE.clear()
    _LAYOUT_CACHE[cache_key] = layout
    return layout


class HistoryDelegate(QStyledItemDelegate):
    open_clicked = Signal(int)

    ROW_HEIGHT = 94

    def __init__(self, thumbnails, parent=None) -> None:
        super().__init__(parent)
        self._thumbnails = thumbnails
        self._file_state: dict[str, bool] = {}

    def clear_file_cache(self) -> None:
        self._file_state.clear()

    def _file_exists(self, entry: HistoryEntry) -> bool:
        key = entry.filepath or f"id:{entry.id}"
        if key not in self._file_state:
            self._file_state[key] = entry.file_exists
        return self._file_state[key]

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        layout = _history_layout(option.font)
        return QSize(max(300, option.rect.width()), int(layout["row_height"]))

    def _open_rect(self, rect: QRect, font: QFont) -> QRect:
        row_height = int(_history_layout(font)["row_height"])
        top = rect.top() + max(34, (row_height - 32) // 2)
        return QRect(rect.right() - 52, top, 32, 32)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        entry = index.data(HistoryModel.EntryRole)
        if not isinstance(entry, HistoryEntry):
            return
        palette = current_palette()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = QRectF(option.rect).adjusted(2, 3, -2, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        background = palette.accent_soft if selected else (palette.surface_hover if hovered else palette.card)
        border_color = palette.accent if selected else (palette.border_strong if hovered else palette.border)
        painter.setPen(QPen(QColor(border_color), 1.3 if selected else 1.0))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 14, 14)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(palette.accent))
            painter.drawRoundedRect(
                QRectF(rect.left() + 1.5, rect.top() + 16, 3, rect.height() - 32),
                1.5,
                1.5,
            )

        thumb_rect = QRectF(rect.left() + 14, rect.top() + 14, 104, 58)
        path = QPainterPath()
        path.addRoundedRect(thumb_rect, 9, 9)
        painter.save()
        painter.setClipPath(path)
        pixmap = self._thumbnails.load(entry.thumbnail) if entry.thumbnail else None
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                thumb_rect.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            source = QRectF(
                (scaled.width() - thumb_rect.width()) / 2,
                (scaled.height() - thumb_rect.height()) / 2,
                thumb_rect.width(),
                thumb_rect.height(),
            )
            painter.drawPixmap(thumb_rect, scaled, source)
        else:
            gradient = QLinearGradient(thumb_rect.topLeft(), thumb_rect.bottomRight())
            gradient.setColorAt(0, QColor(palette.surface_alt))
            gradient.setColorAt(1, QColor(palette.accent_soft))
            painter.fillPath(path, gradient)
            glyph = icon("film", palette.text_muted, 22)
            glyph.paint(
                painter,
                QRect(
                    int(thumb_rect.center().x() - 11),
                    int(thumb_rect.center().y() - 11),
                    22,
                    22,
                ),
            )
        painter.restore()
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(thumb_rect.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)

        text_x = thumb_rect.right() + 14
        right = rect.right() - 16
        layout = _history_layout(option.font)
        open_rect = self._open_rect(option.rect, option.font)

        # Availability pill.  Stat the path once per entry and reuse the
        # result until the list is reloaded; delegates repaint on every scroll
        # and animation frame.
        file_exists = self._file_exists(entry)
        pill_font = layout["pill_font"]
        pill_text = "ファイルあり" if file_exists else "見つかりません"
        pill_color = palette.success if file_exists else palette.text_muted
        pill_soft = palette.success_soft if file_exists else palette.surface_alt
        metrics = QFontMetrics(pill_font)
        pill_width = metrics.horizontalAdvance(pill_text) + 18
        pill_rect = QRectF(
            right - pill_width - 42,
            rect.top() + 14,
            pill_width,
            int(layout["pill_h"]),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(pill_soft))
        painter.drawRoundedRect(pill_rect, 8, 8)
        painter.setFont(pill_font)
        painter.setPen(QColor(pill_color))
        painter.drawText(pill_rect, Qt.AlignCenter, pill_text)

        title_font = layout["title_font"]
        title_metrics = QFontMetrics(title_font)
        title_width = max(40, pill_rect.left() - text_x - 10)
        painter.setFont(title_font)
        painter.setPen(QColor(palette.text))
        painter.drawText(
            QRectF(
                text_x,
                rect.top() + int(layout["title_top"]),
                title_width,
                int(layout["title_h"]),
            ),
            Qt.AlignLeft | Qt.AlignVCenter,
            title_metrics.elidedText(entry.title, Qt.ElideRight, int(title_width)),
        )

        meta_font = layout["meta_font"]
        meta_metrics = QFontMetrics(meta_font)
        meta_bits = [bit for bit in (entry.extractor, human_duration(entry.duration)) if bit]
        if entry.filesize:
            meta_bits.append(human_size(entry.filesize))
        meta_bits.append(relative_time(entry.completed_at))
        meta_width = max(40, right - text_x - 48)
        painter.setFont(meta_font)
        painter.setPen(QColor(palette.text_muted))
        painter.drawText(
            QRectF(
                text_x,
                rect.top() + int(layout["meta_top"]),
                meta_width,
                int(layout["meta_h"]),
            ),
            Qt.AlignLeft | Qt.AlignVCenter,
            meta_metrics.elidedText(
                "  ·  ".join(meta_bits), Qt.ElideRight, int(meta_width)
            ),
        )

        location = entry.filepath or entry.save_dir or "—"
        location_font = layout["location_font"]
        location_metrics = QFontMetrics(location_font)
        painter.setFont(location_font)
        painter.setPen(QColor(palette.text_muted))
        painter.drawText(
            QRectF(
                text_x,
                rect.top() + int(layout["location_top"]),
                meta_width,
                int(layout["location_h"]),
            ),
            Qt.AlignLeft | Qt.AlignVCenter,
            location_metrics.elidedText(location, Qt.ElideMiddle, int(meta_width)),
        )

        painter.setPen(QPen(QColor(palette.border), 1))
        painter.setBrush(QColor(palette.surface_alt))
        painter.drawRoundedRect(QRectF(open_rect), 9, 9)
        glyph = icon("folder-open", palette.text_secondary, 16)
        glyph.paint(painter, open_rect.adjusted(8, 8, -8, -8))
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        entry = index.data(HistoryModel.EntryRole)
        if (
            isinstance(entry, HistoryEntry)
            and event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
            and self._open_rect(option.rect, option.font).contains(event.pos())
        ):
            self.open_clicked.emit(entry.id)
            return True
        return super().editorEvent(event, model, option, index)


class HistoryPage(QWidget):
    def __init__(
        self,
        ctx: AppContext,
        *,
        navigate: Callable[[str], None],
        toast: Callable[..., None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._navigate = navigate
        self._toast = toast
        self._model = HistoryModel(self)
        self._search_action = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(260)
        self._search_timer.timeout.connect(self.reload)
        self._build_ui()
        self.ctx.thumbnails.loaded.connect(self._on_thumbnail_loaded)
        self.ctx.thumbnails.failed.connect(self._on_thumbnail_failed)
        self.reload()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 22)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(make_label("ダウンロード履歴", "h1"))
        text.addWidget(
            make_label(
                "完了したダウンロードを端末内に記録します。履歴からファイルをすぐに開けます。",
                "secondary",
            )
        )
        header.addLayout(text, 1)
        self.open_dir_button = make_button(
            "保存先を開く", "secondary", icon_name="folder-open", parent=self
        )
        self.open_dir_button.clicked.connect(self._open_save_dir)
        header.addWidget(self.open_dir_button)
        self.refresh_button = make_button("更新", "secondary", icon_name="refresh", parent=self)
        self.refresh_button.clicked.connect(self.reload)
        header.addWidget(self.refresh_button)
        self.clear_button = make_button("履歴を消去", "ghost", icon_name="trash", parent=self)
        self.clear_button.clicked.connect(self._clear_history)
        header.addWidget(self.clear_button)
        root.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self._total_card = StatCard("database", "保存した本数", "accent", self)
        self._week_card = StatCard("clock", "過去 7 日間", "success", self)
        self._size_card = StatCard("file", "表示中の合計サイズ", "muted", self)
        for card in (self._total_card, self._week_card, self._size_card):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            stats.addWidget(card, 1)
        root.addLayout(stats)

        toolbar = Card(self)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(10)
        self.search = QLineEdit(toolbar)
        self.search.setPlaceholderText("タイトル・サイト・URL で検索")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("履歴を検索")
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        toolbar_layout.addWidget(self.search, 1)
        self.count_label = make_label("", "caption")
        toolbar_layout.addWidget(self.count_label)
        root.addWidget(toolbar)

        self.list_card = Card(self)
        layout = QVBoxLayout(self.list_card)
        layout.setContentsMargins(6, 6, 6, 6)
        self.stack = QStackedWidget(self.list_card)
        self.list = QListView(self.stack)
        self.list.setObjectName("historyList")
        self.list.setModel(self._model)
        self.list.setAccessibleName("ダウンロード履歴")
        self.delegate = HistoryDelegate(self.ctx.thumbnails, self.list)
        self.delegate.open_clicked.connect(self._open_entry_by_id)
        self.list.setItemDelegate(self.delegate)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setFocusPolicy(Qt.StrongFocus)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self.list.doubleClicked.connect(self._on_double_click)
        self.stack.addWidget(self.list)
        self.empty = EmptyState(
            "history",
            "まだ履歴がありません",
            "ダウンロードが完了すると、ここからファイルを開いたり保存先を確認できます。",
            action_text="動画を追加",
            parent=self.stack,
        )
        self.empty.action_clicked.connect(self._on_empty_action)
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack)
        root.addWidget(self.list_card, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        footer.addWidget(make_label("履歴は設定した件数を超えると古いものから削除されます。", "caption"), 1)
        footer.addWidget(make_label("ダブルクリックでファイルを開く  ·  Delete で履歴から削除", "caption"))
        root.addLayout(footer)

    # ----------------------------------------------------------------- data
    def reload(self) -> None:
        query = self.search.text().strip()
        try:
            entries = self.ctx.history.entries(search=query, limit=600)
        except Exception as exc:  # noqa: BLE001 - database errors are user-visible
            logger.error("履歴を読み込めませんでした: %s", exc)
            self._toast(
                "履歴を読み込めませんでした",
                "履歴データベースを開けませんでした。診断画面でログを確認してください。",
                "error",
            )
            entries = []
        self.delegate.clear_file_cache()
        self._model.set_entries(entries)
        self._update_summary(entries)
        self._sync_view_state()

    def _update_summary(self, entries: list[HistoryEntry]) -> None:
        try:
            total = self.ctx.history.count()
        except Exception:
            total = len(entries)
        week_ago = time.time() - 7 * 86400
        try:
            this_week = self.ctx.history.count_since(week_ago)
        except Exception:
            this_week = sum(1 for entry in entries if entry.completed_at >= week_ago)
        total_size = sum(entry.filesize or 0 for entry in entries)
        self._total_card.set_value(total)
        self._week_card.set_value(this_week)
        self._size_card.set_value(human_size(total_size))
        self.clear_button.setEnabled(total > 0)

    def _sync_view_state(self) -> None:
        count = self._model.rowCount()
        searching = bool(self.search.text().strip())
        if count == 0:
            if searching:
                self.empty.set_content(
                    "search",
                    "一致する履歴がありません",
                    "検索語を短くするか、別のキーワードでお試しください。",
                    "検索をクリア",
                )
                self._empty_action = "clear"
            else:
                self.empty.set_content(
                    "history",
                    "まだ履歴がありません",
                    "ダウンロードが完了すると、ここからファイルを開いたり保存先を確認できます。",
                    "動画を追加",
                )
                self._empty_action = "add"
            self.stack.setCurrentWidget(self.empty)
            fade_in(self.empty, duration=140)
        else:
            self.stack.setCurrentWidget(self.list)
        self.count_label.setText(f"{count} 件を表示" if searching else f"{count} 件")

    def _on_empty_action(self) -> None:
        if self._empty_action == "clear":
            self.search.clear()
            self.reload()
        else:
            self._navigate("home")

    def _selected_entries(self) -> list[HistoryEntry]:
        selection = self.list.selectionModel()
        if selection is None:
            return []
        entries = []
        for index in selection.selectedRows():
            entry = self._model.entry_at(index.row())
            if entry is not None:
                entries.append(entry)
        return entries

    # --------------------------------------------------------------- actions
    def _on_thumbnail_loaded(self, _url: str, _pixmap) -> None:
        self.list.viewport().update()

    def _on_thumbnail_failed(self, _url: str) -> None:
        self.list.viewport().update()

    def _open_entry_by_id(self, entry_id: int) -> None:
        for entry in self._model.entries():
            if entry.id == entry_id:
                self._open_entry(entry)
                return

    def _open_entry(self, entry: HistoryEntry) -> None:
        target = Path(entry.filepath) if entry.filepath else None
        if target and target.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            return
        folder = Path(entry.save_dir) if entry.save_dir else (target.parent if target else None)
        if folder and folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            self._toast(
                "ファイルが見つかりません",
                "保存先フォルダーを開きました。ファイルが移動・削除されていないか確認してください。",
                "warning",
            )
            return
        self._toast(
            "ファイルを開けません",
            "保存先が見つかりませんでした。設定の保存先を確認してください。",
            "warning",
        )

    def _open_save_dir(self) -> None:
        folder = Path(self.ctx.settings.save_dir)
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self._toast(
                "保存先を開けません",
                "設定されている保存先フォルダーが見つかりません。",
                "warning",
            )

    def _on_double_click(self, index) -> None:
        entry = self._model.entry_at(index.row())
        if entry is not None:
            self._open_entry(entry)

    def _remove_selected(self) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        confirmed = ConfirmDialog.ask(
            self,
            "履歴から削除しますか？",
            f"{len(entries)} 件の履歴を削除します。",
            confirm_text="削除する",
            detail="保存済みのファイルは削除されません。",
        )
        if not confirmed:
            return
        try:
            self.ctx.history.delete([entry.id for entry in entries])
        except Exception as exc:  # noqa: BLE001
            logger.error("履歴を削除できませんでした: %s", exc)
            self._toast("履歴を削除できませんでした", str(exc), "error")
            return
        self.reload()
        self._toast("履歴を削除しました", f"{len(entries)} 件の項目を削除しました。", "success")

    def _clear_history(self) -> None:
        try:
            total = self.ctx.history.count()
        except Exception:
            total = 0
        if total == 0:
            self._toast("履歴は空です", "削除する履歴がありません。", "info")
            return
        confirmed = ConfirmDialog.ask(
            self,
            "すべての履歴を削除しますか？",
            f"{total} 件のダウンロード履歴を消去します。",
            confirm_text="すべて削除",
            danger=True,
            detail="保存済みのファイルとキューは削除されません。この操作は元に戻せません。",
        )
        if not confirmed:
            return
        try:
            self.ctx.history.clear()
        except Exception as exc:  # noqa: BLE001
            logger.error("履歴を消去できませんでした: %s", exc)
            self._toast("履歴を消去できませんでした", str(exc), "error")
            return
        self.reload()
        self._toast("履歴を消去しました", "保存済みのファイルはそのまま残っています。", "success")

    def _copy_url(self, entry: HistoryEntry) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(entry.url)
            self._toast("URL をコピーしました", entry.url, "success")

    def _open_source(self, entry: HistoryEntry) -> None:
        from ...core.security import validate_url

        validation = validate_url(entry.url, allow_private=True)
        if validation:
            QDesktopServices.openUrl(QUrl(validation.url))

    def _show_context_menu(self, position) -> None:
        index = self.list.indexAt(position)
        if index.isValid() and not self.list.selectionModel().isSelected(index):
            self.list.setCurrentIndex(index)
        entries = self._selected_entries()
        if not entries:
            return
        first = entries[0]
        menu = QMenu(self)
        open_action = menu.addAction(icon("external", current_palette().text_secondary, 16), "ファイルを開く")
        open_action.triggered.connect(lambda: self._open_entry(first))
        folder_action = menu.addAction(
            icon("folder-open", current_palette().text_secondary, 16), "保存先を開く"
        )
        folder_action.triggered.connect(self._open_save_dir)
        page_action = menu.addAction(icon("globe", current_palette().text_secondary, 16), "元のページを開く")
        page_action.triggered.connect(lambda: self._open_source(first))
        copy_action = menu.addAction(icon("copy", current_palette().text_secondary, 16), "URL をコピー")
        copy_action.triggered.connect(lambda: self._copy_url(first))
        menu.addSeparator()
        remove_action = menu.addAction(icon("trash", current_palette().danger, 16), "履歴から削除")
        remove_action.triggered.connect(self._remove_selected)
        menu.exec(self.list.viewport().mapToGlobal(position))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Delete:
            self._remove_selected()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- theming
    def refresh_theme(self) -> None:
        refresh_named_icons(self)
        self._refresh_search_icon()
        self._total_card.refresh_theme()
        self._week_card.refresh_theme()
        self._size_card.refresh_theme()
        self.empty.refresh_theme()
        self.list.viewport().update()

    def _refresh_search_icon(self) -> None:
        pixmap = icon("search", current_palette().text_muted, 15)
        if self._search_action is None:
            self._search_action = self.search.addAction(pixmap, QLineEdit.LeadingPosition)
            self._search_action.setEnabled(False)
        else:
            self._search_action.setIcon(pixmap)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_search_icon()
        self.reload()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()
