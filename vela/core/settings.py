from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from urllib.parse import urlparse

from .paths import default_download_dir

SETTINGS_VERSION = 1

DEFAULT_FILENAME_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"
FALLBACK_FILENAME_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"

THEMES = ("system", "dark", "light")
ACCENTS = ("indigo", "ocean", "rose", "amber")
CONTAINERS = ("auto", "mp4", "mkv")
OVERWRITE_POLICIES = ("rename", "overwrite", "skip")
AUDIO_FORMATS = ("mp3", "m4a", "original")


@dataclass
class Settings:
    version: int = SETTINGS_VERSION
    theme: str = "dark"
    accent: str = "indigo"
    animations: bool = True
    save_dir: str = field(default_factory=lambda: str(default_download_dir()))
    filename_template: str = DEFAULT_FILENAME_TEMPLATE
    container: str = "auto"
    overwrite: str = "rename"
    concurrency: int = 2
    rate_limit_mbps: int = 0
    audio_format: str = "mp3"
    proxy: str = ""
    cookies_file: str = ""
    history_limit: int = 1000
    restore_queue: bool = True
    check_updates: bool = False
    ffmpeg_dir: str = ""
    last_page: str = "home"
    window_width: int = 1280
    window_height: int = 840

    def clone(self) -> "Settings":
        return replace(self)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> tuple["Settings", list[str]]:
        warnings: list[str] = []
        settings = cls()
        if not isinstance(raw, dict):
            return settings, ["設定ファイルの形式が不正なため、初期設定を使用しました。"]
        known = {item.name for item in fields(cls)}
        for key, value in raw.items():
            if key not in known:
                continue
            setattr(settings, key, value)
        normalized, issues = settings.normalized()
        warnings.extend(issues)
        return normalized, warnings

    def normalized(self) -> tuple["Settings", list[str]]:
        data = self.to_dict()
        issues: list[str] = []

        def one_of(key: str, allowed: tuple[str, ...], default: str) -> None:
            value = data.get(key)
            if value not in allowed:
                data[key] = default
                issues.append(f"{key} の値が不正だったため、既定値に戻しました。")

        def bounded_int(key: str, low: int, high: int, default: int) -> None:
            try:
                value = int(data.get(key))
            except (TypeError, ValueError):
                data[key] = default
                issues.append(f"{key} の値が不正だったため、既定値に戻しました。")
                return
            if value < low or value > high:
                data[key] = max(low, min(high, value))
                issues.append(f"{key} を {data[key]} に調整しました。")

        one_of("theme", THEMES, "dark")
        one_of("accent", ACCENTS, "indigo")
        one_of("container", CONTAINERS, "auto")
        one_of("overwrite", OVERWRITE_POLICIES, "rename")
        one_of("audio_format", AUDIO_FORMATS, "mp3")
        bounded_int("concurrency", 1, 6, 2)
        bounded_int("rate_limit_mbps", 0, 1000, 0)
        bounded_int("history_limit", 50, 20000, 1000)
        bounded_int("window_width", 900, 6000, 1280)
        bounded_int("window_height", 600, 4000, 840)

        for key, default in (
            ("animations", True),
            ("restore_queue", True),
            ("check_updates", False),
        ):
            if not isinstance(data.get(key), bool):
                data[key] = default
                issues.append(f"{key} の値が不正だったため、既定値に戻しました。")

        save_dir = str(data.get("save_dir") or "").strip()
        if not save_dir:
            save_dir = str(default_download_dir())
        try:
            save_dir = str(Path(os.path.expandvars(os.path.expanduser(save_dir))).resolve())
        except (OSError, RuntimeError):
            save_dir = str(default_download_dir())
            issues.append("保存先のパスを解釈できなかったため、既定の保存先を使用します。")
        data["save_dir"] = save_dir

        template, template_error = validate_filename_template(
            str(data.get("filename_template") or "")
        )
        if template_error:
            issues.append(template_error)
        data["filename_template"] = template or FALLBACK_FILENAME_TEMPLATE

        proxy = str(data.get("proxy") or "").strip()
        if proxy and not validate_proxy(proxy):
            issues.append("プロキシ URL の形式が不正なため、設定を使用しません。")
            proxy = ""
        data["proxy"] = proxy

        cookies = str(data.get("cookies_file") or "").strip()
        data["cookies_file"] = str(Path(cookies).expanduser()) if cookies else ""

        ffmpeg_dir = str(data.get("ffmpeg_dir") or "").strip()
        data["ffmpeg_dir"] = str(Path(ffmpeg_dir).expanduser()) if ffmpeg_dir else ""

        last_page = data.get("last_page")
        if last_page not in ("home", "queue", "history", "settings", "diagnostics"):
            data["last_page"] = "home"

        return Settings(**data), issues


