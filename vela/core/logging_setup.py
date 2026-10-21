from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .security import redact_url

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_HEADER_RE = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|x-api-key|proxy-authorization)\s*[:=]\s*[^\r\n]+"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|access[_-]?token)\b\s*[:=]\s*[\"']?[^\s\"'&,;]+"
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def sanitize_text(text: str, max_length: int = 8000) -> str:
    if not text:
        return ""
    cleaned = _ANSI_RE.sub("", str(text))
    cleaned = _URL_RE.sub(lambda match: redact_url(match.group(0)), cleaned)
    cleaned = _HEADER_RE.sub(lambda match: f"{match.group(1)}: <redacted>", cleaned)
    cleaned = _SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", cleaned)
    if len(cleaned) > max_length:
        if max_length <= 1:
            cleaned = "…"[:max_length]
        else:
            cleaned = cleaned[: max_length - 1] + "…"
    return cleaned


def _sanitize_arg(value: object) -> object:
    # Only strings can carry secrets.  Converting numbers to str() would break
    # %d/%f style placeholders in the log message.
    if isinstance(value, str):
        return sanitize_text(value, 500)
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = sanitize_text(str(record.msg))
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        key: _sanitize_arg(value) for key, value in record.args.items()
                    }
                else:
                    record.args = tuple(_sanitize_arg(value) for value in record.args)
        except Exception:  # pragma: no cover - logging must never break
            record.msg = "<log message could not be sanitized>"
            record.args = ()
        return True


class RedactingFormatter(logging.Formatter):
    """Formatter that also redacts text produced after filtering.

    ``RedactionFilter`` only sees ``record.msg``/``record.args``.  Exception
    tracebacks and stack info are rendered later by the formatter, so secrets
    embedded in an exception message (tokens, cookies) would otherwise reach
    the log file.  Sanitizing the final string closes that hole.
    """

    def format(self, record: logging.LogRecord) -> str:
        return sanitize_text(super().format(record), 20000)


class MemoryLogHandler(logging.Handler):
    """Small ring buffer used by the diagnostics page and crash dialog."""

    def __init__(self, capacity: int = 800) -> None:
        super().__init__()
        self.capacity = capacity
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(self.format(record))
            if len(self.records) > self.capacity:
                del self.records[: len(self.records) - self.capacity]
        except Exception:  # pragma: no cover
            pass


_memory_handler: MemoryLogHandler | None = None


def setup_logging(log_file: Path, *, level: int = logging.INFO) -> MemoryLogHandler:
    global _memory_handler
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    redaction = RedactionFilter()
    file_handler = RotatingFileHandler(
        log_file, maxBytes=4 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(RedactingFormatter(LOG_FORMAT, DATE_FORMAT))
    file_handler.addFilter(redaction)
    root.addHandler(file_handler)

    _memory_handler = MemoryLogHandler()
    _memory_handler.setFormatter(RedactingFormatter(LOG_FORMAT, DATE_FORMAT))
    _memory_handler.addFilter(redaction)
    root.addHandler(_memory_handler)

    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(
            RedactingFormatter("%(levelname)-7s %(name)s: %(message)s")
        )
        console.addFilter(redaction)
        root.addHandler(console)

    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return _memory_handler


def get_memory_handler() -> MemoryLogHandler | None:
    return _memory_handler


def read_log_tail(path: Path, max_lines: int = 500) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return "".join(lines[-max_lines:])
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return f"ログを読み込めませんでした: {exc}"


class YtdlpLogger:
    """Routes yt-dlp messages into Python logging with redaction."""

    def __init__(self, name: str = "yt_dlp") -> None:
        self._logger = logging.getLogger(name)

    def debug(self, message: str) -> None:
        if message.startswith("[debug] "):
            self._logger.debug(message[8:])
        else:
            self._logger.debug(message)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)
