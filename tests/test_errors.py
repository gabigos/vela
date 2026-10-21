from __future__ import annotations

import pytest

from vela.core.downloader import DownloadCancelled, DownloadPaused
from vela.core.errors import classify_error


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("ERROR: No space left on device", "DISK_FULL"),
        ("ffmpeg not found. Please install ffmpeg", "FFMPEG_MISSING"),
        ("This video is DRM protected", "DRM_UNSUPPORTED"),
        ("This video is not available in your country", "GEO_BLOCKED"),
        (
            "ERROR: [youtube] abc: The uploader has not made this video available in your country",
            "GEO_BLOCKED",
        ),
        ("This video is not available due to geoblocking", "GEO_BLOCKED"),
        ("ERROR: [youtube] abc: No video formats found!", "EXTRACTOR_OUTDATED"),
        ("Private video. Sign in if you've been granted access", "PRIVATE_VIDEO"),
        ("ERROR: HTTP Error 429: Too Many Requests", "RATE_LIMITED"),
        ("Unable to download webpage: <urlopen error timed out>", "TIMEOUT"),
        ("The read operation timed out", "TIMEOUT"),
        ("Requested format is not available", "FORMAT_UNAVAILABLE"),
        ("Permission denied: 'C:/Videos/a.mp4'", "PERMISSION"),
        ("Unsupported URL: https://example.com/nothing", "UNSUPPORTED_URL"),
        ("This is not a valid URL", "INVALID_URL"),
    ],
)
def test_error_classification(message: str, code: str) -> None:
    diagnosis = classify_error(RuntimeError(message))
    assert diagnosis.code == code
    assert diagnosis.title
    assert diagnosis.summary
    assert diagnosis.remedy


def test_unknown_errors_are_safe() -> None:
    diagnosis = classify_error("something odd happened")
    assert diagnosis.code == "UNKNOWN"
    assert diagnosis.retryable is True
    assert "something odd happened" in diagnosis.technical


def test_cancelled_and_paused_are_not_errors() -> None:
    assert classify_error(DownloadCancelled("x")).code == "CANCELLED"
    assert classify_error(DownloadPaused("x")).code == "CANCELLED"
    assert classify_error(DownloadCancelled("x")).retryable is True


def test_technical_text_is_length_limited() -> None:
    diagnosis = classify_error("x" * 9000)
    assert len(diagnosis.technical) <= 4000
