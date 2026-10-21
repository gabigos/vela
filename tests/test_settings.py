from __future__ import annotations

import json
from pathlib import Path

from vela.core.settings import (
    DEFAULT_FILENAME_TEMPLATE,
    Settings,
    SettingsStore,
    sanitize_filename_component,
    validate_filename_template,
    validate_proxy,
    validate_save_dir,
)


def test_defaults_are_normalized(paths) -> None:
    settings, issues = Settings().normalized()
    assert issues == []
    assert settings.theme == "dark"
    assert settings.concurrency == 2
    assert Path(settings.save_dir).is_absolute()
    assert settings.filename_template == DEFAULT_FILENAME_TEMPLATE


def test_invalid_values_fall_back() -> None:
    settings, issues = Settings.from_dict(
        {
            "theme": "neon",
            "accent": "green",
            "container": "avi",
            "overwrite": "ask",
            "audio_format": "flac",
            "concurrency": 99,
            "rate_limit_mbps": -5,
            "history_limit": 1,
            "window_width": 10,
            "window_height": 99999,
            "animations": "yes",
            "filename_template": "bad/name",
            "proxy": "not-a-proxy",
            "last_page": "unknown",
        }
    )
    assert settings.theme == "dark"
    assert settings.accent == "indigo"
    assert settings.container == "auto"
    assert settings.overwrite == "rename"
    assert settings.audio_format == "mp3"
    assert settings.concurrency == 6
    assert settings.rate_limit_mbps == 0
    assert settings.history_limit == 50
    assert settings.window_width == 900
    assert settings.window_height == 4000
    assert settings.animations is True
    assert settings.filename_template == DEFAULT_FILENAME_TEMPLATE
    assert settings.proxy == ""
    assert settings.last_page == "home"
    assert issues


def test_invalid_boolean_values_use_their_own_default() -> None:
    settings, issues = Settings.from_dict(
        {"animations": "yes", "restore_queue": 0, "check_updates": "sometimes"}
    )
    assert settings.animations is True
    assert settings.restore_queue is True
    assert settings.check_updates is False
    assert issues


def test_filename_template_validation() -> None:
    assert validate_filename_template("")[0] == ""
    assert validate_filename_template("a/b")[0] == ""
    assert validate_filename_template("..")[0] == ""
    assert validate_filename_template("x" * 300)[0] == ""
    template, error = validate_filename_template("%(title)s")
    assert template == "%(title)s.%(ext)s"
    assert error is None


def test_proxy_validation() -> None:
    assert validate_proxy("http://127.0.0.1:8080")
    assert validate_proxy("socks5h://proxy.example.com:1080")
    assert not validate_proxy("ftp://proxy.example.com")
    assert not validate_proxy("http://")
    assert not validate_proxy("http://proxy.example.com:70000")


def test_save_dir_validation(tmp_path: Path) -> None:
    target = tmp_path / "new" / "folder"
    ok, message = validate_save_dir(str(target))
    assert ok, message
    assert target.is_dir()
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    ok, _ = validate_save_dir(str(file_path))
    assert not ok


def test_filename_component_sanitizing() -> None:
    assert sanitize_filename_component('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize_filename_component("CON") == "_CON"
    assert sanitize_filename_component("   ") == "download"
    assert len(sanitize_filename_component("x" * 500, max_length=50)) <= 50


def test_store_roundtrip_and_backup(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = store.reset()
    settings.theme = "light"
    settings.concurrency = 4
    store.save(settings)
    loaded = store.load()
    assert loaded.theme == "light"
    assert loaded.concurrency == 4
    assert (tmp_path / "settings.bak").exists()


def test_corrupt_settings_are_preserved_and_replaced(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")
    store = SettingsStore(path)
    settings = store.load()
    assert settings.theme == "dark"
    assert store.warnings
    backups = list(tmp_path.glob("settings.corrupt-*.json"))
    assert backups and backups[0].exists()
    assert not path.exists()


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "light", "evil": "x"}), encoding="utf-8")
    settings = SettingsStore(path).load()
    assert settings.theme == "light"
    assert not hasattr(settings, "evil")
