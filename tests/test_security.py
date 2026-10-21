from __future__ import annotations

from pathlib import Path

import pytest

from vela.core.security import (
    ensure_within_directory,
    redact_url,
    resolve_public_host,
    validate_redirect_target,
    validate_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "http://example.com/video.mp4",
        "https://vimeo.com/123456",
        "www.youtube.com/watch?v=abc123",
        "//example.com/path",
    ],
)
def test_valid_urls_are_accepted(url: str) -> None:
    result = validate_url(url)
    assert result.ok, result.message
    assert result.url.startswith(("http://", "https://"))


def test_bare_domain_gets_https() -> None:
    result = validate_url("example.com/watch")
    assert result.ok
    assert result.url == "https://example.com/watch"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", "empty"),
        ("javascript:alert(1)", "scheme"),
        ("file:///C:/Windows/win.ini", "scheme"),
        ("ftp://example.com/video", "scheme"),
        ("https://user:pass@example.com/video", "userinfo"),
        ("https://example.com/a b", "invalid_chars"),
        ("http://localhost:8080/video", "private_host"),
        ("http://127.0.0.1/video", "private_host"),
        ("http://192.168.1.20/video", "private_host"),
        ("http://[::1]/video", "private_host"),
        ("http://router.local/video", "private_host"),
        ("https://example.com:abc/video", "port"),
        ("https://example.com:70000/video", "port"),
        ("https://example.com:0/video", "port"),
    ],
)
def test_unsafe_urls_are_rejected(url: str, reason: str) -> None:
    result = validate_url(url)
    assert not result.ok
    assert result.reason


def test_invalid_port_is_rejected_before_dns_resolution() -> None:
    result = resolve_public_host("https://example.com:not-a-port/video")
    assert not result.ok
    assert result.reason == "port"


def test_private_hosts_can_be_allowed_explicitly() -> None:
    result = validate_url("http://127.0.0.1:8080/video.mp4", allow_private=True)
    assert result.ok
    assert result.url == "http://127.0.0.1:8080/video.mp4"


def test_redirect_guard_uses_the_same_rules() -> None:
    assert validate_redirect_target("https://example.com/video").ok
    assert not validate_redirect_target("http://localhost/admin")
    assert not validate_redirect_target("data:text/html,hi")


def test_redact_url_removes_credentials_and_secrets() -> None:
    redacted = redact_url(
        "https://user:secret@example.com/watch?token=abc123&v=42&sig=xyz#frag"
    )
    assert "user" not in redacted
    assert "secret" not in redacted
    assert "abc123" not in redacted
    assert "xyz" not in redacted
    assert "example.com" in redacted
    assert "v=42" not in redacted


def test_redact_url_keeps_query_when_requested() -> None:
    redacted = redact_url(
        "https://example.com/watch?v=42&access_token=secret", keep_query=True
    )
    assert "v=42" in redacted
    assert "secret" not in redacted


def test_ensure_within_directory(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    inside = root / "clip.mp4"
    inside.write_bytes(b"data")
    assert ensure_within_directory(inside, root)
    assert not ensure_within_directory(tmp_path / "other.mp4", root)
