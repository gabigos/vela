from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import (
    QAbstractListModel,
    QCoreApplication,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)

from .downloader import DownloadResult, DownloadWorker
from .history import HistoryStore
from .models import DownloadStatus, ProgressSnapshot, QueueItem
from .paths import AppPaths
from .settings import Settings
from .utils import human_size

logger = logging.getLogger(__name__)


class QueueModel(QAbstractListModel):
    ItemRole = int(Qt.UserRole) + 1
    StatusRole = int(Qt.UserRole) + 2
    PercentRole = int(Qt.UserRole) + 3
    IdRole = int(Qt.UserRole) + 4

    stats_changed = Signal()
    item_added = Signal(object)
    item_removed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[QueueItem] = []
        self._index: dict[str, int] = {}

    # ---- Qt model API -------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.ItemRole:
            return item
        if role == self.IdRole:
            return item.item_id
        if role == self.StatusRole:
            return item.status.value
        if role == self.PercentRole:
            return item.percent
        if role == Qt.DisplayRole:
            return item.title
        if role == Qt.ToolTipRole:
            return f"{item.title}\n{item.url}"
        return None

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ItemRole: b"item",
            self.IdRole: b"itemId",
            self.StatusRole: b"status",
            self.PercentRole: b"percent",
            Qt.DisplayRole: b"title",
        }

    # ---- convenience --------------------------------------------------
    def items(self) -> list[QueueItem]:
        return list(self._items)

    def item_at(self, row: int) -> QueueItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def row_for_id(self, item_id: str) -> int:
        return self._index.get(item_id, -1)

    def find(self, item_id: str) -> QueueItem | None:
        row = self.row_for_id(item_id)
        return self._items[row] if row >= 0 else None

    def add_item(self, item: QueueItem) -> None:
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items))
        self._items.append(item)
        self._index[item.item_id] = len(self._items) - 1
        self.endInsertRows()
        self.item_added.emit(item)
        self.stats_changed.emit()

    def add_items(self, items: Iterable[QueueItem]) -> None:
        new_items = list(items)
        if not new_items:
            return
        start = len(self._items)
        self.beginInsertRows(QModelIndex(), start, start + len(new_items) - 1)
        self._items.extend(new_items)
        for offset, item in enumerate(new_items):
            self._index[item.item_id] = start + offset
        self.endInsertRows()
        for item in new_items:
            self.item_added.emit(item)
        self.stats_changed.emit()

    def remove_item(self, item_id: str) -> bool:
        row = self.row_for_id(item_id)
        if row < 0:
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        item = self._items.pop(row)
        self._rebuild_index()
        self.endRemoveRows()
        self.item_removed.emit(item.item_id)
        self.stats_changed.emit()
        return True

    def remove_rows(self, rows: Iterable[int]) -> list[QueueItem]:
        removed: list[QueueItem] = []
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self._items):
                self.beginRemoveRows(QModelIndex(), row, row)
                removed.append(self._items.pop(row))
                self.endRemoveRows()
        if removed:
            self._rebuild_index()
            for item in removed:
                self.item_removed.emit(item.item_id)
            self.stats_changed.emit()
        return removed

    def clear(self) -> list[QueueItem]:
        removed = list(self._items)
        if not removed:
            return []
        self.beginResetModel()
        self._items.clear()
        self._index.clear()
        self.endResetModel()
        for item in removed:
            self.item_removed.emit(item.item_id)
        self.stats_changed.emit()
        return removed

    def update_item(self, item_id: str) -> None:
        row = self.row_for_id(item_id)
        if row < 0:
            return
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [self.ItemRole, self.StatusRole, self.PercentRole])

    def refresh_stats(self) -> None:
        self.stats_changed.emit()

    def stats(self) -> dict[str, int]:
        result = {
            "total": len(self._items),
            "active": 0,
            "queued": 0,
            "paused": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        for item in self._items:
            status = item.status
            if status in {
                DownloadStatus.ANALYZING,
                DownloadStatus.DOWNLOADING,
                DownloadStatus.PROCESSING,
                DownloadStatus.CANCELLING,
            }:
                result["active"] += 1
            elif status == DownloadStatus.QUEUED:
                result["queued"] += 1
            elif status == DownloadStatus.PAUSED:
                result["paused"] += 1
            elif status == DownloadStatus.COMPLETED:
                result["completed"] += 1
            elif status == DownloadStatus.FAILED:
                result["failed"] += 1
            elif status == DownloadStatus.CANCELLED:
                result["cancelled"] += 1
        return result

    def _rebuild_index(self) -> None:
        self._index = {item.item_id: row for row, item in enumerate(self._items)}


class QueueFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = "all"
        self._search = ""
        self.setDynamicSortFilter(True)

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._invalidate_filter()

    def set_search(self, text: str) -> None:
        normalized = text.strip().casefold()
        if normalized == self._search:
            return
        self._search = normalized
        self._invalidate_filter()

    def _invalidate_filter(self) -> None:
        # Qt 6.10 deprecates invalidateFilter() in favour of the explicit
        # begin/end pair. Older Qt versions only provide the former.
        begin = getattr(self, "beginFilterChange", None)
        end = getattr(self, "endFilterChange", None)
        if callable(begin) and callable(end):
            begin()
            end()
        else:  # pragma: no cover - retained for Qt < 6.10
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, QueueModel):
            return True
        item = model.item_at(source_row)
        if item is None:
            return False
        if self._search:
            haystack = f"{item.title} {item.uploader} {item.extractor} {item.playlist_title}".casefold()
            if self._search not in haystack:
                return False
        mode = self._mode
        if mode == "all":
            return True
        if mode == "active":
            return item.status.is_active
        if mode == "queued":
            return item.status == DownloadStatus.QUEUED
        if mode == "paused":
            return item.status == DownloadStatus.PAUSED
        if mode == "completed":
            return item.status == DownloadStatus.COMPLETED
        if mode == "failed":
            return item.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED)
        return True


