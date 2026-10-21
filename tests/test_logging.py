from __future__ import annotations

import logging
import sys

from vela.core.logging_setup import RedactingFormatter, RedactionFilter, sanitize_text


def _record(msg: object, args: object = (), exc_info=None) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, msg, args, exc_info)


def test_number_placeholders_are_not_broken_by_redaction() -> None:
    formatter = RedactingFormatter("%(message)s")
    record = _record("前回のキューから %d 件を復元しました", (3,))

    RedactionFilter().filter(record)

    assert formatter.format(record) == "前回のキューから 3 件を復元しました"


def test_string_arguments_are_still_redacted() -> None:
    formatter = RedactingFormatter("%(message)s")
    record = _record("取得失敗: %s", ("https://cdn.test/v.mp4?token=SUPERSECRET",))

    RedactionFilter().filter(record)

    output = formatter.format(record)
    assert "SUPERSECRET" not in output
    assert "https://cdn.test/v.mp4" in output


def test_secrets_in_exception_traceback_are_redacted() -> None:
    formatter = RedactingFormatter("%(message)s")
    try:
        raise RuntimeError(
            "download failed https://cdn.test/v.mp4?token=SUPERSECRET Cookie: SID=XYZ"
        )
    except RuntimeError:
        record = _record("処理に失敗しました", (), sys.exc_info())

    RedactionFilter().filter(record)

    output = formatter.format(record)
    assert "SUPERSECRET" not in output
    assert "SID=XYZ" not in output
    assert "<redacted>" in output


def test_sanitize_text_truncates() -> None:
    assert len(sanitize_text("x" * 9000, 4000)) <= 4000
