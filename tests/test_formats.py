from __future__ import annotations

from vela.core.formats import (
    build_format_options,
    codec_label,
    default_option,
    describe_option,
    find_option,
    resolution_label,
)
from vela.core.models import FormatInfo, VideoInfo


def _video_info() -> VideoInfo:
    return VideoInfo(
        url="https://example.com/watch",
        title="Example",
        formats=[
            FormatInfo(
                format_id="137",
                ext="mp4",
                height=1080,
                fps=30,
                vcodec="avc1.640028",
                acodec="none",
                filesize=100_000_000,
            ),
            FormatInfo(
                format_id="248",
                ext="webm",
                height=1080,
                fps=30,
                vcodec="vp9",
                acodec="none",
                filesize=80_000_000,
            ),
            FormatInfo(
                format_id="18",
                ext="mp4",
                height=360,
                fps=30,
                vcodec="avc1.42001E",
                acodec="mp4a.40.2",
                filesize=20_000_000,
            ),
            FormatInfo(
                format_id="140",
                ext="m4a",
                vcodec="none",
                acodec="mp4a.40.2",
                filesize=3_000_000,
            ),
            FormatInfo(
                format_id="sb0",
                ext="mhtml",
                vcodec="none",
                acodec="none",
            ),
        ],
    )


def test_codec_and_resolution_labels() -> None:
    assert codec_label("avc1.640028") == "H.264"
    assert codec_label("vp09.00.10.08") == "VP9"
    assert codec_label("none") == "—"
    assert codec_label(None) == "—"
    assert resolution_label(1080, 60) == "1080p60"
    assert resolution_label(720, 30) == "720p"
    assert resolution_label(None) == "解像度不明"


def test_preset_options_are_always_present() -> None:
    options = build_format_options(_video_info())
    keys = [option.key for option in options]
    assert keys[:5] == ["best", "mp4", "audio_original", "audio_mp3", "audio_m4a"]
    assert find_option(options, "mp3") is None
    assert find_option(options, "audio_mp3").audio_format == "mp3"


def test_merge_requirement_is_detected() -> None:
    options = build_format_options(_video_info())
    best = find_option(options, "best")
    assert best is not None
    assert best.requires_ffmpeg is True
    assert find_option(options, "audio_original").requires_ffmpeg is False


def test_video_formats_are_deduplicated_and_sorted() -> None:
    options = build_format_options(_video_info())
    video_options = [option for option in options if option.kind == "video"]
    heights = [option.height for option in video_options]
    assert heights == sorted(heights, reverse=True)
    assert sum(1 for option in video_options if option.height == 1080) == 2
    format_ids = {option.key for option in video_options}
    assert "fmt:137" in format_ids
    assert "fmt:18" in format_ids
    assert all("mhtml" not in option.key for option in video_options)


def test_formats_with_audio_do_not_require_merge() -> None:
    options = build_format_options(_video_info())
    option_18 = find_option(options, "fmt:18")
    assert option_18 is not None
    assert option_18.requires_ffmpeg is False
    assert option_18.selector == "18"


def test_describe_option_and_default() -> None:
    options = build_format_options(_video_info())
    best = default_option(options)
    assert best.key == "best"
    description = describe_option(find_option(options, "fmt:137"))
    assert "1080p" in description
    assert "H.264" in description
    assert default_option([]).key == "best"


def test_empty_video_info_still_returns_presets() -> None:
    options = build_format_options(VideoInfo(url="https://example.com", title="x"))
    assert options
    assert options[0].key == "best"
    assert all(option.kind != "video" for option in options)


def test_muxed_and_video_only_are_not_deduplicated() -> None:
    # A muxed 360p stream and a video-only 360p stream must both stay
    # selectable: without FFmpeg only the muxed one can be downloaded.
    info = VideoInfo(
        url="https://example.com/watch",
        title="Example",
        formats=[
            FormatInfo(
                format_id="18",
                ext="mp4",
                height=360,
                fps=30,
                vcodec="avc1.42001E",
                acodec="mp4a.40.2",
                tbr=389,
            ),
            FormatInfo(
                format_id="134",
                ext="mp4",
                height=360,
                fps=30,
                vcodec="avc1.4d401e",
                acodec="none",
                tbr=596,
            ),
        ],
    )

    options = build_format_options(info)

    assert find_option(options, "fmt:18") is not None
    assert find_option(options, "fmt:134") is not None
    assert find_option(options, "fmt:18").requires_ffmpeg is False
