from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    filepath TEXT NOT NULL DEFAULT '',
    save_dir TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'completed',
    filesize INTEGER,
    duration REAL,
    extractor TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    completed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_completed ON downloads(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_title ON downloads(title);
"""


@dataclass
class HistoryEntry:
    id: int
    title: str
    url: str
    filepath: str
    save_dir: str
    status: str
    filesize: int | None
    duration: float | None
    extractor: str
    thumbnail: str
    created_at: float
    completed_at: float

    @property
    def file_exists(self) -> bool:
        try:
            return bool(self.filepath) and Path(self.filepath).is_file()
        except OSError:
            return False


class HistoryStore:
    def __init__(self, path: Path, *, limit: int = 1000) -> None:
        self.path = Path(path)
        self.limit = limit
        self.warnings: list[str] = []
        self._connection: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(self.path), timeout=8)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.executescript(_SCHEMA)
            connection.commit()
        except sqlite3.DatabaseError as exc:
            logger.warning("履歴データベースを初期化できませんでした: %s", exc)
            self._preserve_corrupt()
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
            self._remove_corrupt_files()
            connection = sqlite3.connect(str(self.path), timeout=8)
            connection.row_factory = sqlite3.Row
            connection.executescript(_SCHEMA)
            connection.commit()
            self.warnings.append("履歴データベースが破損していたため、新しく作成しました。")
        self._connection = connection
        return connection

    def _remove_corrupt_files(self) -> None:
        for candidate in (
            self.path,
            self.path.with_name(self.path.name + "-wal"),
            self.path.with_name(self.path.name + "-shm"),
        ):
            try:
                candidate.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("破損した履歴ファイルを削除できませんでした: %s", exc)

    def _preserve_corrupt(self) -> None:
        try:
            if self.path.exists():
                backup = self.path.with_name(
                    f"{self.path.stem}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}{self.path.suffix}"
                )
                shutil.copy2(self.path, backup)
        except OSError:
            pass

    def add(
        self,
        *,
        title: str,
        url: str,
        filepath: str,
        save_dir: str,
        status: str = "completed",
        filesize: int | None = None,
        duration: float | None = None,
        extractor: str = "",
        thumbnail: str = "",
        created_at: float | None = None,
        completed_at: float | None = None,
    ) -> int:
        now = time.time()
        connection = self._connect()
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO downloads
                    (title, url, filepath, save_dir, status, filesize, duration,
                     extractor, thumbnail, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    url,
                    filepath,
                    save_dir,
                    status,
                    filesize,
                    duration,
                    extractor,
                    thumbnail,
                    created_at if created_at is not None else now,
                    completed_at if completed_at is not None else now,
                ),
            )
        self.prune()
        return int(cursor.lastrowid or 0)

    def entries(self, search: str = "", limit: int = 500) -> list[HistoryEntry]:
        connection = self._connect()
        term = f"%{search.strip()}%"
        if search.strip():
            rows = connection.execute(
                """
                SELECT * FROM downloads
                WHERE title LIKE ? OR extractor LIKE ? OR url LIKE ?
                ORDER BY completed_at DESC LIMIT ?
                """,
                (term, term, term, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM downloads ORDER BY completed_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def count(self) -> int:
        connection = self._connect()
        row = connection.execute("SELECT COUNT(*) AS n FROM downloads").fetchone()
        return int(row["n"] if row else 0)

    def count_since(self, timestamp: float) -> int:
        """Return the number of completed downloads at or after *timestamp*."""
        connection = self._connect()
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM downloads WHERE completed_at >= ?",
            (timestamp,),
        ).fetchone()
        return int(row["n"] if row else 0)

    def delete(self, entry_ids: Iterable[int]) -> None:
        ids = [int(item) for item in entry_ids]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        connection = self._connect()
        with connection:
            connection.execute(f"DELETE FROM downloads WHERE id IN ({placeholders})", ids)

    def clear(self) -> None:
        connection = self._connect()
        with connection:
            connection.execute("DELETE FROM downloads")

    def prune(self) -> None:
        connection = self._connect()
        with connection:
            connection.execute(
                """
                DELETE FROM downloads WHERE id NOT IN (
                    SELECT id FROM downloads ORDER BY completed_at DESC LIMIT ?
                )
                """,
                (self.limit,),
            )

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> HistoryEntry:
        return HistoryEntry(
            id=int(row["id"]),
            title=str(row["title"]),
            url=str(row["url"]),
            filepath=str(row["filepath"]),
            save_dir=str(row["save_dir"]),
            status=str(row["status"]),
            filesize=row["filesize"],
            duration=row["duration"],
            extractor=str(row["extractor"]),
            thumbnail=str(row["thumbnail"]),
            created_at=float(row["created_at"]),
            completed_at=float(row["completed_at"]),
        )
