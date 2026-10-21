from __future__ import annotations

import json

from PySide6.QtCore import Qt

from vela.core.models import DownloadStatus, ProgressSnapshot, QueueItem
from vela.core.queue import QueueFilterProxy, QueueManager, QueueModel


def _item(title: str, status: DownloadStatus = DownloadStatus.QUEUED, **kwargs) -> QueueItem:
    return QueueItem(
        url=f"https://example.com/{title}",
        title=title,
        save_dir="C:/Videos",
        format_selector="best",
        format_label="最高画質",
        status=status,
        **kwargs,
    )


def test_model_add_remove_and_stats(qapp) -> None:
    model = QueueModel()
    active = _item("active", DownloadStatus.DOWNLOADING)
    queued = _item("queued", DownloadStatus.QUEUED)
    done = _item("done", DownloadStatus.COMPLETED)
    model.add_items([active, queued, done])
    assert model.rowCount() == 3
    assert model.find(active.item_id) is active
    assert model.row_for_id(done.item_id) == 2
    stats = model.stats()
    assert stats["total"] == 3
    assert stats["active"] == 1
    assert stats["queued"] == 1
    assert stats["completed"] == 1
    assert model.remove_item(queued.item_id)
    assert model.rowCount() == 2
    assert model.find(queued.item_id) is None
    model.clear()
    assert model.rowCount() == 0


def test_model_roles(qapp) -> None:
    model = QueueModel()
    item = _item("role-test", DownloadStatus.DOWNLOADING, percent=42.5)
    model.add_item(item)
    index = model.index(0, 0)
    assert model.data(index, Qt.DisplayRole) == "role-test"
    assert model.data(index, QueueModel.IdRole) == item.item_id
    assert model.data(index, QueueModel.StatusRole) == "downloading"
    assert model.data(index, QueueModel.PercentRole) == 42.5
    assert model.data(index, QueueModel.ItemRole) is item


def test_filter_proxy_modes_and_search(qapp) -> None:
    model = QueueModel()
    model.add_items(
        [
            _item("Cooking Show", DownloadStatus.COMPLETED),
            _item("Cooking Live", DownloadStatus.DOWNLOADING, uploader="ライブ配信"),
            _item("Music Mix", DownloadStatus.FAILED),
            _item("Paused Clip", DownloadStatus.PAUSED),
        ]
    )
    proxy = QueueFilterProxy()
    proxy.setSourceModel(model)

    def titles() -> list[str]:
        return [proxy.data(proxy.index(row, 0), Qt.DisplayRole) for row in range(proxy.rowCount())]

    assert len(titles()) == 4
    proxy.set_mode("active")
    assert titles() == ["Cooking Live"]
    proxy.set_mode("completed")
    assert titles() == ["Cooking Show"]
    proxy.set_mode("failed")
    assert titles() == ["Music Mix"]
    proxy.set_mode("paused")
    assert titles() == ["Paused Clip"]
    proxy.set_mode("all")
    proxy.set_search("cooking")
    assert titles() == ["Cooking Show", "Cooking Live"]
    proxy.set_search("ライブ")
    assert titles() == ["Cooking Live"]


def test_queue_persistence_roundtrip(qapp, paths, tmp_path) -> None:
    from vela.core.history import HistoryStore

    history = HistoryStore(tmp_path / "history.sqlite3")
    try:
        model = QueueModel()
        manager = QueueManager(model, lambda: None, paths, lambda: None, history)
        paused = _item("paused", DownloadStatus.PAUSED)
        queued = _item("queued", DownloadStatus.QUEUED)
        model.add_items([paused, queued])
        manager.save_state()

        payload = json.loads(paths.queue_file.read_text(encoding="utf-8"))
        assert len(payload["items"]) == 2
        assert all(item["status"] == "paused" for item in payload["items"])

        restored_model = QueueModel()
        restored_manager = QueueManager(
            restored_model, lambda: None, paths, lambda: None, history
        )
        assert restored_manager.load_state(True) == 2
        restored = restored_model.items()
        assert {item.title for item in restored} == {"paused", "queued"}
        assert all(item.status == DownloadStatus.PAUSED for item in restored)
        assert restored[0].url.startswith("https://example.com/")

        assert restored_manager.load_state(False) == 0
    finally:
        history.close()


