from __future__ import annotations

import time
from pathlib import Path

from vela.core.history import HistoryStore


def _add(store: HistoryStore, title: str, *, completed: float, extractor: str = "YouTube") -> int:
    return store.add(
        title=title,
        url=f"https://example.com/{title}",
        filepath="",
        save_dir="C:/Videos",
        filesize=1024,
        duration=60,
        extractor=extractor,
        created_at=completed - 10,
        completed_at=completed,
    )


def test_add_and_list_entries(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        now = time.time()
        first = _add(store, "old", completed=now - 100)
        second = _add(store, "new", completed=now)
        entries = store.entries()
        assert [entry.id for entry in entries] == [second, first]
        assert entries[0].title == "new"
        assert entries[1].filesize == 1024
        assert store.count() == 2
    finally:
        store.close()


def test_search_matches_title_extractor_and_url(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        _add(store, "Cooking Show", completed=time.time(), extractor="YouTube")
        _add(store, "Live Set", completed=time.time() - 10, extractor="SoundCloud")
        assert [e.title for e in store.entries("cooking")] == ["Cooking Show"]
        assert [e.title for e in store.entries("soundcloud")] == ["Live Set"]
        assert [e.title for e in store.entries("example.com")] == ["Cooking Show", "Live Set"]
        assert store.entries("missing") == []
    finally:
        store.close()


def test_delete_and_clear(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        first = _add(store, "one", completed=time.time())
        second = _add(store, "two", completed=time.time())
        store.delete([first, second])
        assert store.count() == 0
        _add(store, "three", completed=time.time())
        store.clear()
        assert store.count() == 0
    finally:
        store.close()


def test_count_since_counts_all_recent_entries(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        now = time.time()
        _add(store, "old", completed=now - 200)
        _add(store, "recent-a", completed=now - 10)
        _add(store, "recent-b", completed=now)
        assert store.count_since(now - 100) == 2
        assert store.count_since(now - 300) == 3
        assert store.count_since(now + 10) == 0
    finally:
        store.close()


def test_prune_keeps_newest_entries(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3", limit=3)
    try:
        now = time.time()
        for index in range(6):
            _add(store, f"item-{index}", completed=now - index)
        titles = [entry.title for entry in store.entries()]
        assert titles == ["item-0", "item-1", "item-2"]
    finally:
        store.close()


def test_corrupt_database_is_backed_up_and_recreated(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    path.write_bytes(b"this is definitely not a sqlite database" * 20)
    store = HistoryStore(path)
    try:
        assert store.count() == 0
        assert store.warnings
        backups = list(tmp_path.glob("history.corrupt-*.sqlite3"))
        assert backups and backups[0].exists()
        _add(store, "after-recovery", completed=time.time())
        assert store.count() == 1
    finally:
        store.close()