def validate_filename_template(template: str) -> tuple[str, str | None]:
    template = (template or "").strip()
    if not template:
        return "", "ファイル名テンプレートが空のため、既定値を使用します。"
    if len(template) > 240:
        return "", "ファイル名テンプレートが長すぎるため、既定値を使用します。"
    if any(char in template for char in ("/", "\\", "\0")):
        return "", "ファイル名テンプレートにパス区切り文字は使用できません。"
    if ".." in template:
        return "", "ファイル名テンプレートに '..' は使用できません。"
    if any(ord(char) < 32 for char in template):
        return "", "ファイル名テンプレートに制御文字は使用できません。"
    if "%(ext)s" not in template:
        template = f"{template}.%(ext)s"
    return template, None


def validate_proxy(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https", "socks5", "socks5h"):
        return False
    if not parsed.hostname:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    return port is None or 0 < port < 65536


def validate_save_dir(value: str) -> tuple[bool, str]:
    try:
        path = Path(os.path.expandvars(os.path.expanduser(value)))
        if path.exists() and not path.is_dir():
            return False, "指定されたパスはファイルです。フォルダーを選択してください。"
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".vela-write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, ""
    except OSError as exc:
        return False, f"保存先に書き込めません: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"保存先を確認できませんでした: {exc}"


def sanitize_filename_component(value: str, max_length: int = 120) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    name = name.strip().rstrip(". ")
    if not name:
        name = "download"
    stem = name.split(".")[0].upper()
    if stem in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = f"_{name}"
    if len(name) > max_length:
        suffix = Path(name).suffix[:12]
        name = name[: max_length - len(suffix)].rstrip(". ") + suffix
    return name


class SettingsStore:
    """Loads and atomically saves the JSON settings file.

    Corrupt files are preserved next to the original so the user (or a
    developer) can inspect them, while the application always starts with
    usable defaults.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.warnings: list[str] = []

    def load(self) -> Settings:
        self.warnings = []
        if not self.path.exists():
            settings = Settings()
            normalized, issues = settings.normalized()
            self.warnings.extend(issues)
            return normalized
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            self.warnings.append(f"設定ファイルを読み込めませんでした: {exc}")
            settings, _ = Settings().normalized()
            return settings
        try:
            raw = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            self._preserve_corrupt()
            self.warnings.append(f"設定ファイルが破損していたため、初期設定で起動しました（{exc}）。")
            settings, _ = Settings().normalized()
            return settings
        settings, issues = Settings.from_dict(raw)
        self.warnings.extend(issues)
        return settings

    def _preserve_corrupt(self) -> bool:
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}.json")
            shutil.copy2(self.path, backup)
        except OSError:
            return False
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        return True

    def save(self, settings: Settings) -> None:
        normalized, issues = settings.normalized()
        self.warnings = issues
        payload = json.dumps(normalized.to_dict(), ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                shutil.copy2(self.path, self.path.with_suffix(".bak"))
            except OSError:
                pass
        fd, temp_name = tempfile.mkstemp(
            prefix=".settings-", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def reset(self) -> Settings:
        settings, _ = Settings().normalized()
        self.save(settings)
        return settings
