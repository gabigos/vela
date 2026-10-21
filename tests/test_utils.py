from __future__ import annotations

import time

from vela.core.utils import (
    clamp,
    collapse_whitespace,
    elapsed_text,
    human_count,
    human_duration,
    human_eta,
    human_size,
    human_speed,
    middle_elide,
    relative_time,
    safe_float,
    safe_int,
)


def test_human_size() -> None:
    assert human_size(None) == "—"
    assert human_size(-1) == "—"
    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(1536) == "1.5 KB"
    assert human_size(10 * 1024 * 1024) == "10 MB"
    assert human_size(1024, approximate=True) == "約 1.0 KB"
    # Rounding must roll over into the next unit instead of showing 1024 MB.
    assert human_size(1_073_741_823) == "1.0 GB"
    assert human_size(float("nan")) == "—"
    assert human_size(float("inf")) == "—"


def test_human_speed_and_duration() -> None:
    assert human_speed(None) == "—"
    assert human_speed(0) == "—"
    assert human_speed(1024) == "1.0 KB/s"
    assert human_duration(None) == "—"
    assert human_duration(0) == "—"
    assert human_duration(59) == "0:59"
    assert human_duration(60) == "1:00"
    assert human_duration(3661) == "1:01:01"


def test_human_eta_and_count() -> None:
    assert human_eta(None) == "—"
    assert human_eta(12) == "残り 12 秒"
    assert human_eta(90) == "残り 1 分"
    assert human_eta(3700) == "残り 1 時間 1 分"
    assert human_count(None) == "—"
    assert human_count(9999) == "9,999"
    assert human_count(12_345) == "1.2 万"
    assert human_count(120_000_000) == "1.2 億"
    # 9999.99万 must roll over to 億 rather than show 10000.0 万.
    assert human_count(99_999_999) == "1.0 億"


def test_relative_time() -> None:
    now = time.time()
    assert relative_time(None) == "—"
    assert relative_time(now) == "たった今"
    assert relative_time(now - 120) == "2 分前"
    assert relative_time(now - 7200) == "2 時間前"
    assert relative_time(now - 2 * 86400) == "2 日前"


def test_misc_helpers() -> None:
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
    assert middle_elide("short") == "short"
    assert middle_elide("abcdefghijklmnopqrstuvwxyz", limit=10) == "abcd…wxyz"
    assert safe_int("12") == 12
    assert safe_int("x", 7) == 7
    assert safe_int(True, 9) == 9
    assert safe_float("1.5") == 1.5
    assert safe_float("x", 2.5) == 2.5
    assert collapse_whitespace("  a \n\t b  ") == "a b"
    assert elapsed_text(0.2) == "1 秒未満"
    assert elapsed_text(5.5) == "5.5 秒"
    assert elapsed_text(75) == "1 分 15 秒"
