from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_ALLOWED_SCHEMES = {"http", "https"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,251}[a-z0-9])?$")
_BLOCKED_SUFFIXES = (
    ".local",
    ".localhost",
    ".localdomain",
    ".internal",
    ".lan",
    ".home",
    ".home.arpa",
    ".test",
    ".invalid",
    ".example",
    ".onion",
)


@dataclass(frozen=True)
class URLValidation:
    ok: bool
    url: str = ""
    message: str = ""
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def _is_blocked_hostname(hostname: str) -> str:
    """Return a user-facing reason when a host must not be contacted."""
    host = hostname.strip().lower().rstrip(".")
    if not host:
        return "URL にホスト名が含まれていません。"
    if host in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}:
        return "ローカルネットワーク上のアドレスには接続できません。"
    if host.endswith(_BLOCKED_SUFFIXES):
        return "ローカルネットワーク上のアドレスには接続できません。"
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if not _HOSTNAME_RE.match(host):
            return "URL のホスト名が不正です。"
        return ""
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or not address.is_global
    ):
        return "ローカルネットワークや内部サービス上のアドレスには接続できません。"
    return ""


def validate_url(raw: str, *, allow_private: bool = False) -> URLValidation:
    text = (raw or "").strip()
    if not text:
        return URLValidation(False, message="URL を入力してください。", reason="empty")
    if len(text) > 4096:
        return URLValidation(False, message="URL が長すぎます。", reason="too_long")
    if _CONTROL_CHARS.search(text) or any(char.isspace() for char in text):
        return URLValidation(
            False,
            message="URL に空白や制御文字が含まれています。コピーし直してください。",
            reason="invalid_chars",
        )
    if "://" not in text:
        if text.startswith("//"):
            text = f"https:{text}"
        elif re.match(r"^[\w.-]+\.[a-z]{2,}(?:[/:?#]|$)", text, re.IGNORECASE):
            text = f"https://{text}"
        else:
            return URLValidation(
                False,
                message="http:// または https:// で始まる URL を入力してください。",
                reason="scheme",
            )
    try:
        parsed = urlsplit(text)
    except ValueError:
        return URLValidation(False, message="URL を解釈できませんでした。", reason="parse")
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return URLValidation(
            False,
            message="http:// または https:// の URL のみ利用できます。",
            reason="scheme",
        )
    if parsed.username or parsed.password:
        return URLValidation(
            False,
            message="URL に認証情報を含めることはできません。Cookie 設定を利用してください。",
            reason="userinfo",
        )
    if not parsed.hostname:
        return URLValidation(False, message="URL にホスト名が含まれていません。", reason="host")
    try:
        port = parsed.port
    except ValueError:
        return URLValidation(
            False,
            message="URL のポート番号が不正です。",
            reason="port",
        )
    if port is not None and not 1 <= port <= 65535:
        return URLValidation(
            False,
            message="URL のポート番号が不正です。",
            reason="port",
        )
    if not allow_private:
        blocked = _is_blocked_hostname(parsed.hostname)
        if blocked:
            return URLValidation(False, message=blocked, reason="private_host")
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            parsed.fragment,
        )
    )
    return URLValidation(True, url=normalized)


def resolve_public_host(url: str, *, allow_private: bool = False) -> URLValidation:
    """Validate the URL and ensure every resolved address is public.

    DNS answers can change after this check (DNS rebinding), and HTTP
    redirects are followed by yt-dlp. Literal private hosts are also blocked
    inside :class:`vela.core.ytdlp_service.SafeYoutubeDL`, which reduces the
    risk of redirect-based access to internal services.
    """
    validation = validate_url(url, allow_private=allow_private)
    if not validation:
        return validation
    if allow_private:
        return validation
    parsed = urlsplit(validation.url)
    host = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError, UnicodeError) as exc:
        return URLValidation(
            False,
            message="ホスト名を解決できませんでした。インターネット接続を確認してください。",
            reason=f"dns:{exc}",
        )
    for info in infos:
        address_text = info[4][0]
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            continue
        if not address.is_global:
            return URLValidation(
                False,
                message="この URL はローカルネットワーク上のアドレスを指しているため接続できません。",
                reason="private_dns",
            )
    return validation


def validate_redirect_target(url: str) -> URLValidation:
    """Cheap check applied to every request URL (no DNS lookup)."""
    return validate_url(url)


def ensure_within_directory(file_path: str | Path, directory: str | Path) -> bool:
    try:
        child = Path(file_path).resolve()
        parent = Path(directory).resolve()
        child.relative_to(parent)
        return True
    except (OSError, ValueError):
        return False


_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|access_token|auth|authorization|sig|signature|key|api_key|apikey|"
    r"expire|expires|hdnts|policy|session|sessionid|password|passwd|pwd|cookie|"
    r"client_secret|code|state|sp|se|sig|n)=)[^&#\s]+"
)


def redact_url(url: str, keep_query: bool = False) -> str:
    """Remove user info and sensitive query values from a URL."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    if not host:
        return "<invalid-url>"
    netloc = host
    try:
        if parsed.port:
            netloc = f"{host}:{parsed.port}"
    except ValueError:
        pass
    query = parsed.query if keep_query else ""
    if query:
        query = _SECRET_QUERY_RE.sub(r"\1<redacted>", query)
    if parsed.fragment and not keep_query:
        fragment = ""
    else:
        fragment = parsed.fragment
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment))
