from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

from vela.core.downloader import DownloadWorker
from vela.core.ffmpeg_tools import FFmpegInfo
from vela.core.models import QueueItem
from vela.core.settings import Settings
from vela.core.ytdlp_service import SafeYoutubeDL


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass


@pytest.fixture()
def media_server(project_root: Path):
    media_dir = project_root / "tools" / "testmedia"
    sample = media_dir / "sample.mp4"
    if not sample.is_file():
        pytest.skip("tools/testmedia/sample.mp4 is not present")
    handler = functools.partial(_QuietHandler, directory=str(media_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/sample.mp4"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.integration()
def test_real_download_from_local_http(
    qapp, paths, project_root: Path, tmp_path: Path, media_server: str, monkeypatch
) -> None:
    # The downloader deliberately blocks private hosts. The test opts in only
    # for its own loopback server so the entire yt-dlp download path can run.
    monkeypatch.setattr(SafeYoutubeDL, "allow_private", True)

    save_dir = tmp_path / "downloads"
    save_dir.mkdir()
    settings = Settings(
        save_dir=str(save_dir),
        filename_template="%(title)s [%(id)s].%(ext)s",
        concurrency=1,
    )
    item = QueueItem(
        url=media_server,
        title="sample",
        save_dir=str(save_dir),
        format_selector="best",
        format_label="最高画質（自動）",
        extractor="Generic",
    )
    worker = DownloadWorker(
        item,
        lambda: settings,
        paths,
        lambda: FFmpegInfo(),
    )
    finished: list[object] = []
    worker.finished.connect(lambda _item_id, result: finished.append(result))

    worker.run()
    qapp.processEvents()

    assert len(finished) == 1
    result = finished[0]
    assert result.ok, result.error or result.note
    output = Path(result.output_path)
    assert output.is_file()
    expected = project_root / "tools" / "testmedia" / "sample.mp4"
    assert output.stat().st_size == expected.stat().st_size
    assert result.filesize == output.stat().st_size
    assert result.diagnosis is None
    assert not result.cancelled
    assert not result.paused


def test_downloader_refuses_private_hosts_without_opt_in(
    qapp, paths, tmp_path: Path, media_server: str
) -> None:
    settings = Settings(
        save_dir=str(tmp_path),
        filename_template="%(title)s.%(ext)s",
        concurrency=1,
    )
    item = QueueItem(
        url=media_server,
        title="blocked",
        save_dir=str(tmp_path),
        format_selector="best",
        format_label="最高画質（自動）",
    )
    worker = DownloadWorker(item, lambda: settings, paths, lambda: FFmpegInfo())
    finished: list[object] = []
    worker.finished.connect(lambda _item_id, result: finished.append(result))
    worker.run()
    qapp.processEvents()
    assert len(finished) == 1
    result = finished[0]
    assert not result.ok
    assert result.diagnosis is not None
    assert result.diagnosis.code == "INVALID_URL"
