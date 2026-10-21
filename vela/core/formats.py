from __future__ import annotations

from .models import FormatInfo, FormatOption, VideoInfo
from .utils import human_size

_CODEC_NAMES = {
    "avc1": "H.264",
    "avc3": "H.264",
    "h264": "H.264",
    "hev1": "H.265",
    "hvc1": "H.265",
    "hevc": "H.265",
    "h265": "H.265",
    "vp8": "VP8",
    "vp9": "VP9",
    "vp09": "VP9",
    "av01": "AV1",
    "theora": "Theora",
    "mp4v": "MPEG-4",
    "mp4a": "AAC",
    "aac": "AAC",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "mp3": "MP3",
    "ac-3": "AC-3",
    "ec-3": "E-AC-3",
    "flac": "FLAC",
    "alac": "ALAC",
}


def codec_label(codec: str | None) -> str:
    if not codec or codec == "none":
        return "—"
    base = codec.split(".")[0].lower()
    return _CODEC_NAMES.get(base, base.upper())


def resolution_label(height: int | None, fps: float | None = None) -> str:
    if not height:
        return "解像度不明"
    base = f"{height}p"
    if fps and fps >= 48:
        return f"{base}{int(round(fps))}"
    return base


def _merge_required(formats: list[FormatInfo]) -> bool:
    return any(item.has_video and not item.has_audio for item in formats)


def build_format_options(info: VideoInfo) -> list[FormatOption]:
    options: list[FormatOption] = []
    merge = _merge_required(info.formats)
    options.append(
        FormatOption(
            key="best",
            label="最高画質（自動）",
            selector="bestvideo*+bestaudio/best",
            kind="preset",
            note="利用可能な中で最も高画質な映像と音声を選びます",
            requires_ffmpeg=merge,
        )
    )
    options.append(
        FormatOption(
            key="mp4",
            label="MP4（互換性重視）",
            selector="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            kind="preset",
            ext="mp4",
            note="多くのプレイヤーで再生できる形式を優先します",
            requires_ffmpeg=merge,
        )
    )
    options.append(
        FormatOption(
            key="audio_original",
            label="音声のみ（元の形式）",
            selector="bestaudio/best",
            kind="audio",
            audio_format="original",
            audio_only=True,
            note="再エンコードせず、配信されている音声をそのまま保存します",
        )
    )
    options.append(
        FormatOption(
            key="audio_mp3",
            label="音声のみ（MP3）",
            selector="bestaudio/best",
            kind="audio",
            ext="mp3",
            audio_format="mp3",
            audio_only=True,
            requires_ffmpeg=True,
            note="MP3 192 kbps に変換します",
        )
    )
    options.append(
        FormatOption(
            key="audio_m4a",
            label="音声のみ（M4A）",
            selector="bestaudio/best",
            kind="audio",
            ext="m4a",
            audio_format="m4a",
            audio_only=True,
            requires_ffmpeg=True,
            note="M4A（AAC）に変換します",
        )
    )

    seen: dict[tuple, FormatInfo] = {}
    for fmt in info.formats:
        if not fmt.has_video or not fmt.format_id:
            continue
        if fmt.ext.lower() == "mhtml" or fmt.protocol.startswith("mhtml"):
            continue
        if fmt.format_id.startswith("sb") and not fmt.height:
            continue
        key = (
            fmt.height or 0,
            int(round(fmt.fps or 0)),
            codec_label(fmt.vcodec),
            fmt.ext.lower(),
            "hdr" if "hdr" in fmt.dynamic_range.lower() else "sdr",
            bool(fmt.has_audio),
        )
        existing = seen.get(key)
        if existing is None or (fmt.tbr or 0) > (existing.tbr or 0):
            seen[key] = fmt

    ordered = sorted(
        seen.values(),
        key=lambda item: (
            item.height or 0,
            item.fps or 0,
            item.tbr or 0,
            item.filesize or 0,
        ),
        reverse=True,
    )
    for fmt in ordered[:80]:
        label = resolution_label(fmt.height, fmt.fps)
        audio = fmt.has_audio
        note_parts = [fmt.ext.upper() or "?", codec_label(fmt.vcodec)]
        if fmt.format_note:
            note_parts.append(fmt.format_note)
        if "hdr" in fmt.dynamic_range.lower():
            note_parts.append("HDR")
        if not audio:
            note_parts.append("映像のみ・音声を結合")
        if fmt.filesize:
            note_parts.append(human_size(fmt.filesize, approximate=True))
        selector = fmt.format_id if audio else f"{fmt.format_id}+bestaudio/{fmt.format_id}"
        options.append(
            FormatOption(
                key=f"fmt:{fmt.format_id}",
                label=label,
                selector=selector,
                kind="video",
                ext=fmt.ext,
                height=fmt.height,
                fps=fmt.fps,
                vcodec=codec_label(fmt.vcodec),
                acodec=codec_label(fmt.acodec) if audio else "",
                filesize=fmt.filesize,
                note=" · ".join(note_parts),
                requires_ffmpeg=not audio,
            )
        )
    return options


def default_option(options: list[FormatOption]) -> FormatOption:
    return options[0] if options else FormatOption(
        key="best", label="最高画質（自動）", selector="best", kind="preset"
    )


def describe_option(option: FormatOption) -> str:
    if option.kind == "audio":
        return option.label
    parts = [option.label]
    if option.ext:
        parts.append(option.ext.upper())
    if option.vcodec:
        parts.append(option.vcodec)
    if option.acodec:
        parts.append(option.acodec)
    if option.filesize:
        parts.append(option.size_text)
    return " · ".join(parts)


def find_option(options: list[FormatOption], key: str) -> FormatOption | None:
    for option in options:
        if option.key == key:
            return option
    return None
