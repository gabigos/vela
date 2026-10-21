from __future__ import annotations

from vela.core.ytdlp_service import _parse_info


def test_parse_info_ignores_nan_counters() -> None:
    info = {
        "_type": "video",
        "title": "動画",
        "id": "abc",
        "view_count": float("nan"),
        "age_limit": float("nan"),
        "duration": 12.5,
    }

    result = _parse_info(info, "https://example.com/video")

    assert result.view_count is None
    assert result.age_limit == 0


def test_parse_info_ignores_infinite_metadata() -> None:
    info = {
        "_type": "video",
        "title": "動画",
        "id": "abc",
        "view_count": float("inf"),
        "age_limit": float("inf"),
        "duration": float("inf"),
    }

    result = _parse_info(info, "https://example.com/video")

    assert result.view_count is None
    assert result.age_limit == 0
    assert result.duration is None


def test_parse_info_recovers_playlist_count_without_valid_number() -> None:
    info = {
        "_type": "playlist",
        "title": "再生リスト",
        "playlist_count": float("nan"),
        "entries": [{"title": "a", "url": "https://example.com/a"}],
    }

    result = _parse_info(info, "https://example.com/list")

    assert result.playlist_count == len(result.entries) == 1


def test_parse_info_reads_numeric_counters() -> None:
    info = {
        "_type": "video",
        "title": "動画",
        "id": "abc",
        "view_count": 1234.9,
        "age_limit": 18,
    }

    result = _parse_info(info, "https://example.com/video")

    assert result.view_count == 1234
    assert result.age_limit == 18