class QueueManager(QObject):
    notification = Signal(str, str, str)  # title, message, kind
    active_count_changed = Signal(int)
    persistence_error = Signal(str)

    def __init__(
        self,
        model: QueueModel,
        settings_provider,
        paths: AppPaths,
        ffmpeg_provider,
        history: HistoryStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self._settings_provider = settings_provider
        self._paths = paths
        self._ffmpeg_provider = ffmpeg_provider
        self._history = history
        self._active: dict[str, tuple[QThread, DownloadWorker]] = {}
        self._removed_ids: set[str] = set()
        self._warnings: list[str] = []
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self.save_state)
        self.model.stats_changed.connect(self._on_stats_changed)
        self._last_active_count = 0
        self._shutting_down = False

    # ---- lifecycle ----------------------------------------------------
    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def enqueue(self, item: QueueItem) -> None:
        self.enqueue_many([item])

    def enqueue_many(self, items: Iterable[QueueItem]) -> int:
        new_items = [item for item in items if item is not None]
        if not new_items:
            return 0
        self.model.add_items(new_items)
        self._schedule_save()
        self._dispatch()
        return len(new_items)

    def load_state(self, restore: bool = True) -> int:
        if not restore or not self._paths.queue_file.exists():
            return 0
        try:
            payload = json.loads(self._paths.queue_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("キューの復元に失敗しました: %s", exc)
            self._warnings.append("前回のキューを復元できませんでした。")
            return 0
        raw_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            return 0
        restored: list[QueueItem] = []
        for raw in raw_items[:500]:
            if not isinstance(raw, dict):
                continue
            item = QueueItem.from_persisted_dict(raw)
            if item is not None:
                restored.append(item)
        if restored:
            self.model.add_items(restored)
            self.model.refresh_stats()
            logger.info("前回のキューから %d 件を復元しました（一時停止状態）", len(restored))
        return len(restored)

    def _schedule_save(self) -> None:
        if self._shutting_down:
            return
        self._save_timer.start()

    def save_state(self) -> None:
        items = [
            item.to_persisted_dict()
            for item in self.model.items()
            if not item.status.is_final and item.item_id not in self._removed_ids
        ]
        payload = {"version": 1, "saved_at": time.time(), "items": items}
        try:
            self._paths.queue_file.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=".queue-", suffix=".tmp", dir=str(self._paths.queue_file.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, self._paths.queue_file)
            finally:
                Path(temp_name).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("キューの保存に失敗しました: %s", exc)
            self.persistence_error.emit("キューの状態を保存できませんでした。")

    # ---- dispatch -----------------------------------------------------
    def apply_settings(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        if self._shutting_down:
            return
        settings: Settings = self._settings_provider()
        limit = max(1, min(6, settings.concurrency))
        for item in self.model.items():
            if len(self._active) >= limit:
                break
            if item.status != DownloadStatus.QUEUED or item.item_id in self._active:
                continue
            self._start(item)

    def _start(self, item: QueueItem) -> None:
        worker_item = replace(item)
        thread = QThread(self)
        worker = DownloadWorker(
            worker_item,
            self._settings_provider,
            self._paths,
            self._ffmpeg_provider,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_started)
        worker.progress.connect(self._on_progress)
        worker.phase_changed.connect(self._on_phase)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        item.status = DownloadStatus.ANALYZING
        item.started_at = time.time()
        item.attempts += 1
        item.phase = "動画情報を確認しています"
        item.error_code = ""
        item.error_title = ""
        item.error_message = ""
        item.error_remedy = ""
        item.note = ""
        self.model.update_item(item.item_id)
        self.model.refresh_stats()
        self._active[item.item_id] = (thread, worker)
        self._emit_active_count()
        self._schedule_save()
        thread.start()

    def _on_started(self, item_id: str) -> None:
        item = self.model.find(item_id)
        if not item or self._shutting_down:
            return
        if item.status in (
            DownloadStatus.ANALYZING,
            DownloadStatus.PAUSED,
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
            DownloadStatus.CANCELLING,
        ):
            return
        item.status = DownloadStatus.ANALYZING
        item.phase = "動画情報を確認しています"
        self.model.update_item(item_id)
        self.model.refresh_stats()

    def _on_progress(self, item_id: str, snapshot: object) -> None:
        if not isinstance(snapshot, ProgressSnapshot):
            return
        item = self.model.find(item_id)
        if not item or self._shutting_down:
            return
        if item.status in (
            DownloadStatus.PAUSED,
            DownloadStatus.CANCELLING,
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
        ):
            return
        previous_status = item.status
        if snapshot.phase.startswith("後処理"):
            item.status = DownloadStatus.PROCESSING
        elif item.status not in (DownloadStatus.PROCESSING,):
            item.status = DownloadStatus.DOWNLOADING
        item.percent = snapshot.percent
        if snapshot.downloaded_bytes is not None:
            item.downloaded_bytes = snapshot.downloaded_bytes
        if snapshot.total_bytes is not None:
            item.total_bytes = snapshot.total_bytes
        item.speed = snapshot.speed
        item.eta = snapshot.eta
        if snapshot.phase:
            item.phase = snapshot.phase
        if item.status == DownloadStatus.PROCESSING:
            item.speed = None
            item.eta = None
        self.model.update_item(item_id)
        # Progress updates several times per second.  Status counts only
        # change on transitions, so avoid notifying every badge/list for each
        # percentage tick.
        if item.status != previous_status:
            self.model.refresh_stats()

    def _on_phase(self, item_id: str, phase: str) -> None:
        item = self.model.find(item_id)
        if not item or self._shutting_down:
            return
        if item.status in (
            DownloadStatus.PAUSED,
            DownloadStatus.CANCELLING,
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
        ):
            return
        previous_status = item.status
        item.phase = phase
        if "情報" in phase:
            item.status = DownloadStatus.ANALYZING
        else:
            item.status = DownloadStatus.PROCESSING
            item.speed = None
            item.eta = None
        self.model.update_item(item_id)
        if item.status != previous_status:
            self.model.refresh_stats()

    def _on_finished(self, item_id: str, result: object) -> None:
        if not isinstance(result, DownloadResult):
            return
        item = self.model.find(item_id)
        removed = item_id in self._removed_ids
        if not item:
            removed = True
        if item is not None and not removed:
            if result.ok:
                item.status = DownloadStatus.COMPLETED
                item.output_path = result.output_path
                item.percent = 100.0
                item.phase = "完了"
                item.speed = None
                item.eta = None
                item.finished_at = time.time()
                if result.filesize is not None:
                    item.total_bytes = result.filesize
                    item.downloaded_bytes = result.filesize
                item.note = result.note
                self._record_history(item, result)
                if result.skipped_existing:
                    self.notification.emit(
                        "既存ファイルを使用しました", item.title, "info"
                    )
                else:
                    self.notification.emit(
                        "ダウンロードが完了しました",
                        f"{item.title}（{human_size(result.filesize)}）",
                        "success",
                    )
            elif result.paused:
                item.status = DownloadStatus.PAUSED
                item.phase = "一時停止中"
                item.speed = None
                item.eta = None
                item.note = result.note or "再開すると続きからダウンロードします。"
            elif result.cancelled:
                item.status = DownloadStatus.CANCELLED
                item.phase = "キャンセル済み"
                item.speed = None
                item.eta = None
                item.note = result.note
                item.finished_at = time.time()
            else:
                diagnosis = result.diagnosis
                item.status = DownloadStatus.FAILED
                item.phase = "失敗"
                item.speed = None
                item.eta = None
                item.finished_at = time.time()
                if diagnosis:
                    item.error_code = diagnosis.code
                    item.error_title = diagnosis.title
                    item.error_message = diagnosis.summary
                    item.error_remedy = diagnosis.remedy
                    self.notification.emit("ダウンロードに失敗しました", diagnosis.title, "error")
                else:
                    item.error_title = "ダウンロードに失敗しました"
                    item.error_message = str(result.error or "不明なエラー")
                    self.notification.emit("ダウンロードに失敗しました", item.error_title, "error")
            self.model.update_item(item_id)
            self.model.refresh_stats()
        self._schedule_save()

    def _record_history(self, item: QueueItem, result: DownloadResult) -> None:
        try:
            settings: Settings = self._settings_provider()
            self._history.limit = settings.history_limit
            self._history.add(
                title=item.title,
                url=item.url,
                filepath=result.output_path,
                save_dir=item.save_dir,
                status="completed",
                filesize=result.filesize,
                duration=item.duration,
                extractor=item.extractor,
                thumbnail=item.thumbnail,
                created_at=item.added_at,
                completed_at=time.time(),
            )
        except Exception as exc:  # history must not break downloads
            logger.error("履歴の記録に失敗しました: %s", exc)

    @Slot()
    def _on_thread_finished(self) -> None:
        thread = self.sender()
        finished_id = ""
        for item_id, (active_thread, _worker) in list(self._active.items()):
            if active_thread is thread:
                finished_id = item_id
                break
        if finished_id:
            self._active.pop(finished_id, None)
            self._removed_ids.discard(finished_id)
        self._emit_active_count()
        self._schedule_save()
        self._dispatch()

    # ---- user actions -------------------------------------------------
    def pause(self, item_id: str) -> None:
        item = self.model.find(item_id)
        if not item:
            return
        if item.status in (DownloadStatus.QUEUED,):
            item.status = DownloadStatus.PAUSED
            item.note = "再開するとダウンロードを開始します。"
            self.model.update_item(item_id)
            self.model.refresh_stats()
            self._schedule_save()
            return
        if item.status == DownloadStatus.DOWNLOADING:
            worker = self._active.get(item_id, (None, None))[1]
            if worker:
                worker.request_pause()
                item.phase = "一時停止しています…"
                item.note = "現在の接続を終了して一時停止します。再開すると続きから取得します。"
                self.model.update_item(item_id)
            return
        if item.status == DownloadStatus.ANALYZING:
            worker = self._active.get(item_id, (None, None))[1]
            if worker:
                worker.request_pause()
                item.note = "情報取得後に一時停止します。"
                self.model.update_item(item_id)
            return
        if item.status == DownloadStatus.PROCESSING:
            self.notification.emit(
                "処理中は一時停止できません",
                "映像と音声の結合が終わるまで待つか、キャンセルしてください。",
                "info",
            )
            return
        if item.status == DownloadStatus.PAUSED:
            self.resume(item_id)
            return
        if item.status.is_final:
            self.notification.emit("この項目は終了しています", item.title, "info")

    def resume(self, item_id: str) -> None:
        item = self.model.find(item_id)
        if item is None:
            return
        if item.status.is_active or item.status == DownloadStatus.QUEUED:
            return
        if item.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            item.reset_for_retry()
        else:
            item.status = DownloadStatus.QUEUED
            item.error_code = ""
            item.error_title = ""
            item.error_message = ""
            item.error_remedy = ""
            item.note = ""
            item.finished_at = None
        self.model.update_item(item_id)
        self.model.refresh_stats()
        self._schedule_save()
        self._dispatch()

    def cancel(self, item_id: str) -> None:
        item = self.model.find(item_id)
        if item is None:
            return
        if item.status == DownloadStatus.QUEUED:
            item.status = DownloadStatus.CANCELLED
            item.phase = "キャンセル済み"
            item.finished_at = time.time()
            self.model.update_item(item_id)
            self.model.refresh_stats()
            self._schedule_save()
            return
        if item.status == DownloadStatus.PAUSED:
            item.status = DownloadStatus.CANCELLED
            item.phase = "キャンセル済み"
            item.finished_at = time.time()
            self.model.update_item(item_id)
            self.model.refresh_stats()
            self._schedule_save()
            return
        if item.status.is_active:
            worker = self._active.get(item_id, (None, None))[1]
            if worker:
                worker.request_cancel()
                item.status = DownloadStatus.CANCELLING
                item.phase = "キャンセルしています…"
                self.model.update_item(item_id)
                self.model.refresh_stats()
            return

    def remove(self, item_id: str) -> None:
        item = self.model.find(item_id)
        if item is None:
            return
        if item.status.is_active:
            worker = self._active.get(item_id, (None, None))[1]
            if worker:
                worker.request_cancel()
            self._removed_ids.add(item_id)
        self.model.remove_item(item_id)
        self._schedule_save()
        self._dispatch()

    def remove_rows(self, rows: Iterable[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            item = self.model.item_at(row)
            if item:
                self.remove(item.item_id)

    def retry(self, item_id: str) -> None:
        self.resume(item_id)

    def pause_all(self) -> None:
        for item in self.model.items():
            if item.status in (
                DownloadStatus.QUEUED,
                DownloadStatus.ANALYZING,
                DownloadStatus.DOWNLOADING,
            ):
                self.pause(item.item_id)

    def resume_all(self) -> None:
        for item in self.model.items():
            if item.status in (DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                self.resume(item.item_id)

    def cancel_all(self) -> None:
        for item in self.model.items():
            if not item.status.is_final:
                self.cancel(item.item_id)

    def clear_finished(self, include_failed: bool = False) -> int:
        victims = [
            item.item_id
            for item in self.model.items()
            if item.status == DownloadStatus.COMPLETED
            or item.status == DownloadStatus.CANCELLED
            or (include_failed and item.status == DownloadStatus.FAILED)
        ]
        for item_id in victims:
            self.remove(item_id)
        return len(victims)

    def open_folder(self, item_id: str) -> str:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        item = self.model.find(item_id)
        if not item:
            return ""
        path = Path(item.output_path) if item.output_path else Path(item.save_dir)
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
            return str(path.parent)
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return str(path)
        parent = Path(item.save_dir)
        if parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent)))
            return str(parent)
        return ""

    # ---- shutdown -----------------------------------------------------
    def shutdown(self, wait_ms_per_task: int = 5000) -> None:
        self._shutting_down = True
        self._save_timer.stop()
        self.save_state()
        active = list(self._active.items())
        # A close request must not turn downloads that were running into
        # cancelled items: cancelled items are final and would be omitted from
        # the final queue snapshot.  Remember explicit cancellations so they
        # are not resurrected as paused entries.
        cancel_requested = {
            item_id
            for item_id, _active in active
            if (item := self.model.find(item_id)) is not None
            and item.status in (DownloadStatus.CANCELLING, DownloadStatus.CANCELLED)
        }
        for _item_id, (_thread, worker) in active:
            worker.request_cancel()
        deadline = time.monotonic() + max(2.0, wait_ms_per_task / 1000.0 * max(1, len(active)))
        while self._active and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            if self._active:
                time.sleep(0.03)
        for item_id, (thread, _worker) in list(self._active.items()):
            if thread.isRunning():
                logger.warning("スレッドの終了を待機できませんでした: %s", item_id)
                thread.quit()
                if not thread.wait(1500):
                    thread.terminate()
                    thread.wait(500)
        self._active.clear()
        for item_id, _active in active:
            item = self.model.find(item_id)
            if item is None:
                continue
            if item_id in cancel_requested:
                if item.status == DownloadStatus.CANCELLING:
                    item.status = DownloadStatus.CANCELLED
                    item.phase = "キャンセル済み"
                    item.finished_at = time.time()
                    self.model.update_item(item_id)
                continue
            if item.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED):
                continue
            # The worker reports a close request as ``cancelled``.  Persist it
            # as paused instead so it is restored and can continue next time.
            item.status = DownloadStatus.PAUSED
            item.phase = "前回の終了時に中断されました"
            item.note = "次回起動時に再開できます。"
            item.speed = None
            item.eta = None
            item.finished_at = None
            self.model.update_item(item_id)
        self.model.refresh_stats()
        self.save_state()

    def _on_stats_changed(self) -> None:
        self._emit_active_count()

    def _emit_active_count(self) -> None:
        count = len(self._active)
        if count != self._last_active_count:
            self._last_active_count = count
            self.active_count_changed.emit(count)
