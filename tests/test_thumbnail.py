from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QByteArray
from PySide6.QtNetwork import QNetworkReply

from vela.ui.thumbnail import ThumbnailLoader


def test_thumbnail_loader_rejects_private_hosts(qapp, tmp_path: Path) -> None:
    loader = ThumbnailLoader(tmp_path / "thumbnails")

    assert loader.load("http://127.0.0.1/private.jpg") is None
    assert not loader._pending


def test_failed_thumbnail_is_not_requested_on_every_repaint(qapp, tmp_path: Path) -> None:
    loader = ThumbnailLoader(tmp_path / "thumbnails")
    url = "https://example.com/missing.jpg"
    reply = Mock()
    reply.error.return_value = QNetworkReply.NetworkError.ContentNotFoundError
    reply.attribute.return_value = None

    loader._pending.add(url)
    loader._buffers[url] = QByteArray()
    loader._finished(url, reply)

    assert url in loader._failed
    reply.deleteLater.assert_called_once()

    loader._manager = Mock()
    assert loader.load(url) is None
    loader._manager.get.assert_not_called()
