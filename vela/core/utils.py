from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def human_size(value: int | float | None, approximate: bool = False) -> str:
    if value is None or value < 0:
        return "—"
    number = float(value)
    if not math.isfinite(number):
        return "—"
    index = 0
    while index < len(_SIZE_UNITS) - 1 and number >= 1024:
        number /= 1024
        index += 1
    if _SIZE_UNITS[index] == "B":
        text = f"{int(number)} B"
    else:
        decimals = 1 if number < 10 else 0
        # Rounding may push the value up to the next unit (e.g. 1024 MB).
        if index < len(_SIZE_UNITS) - 1 and round(number, decimals) >= 1024:
            number /= 1024
            index += 1
            decimals = 1 if number < 10 else 0
        text = f"{number:.{decimals}f} {_SIZE_UNITS[index]}"
    return f"約 {text}" if approximate else text


def human_speed(value: int | float | None) -> str:
    if value is None or value <= 0:
        return "—"
    return f"{human_size(value)}/s"


def human_duration(seconds: int | float | None) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def human_eta(seconds: int | float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    if seconds < 60:
        return f"残り {int(seconds)} 秒"
    if seconds < 3600:
        return f"残り {int(seconds // 60)} 分"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"残り {hours} 時間 {minutes} 分"


def human_count(value: int | None) -> str:
    if value is None:
        return "—"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f} 億"
    if value >= 10_000:
        man = value / 10_000
        # Rounding may push 9999.99万 up to 10000.0万; show 億 instead.
        if round(man, 1) >= 10_000:
            return f"{value / 100_000_000:.1f} 億"
        return f"{man:.1f} 万"
    return f"{value:,}"


def relative_time(timestamp: float | None) -> str:
    if not timestamp:
        return "—"
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()
    now = datetime.now(tz=dt.tzinfo)
    delta = (now - dt).total_seconds()
    if delta < 60:
        return "たった今"
    if delta < 3600:
        return f"{int(delta // 60)} 分前"
    if delta < 86400:
        return f"{int(delta // 3600)} 時間前"
    if delta < 86400 * 7:
        return f"{int(delta // 86400)} 日前"
    return dt.strftime("%Y/%m/%d %H:%M")


def format_datetime(timestamp: float | None) -> str:
    if not timestamp:
        return "—"
    dt = datetime.fromtimestamp(timestamp).astimezone()
    return dt.strftime("%Y/%m/%d %H:%M")


def elapsed_text(seconds: float) -> str:
    if seconds < 1:
        return "1 秒未満"
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes} 分 {secs} 秒"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def middle_elide(text: str, limit: int = 70) -> str:
    if len(text) <= limit:
        return text
    keep = max(4, (limit - 1) // 2)
    return f"{text[:keep]}…{text[-keep:]}"


def safe_int(value: object, default: int | None = None) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def safe_float(value: object, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


_WHITESPACE = re.compile(r"\s+")


def collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def path_exists(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).is_file()
    except OSError:
        return False