def test_corrupt_queue_file_is_ignored(qapp, paths, tmp_path) -> None:
    from vela.core.history import HistoryStore

    paths.queue_file.write_text("{not json", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.sqlite3")
    try:
        model = QueueModel()
        manager = QueueManager(model, lambda: None, paths, lambda: None, history)
        assert manager.load_state(True) == 0
        assert manager.warnings
        assert model.rowCount() == 0
    finally:
        history.close()


def test_shutdown_keeps_active_items_for_the_next_session(qapp, paths, tmp_path) -> None:
    from vela.core.downloader import DownloadResult
    from vela.core.history import HistoryStore

    history = HistoryStore(tmp_path / "history.sqlite3")
    try:
        model = QueueModel()
        manager = QueueManager(model, lambda: None, paths, lambda: None, history)
        item = _item("active-at-close", DownloadStatus.DOWNLOADING)
        model.add_item(item)

        class _Thread:
            def isRunning(self) -> bool:  # noqa: N802 - Qt naming
                return False

        class _Worker:
            def request_cancel(self) -> None:
                manager._on_finished(  # noqa: SLF001 - reproduce the worker signal
                    item.item_id, DownloadResult(cancelled=True)
                )
                manager._active.pop(item.item_id, None)  # noqa: SLF001

        manager._active[item.item_id] = (_Thread(), _Worker())  # noqa: SLF001
        manager.shutdown(wait_ms_per_task=10)

        assert item.status == DownloadStatus.PAUSED
        payload = json.loads(paths.queue_file.read_text(encoding="utf-8"))
        assert [entry["item_id"] for entry in payload["items"]] == [item.item_id]
        assert payload["items"][0]["status"] == "paused"

        restored_model = QueueModel()
        restored_manager = QueueManager(
            restored_model, lambda: None, paths, lambda: None, history
        )
        assert restored_manager.load_state(True) == 1
        assert restored_model.items()[0].status == DownloadStatus.PAUSED
    finally:
        history.close()


def test_pause_all_includes_items_still_being_analyzed(qapp, paths, tmp_path) -> None:
    from vela.core.history import HistoryStore

    history = HistoryStore(tmp_path / "history.sqlite3")
    try:
        model = QueueModel()
        manager = QueueManager(model, lambda: None, paths, lambda: None, history)
        analyzing = _item("analyzing", DownloadStatus.ANALYZING)
        queued = _item("queued", DownloadStatus.QUEUED)
        model.add_items([analyzing, queued])

        class _Worker:
            pause_requested = False

            def request_pause(self) -> None:
                self.pause_requested = True

        worker = _Worker()
        manager._active[analyzing.item_id] = (object(), worker)  # noqa: SLF001
        manager.pause_all()

        assert worker.pause_requested
        assert queued.status == DownloadStatus.PAUSED
    finally:
        history.close()


def test_late_progress_does_not_reopen_paused_items(qapp, paths, tmp_path) -> None:
    from vela.core.history import HistoryStore

    history = HistoryStore(tmp_path / "history.sqlite3")
    try:
        model = QueueModel()
        manager = QueueManager(model, lambda: None, paths, lambda: None, history)
        item = _item("paused", DownloadStatus.PAUSED)
        model.add_item(item)

        manager._on_progress(  # noqa: SLF001
            item.item_id, ProgressSnapshot(percent=50, phase="ダウンロード中")
        )
        manager._on_phase(item.item_id, "動画情報を確認しています")  # noqa: SLF001

        assert item.status == DownloadStatus.PAUSED
        assert item.percent is None
        assert item.phase == ""
    finally:
        history.close()
