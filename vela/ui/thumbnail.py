from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.security import validate_url
from .icons import icon
from .theme import current_palette

logger = logging.getLogger(__name__)

_MAX_BYTES = 6 * 1024 * 1024
_MAX_CACHE_BYTES = 120 * 1024 * 1024


class ThumbnailLoader(QObject):
    loaded = Signal(str, QPixmap)
    failed = Signal(str)

    def __init__(self, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._manager = QNetworkAccessManager(self)
        self._memory: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._buffers: dict[str, QByteArray] = {}
        self._cleanup_cache()

    def load(self, url: str) -> QPixmap | None:
        if not url:
            return None
        if url in self._memory:
            return self._memory[url]
        if url in self._failed:
            return None
        validation = validate_url(url)
        if not validation:
            return None
        cached = self._cache_path(url)
        if cached and cached.is_file():
            pixmap = QPixmap(str(cached))
            if not pixmap.isNull():
                self._memory[url] = pixmap
                return pixmap
        if url in self._pending:
            return None
        request = QNetworkRequest(QUrl(validation.url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setTransferTimeout(15000)
        request.setRawHeader(b"User-Agent", b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Vela/1.0")
        reply = self._manager.get(request)
        self._pending.add(url)
        self._buffers[url] = QByteArray()
        reply.readyRead.connect(lambda u=url, r=reply: self._read(u, r))
        reply.finished.connect(lambda u=url, r=reply: self._finished(u, r))
        return None

    def _read(self, url: str, reply: QNetworkReply) -> None:
        buffer = self._buffers.get(url)
        if buffer is None:
            return
        buffer.append(reply.readAll())
        if buffer.size() > _MAX_BYTES:
            self._buffers.pop(url, None)
            reply.abort()

    def _finished(self, url: str, reply: QNetworkReply) -> None:
        self._pending.discard(url)
        data = self._buffers.pop(url, QByteArray())
        error = reply.error()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            if error == QNetworkReply.NetworkError.OperationCanceledError:
                self._mark_failed(url)
                return
            if error != QNetworkReply.NetworkError.NoError or (status and int(status) >= 400):
                logger.debug("サムネイルを取得できませんでした (%s): %s", status, url)
                self._mark_failed(url)
                return
            data.append(reply.readAll())
            if data.size() > _MAX_BYTES:
                self._mark_failed(url)
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(data) or pixmap.isNull():
                self._mark_failed(url)
                return
            if pixmap.width() > 960:
                pixmap = pixmap.scaledToWidth(960, Qt.SmoothTransformation)
            self._failed.discard(url)
            self._memory[url] = pixmap
            self._write_cache(url, data)
            self.loaded.emit(url, pixmap)
        finally:
            reply.deleteLater()

    def _mark_failed(self, url: str) -> None:
        # Delegates repaint frequently.  Remember failures for this session so
        # a missing thumbnail does not trigger a network request on every paint.
        self._failed.add(url)
        self.failed.emit(url)

    def _cache_path(self, url: str) -> Path | None:
        try:
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        except Exception:
            return None
        return self._cache_dir / f"{digest}.img"

    def _write_cache(self, url: str, data: QByteArray) -> None:
        path = self._cache_path(url)
        if path is None:
            return
        try:
            path.write_bytes(bytes(data))
        except OSError as exc:
            logger.debug("サムネイルキャッシュを書き込めませんでした: %s", exc)

    def _cleanup_cache(self) -> None:
        try:
            files = sorted(
                (path for path in self._cache_dir.glob("*.img") if path.is_file()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        total = 0
        for index, path in enumerate(files):
            try:
                total += path.stat().st_size
                if index > 300 or total > _MAX_CACHE_BYTES:
                    path.unlink(missing_ok=True)
            except OSError:
                continue


class ThumbnailWidget(QWidget):
    """Rounded 16:9 thumbnail with a tasteful gradient placeholder."""

    def __init__(self, parent: QWidget | None = None, *, radius: int = 14) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._radius = radius
        self._url = ""
        self.setMinimumSize(260, 146)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def set_url(self, url: str) -> None:
        self._url = url
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            source = QRectF(
                (scaled.width() - self.width()) / 2,
                (scaled.height() - self.height()) / 2,
                self.width(),
                self.height(),
            )
            painter.drawPixmap(rect, scaled, source)
        else:
            gradient = QLinearGradient(0, 0, rect.width(), rect.height())
            gradient.setColorAt(0, QColor(palette.surface_alt))
            gradient.setColorAt(1, QColor(palette.accent_soft))
            painter.fillPath(path, gradient)
            glyph = icon("film", palette.text_muted, 38).pixmap(38, 38)
            painter.drawPixmap(
                int((self.width() - 38) / 2), int((self.height() - 38) / 2), glyph
            )
            painter.setPen(QPen(QColor(palette.border), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        painter.end()
