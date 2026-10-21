from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QAction, QFont, QFontDatabase, QFontInfo
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton, QWidget
from shiboken6 import isValid

from vela.app import create_runtime
from vela.core.ffmpeg_tools import discover_ffmpeg
from vela.core.models import FormatInfo, PlaylistEntry, VideoInfo
from vela.core.paths import app_root
from vela.ui.dialogs import ConfirmDialog
from vela.ui.theme import set_animations_enabled
from vela.ui.widgets import FlowLayout, SegmentedControl, Switch, fade_in


@pytest.fixture()
def runtime(qapp: QApplication, tmp_path: Path):
    from vela.core.paths import AppPaths

    paths = AppPaths(tmp_path / "ui-data")
    paths.ensure()
    instance = create_runtime(qapp, paths)
    instance.window.resize(1280, 840)
    yield instance
    instance.ctx.history.close()
    instance.window._closing = True  # noqa: SLF001 - avoid the confirmation dialog
    instance.window.close()


def test_app_root_points_at_repository() -> None:
    root = app_root()
    assert (root / "main.py").is_file()
    assert (root / "vela" / "__init__.py").is_file()


def test_bundled_ffmpeg_is_discovered(project_root: Path) -> None:
    expected = project_root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if not expected.is_file():
        pytest.skip("bundled FFmpeg is not present")
    info = discover_ffmpeg()
    assert info.available
    assert info.ffmpeg == expected
    assert info.ffprobe is not None and info.ffprobe.is_file()
    assert info.source == "同梱"


def test_all_pages_can_be_navigated(runtime) -> None:
    window = runtime.window
    window.show()
    for page in ("home", "queue", "history", "settings", "diagnostics"):
        window.navigate(page, animate=False)
        QApplication.processEvents()
        assert window.stack.currentWidget() is not None
    assert window.stack.count() == 5
    assert window.minimumWidth() == 1040


def test_nav_indicator_tracks_active_page(runtime) -> None:
    window = runtime.window
    window.show()
    QApplication.processEvents()
    indicator = window._nav_indicator  # noqa: SLF001

    def expected(page: str) -> QRect:
        button = window._nav_buttons[page]  # noqa: SLF001
        target = QRect(
            button.mapTo(indicator.parentWidget(), button.rect().topLeft()),
            button.size(),
        )
        target.adjust(0, 1, 0, -1)
        return target

    for page in ("home", "queue", "history", "settings", "diagnostics"):
        window.navigate(page, animate=False)
        QApplication.processEvents()
        assert indicator.isVisible()
        assert indicator.geometry() == expected(page)

    window.navigate("queue", animate=True)
    QTest.qWait(260)
    assert indicator.geometry() == expected("queue")


def test_duplicate_toasts_collapse_and_stack_without_overlap(runtime) -> None:
    window = runtime.window
    window.show()
    message = ("URL をコピーしました", "https://example.com/watch?v=abc")
    for _ in range(3):
        window.toast(*message, "success")

    QApplication.processEvents()
    assert len(window.toasts._toasts) == 1  # noqa: SLF001

    window.toast("通知A", "1")
    window.toast("通知B", "2")
    window.toast("通知C", "3")
    QApplication.processEvents()
    QTest.qWait(30)

    toasts = window.toasts._toasts  # noqa: SLF001
    assert len(toasts) == 2
    ordered = sorted(toasts, key=lambda toast: toast.geometry().top())
    assert ordered[0].geometry().bottom() < ordered[1].geometry().top()


def test_format_table_uses_single_checkbox_selection(runtime) -> None:
    window = runtime.window
    window.show()
    home = window.home
    info = VideoInfo(
        url="https://example.com/watch?v=abc",
        title="Example",
        formats=[
            FormatInfo(
                format_id="137",
                ext="mp4",
                height=1080,
                fps=30,
                vcodec="avc1.640028",
            ),
            FormatInfo(
                format_id="136",
                ext="mp4",
                height=720,
                fps=30,
                vcodec="avc1.4d401f",
            ),
        ],
    )
    home._video = info  # noqa: SLF001
    home._render_result(info)  # noqa: SLF001
    QApplication.processEvents()
    home._format_segment.set_value("custom", emit=True)  # noqa: SLF001
    QApplication.processEvents()

    table = home._format_table  # noqa: SLF001
    assert table is not None
    assert table.columnCount() == 6
    assert table.horizontalHeaderItem(0).text() == "選択"

    def checked_rows() -> list[int]:
        return [
            row
            for row in range(table.rowCount())
            if table.item(row, 0) is not None
            and table.item(row, 0).checkState() == Qt.Checked
        ]

    initial = checked_rows()
    assert len(initial) == 1
    target = 1 if initial[0] != 1 else 0
    table.item(target, 0).setCheckState(Qt.Checked)
    QApplication.processEvents()

    assert checked_rows() == [target]
    assert home._selected_key == table.item(target, 0).data(Qt.UserRole)  # noqa: SLF001

    selected_before = home._selected_key  # noqa: SLF001
    text_rect = table.visualItemRect(table.item(0, 2))
    QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=text_rect.center())
    QApplication.processEvents()
    assert checked_rows() == [target]
    assert home._selected_key == selected_before  # noqa: SLF001

    check_rect = table.visualItemRect(table.item(0, 0))
    QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=check_rect.center())
    QApplication.processEvents()
    assert checked_rows() == [0]


def test_theme_switch_updates_controls(runtime) -> None:
    window = runtime.window
    window.show()
    window.navigate("settings", animate=False)
    QApplication.processEvents()
    result = window.apply_settings({"theme": "light"})
    assert result is not None
    assert runtime.ctx.settings.theme == "light"
    assert window.settings_page.theme_control.selected() == "light"
    assert "ダーク" in window.theme_button.toolTip()
    assert window.theme_button.property("velaIconName") == "moon"

    window.apply_settings({"theme": "dark"})
    assert runtime.ctx.settings.theme == "dark"
    assert window.settings_page.theme_control.selected() == "dark"
    assert window.theme_button.property("velaIconName") == "sun"


def test_scrolling_pages_fit_at_minimum_width(runtime) -> None:
    window = runtime.window
    window.resize(1040, 700)
    window.show()
    pages = {
        "home": window.home,
        "settings": window.settings_page,
        "diagnostics": window.diagnostics_page,
    }
    for name, page in pages.items():
        window.navigate(name, animate=False)
        QApplication.processEvents()
        scroll = getattr(page, "scroll", None)
        assert scroll is not None
        assert scroll.horizontalScrollBar().maximum() == 0, name


def test_fade_in_cleans_up_after_animation(qapp: QApplication) -> None:
    widget = QWidget()
    widget.resize(120, 60)
    widget.show()
    set_animations_enabled(True)
    try:
        fade_in(widget, duration=30)
        assert widget.graphicsEffect() is not None
        QTest.qWait(90)
        assert widget.graphicsEffect() is None
    finally:
        set_animations_enabled(True)
        widget.close()


def test_fade_in_is_a_noop_when_animations_are_disabled(qapp: QApplication) -> None:
    widget = QWidget()
    widget.show()
    set_animations_enabled(False)
    try:
        fade_in(widget, duration=30)
        assert widget.graphicsEffect() is None
    finally:
        set_animations_enabled(True)
        widget.close()


def test_search_icon_is_not_duplicated(runtime) -> None:
    window = runtime.window
    window.show()
    for name, page in (("queue", window.queue_page), ("history", window.history_page)):
        window.navigate(name, animate=False)
        QApplication.processEvents()
        page.refresh_theme()
        page.refresh_theme()
        QApplication.processEvents()
        actions = page.search.findChildren(QAction)
        assert len(actions) == 2, [action.text() for action in actions]
        assert len([action for action in actions if not action.isEnabled()]) == 1


def test_diagnostics_environment_does_not_duplicate_rows(runtime) -> None:
    window = runtime.window
    window.show()
    window.navigate("diagnostics", animate=False)
    QApplication.processEvents()
    grid = window.diagnostics_page.env_grid
    count = grid.count()
    assert count >= 20
    window.diagnostics_page.refresh_theme()
    window.diagnostics_page.refresh_theme()
    QApplication.processEvents()
    assert grid.count() == count


def test_settings_headings_are_left_aligned(runtime) -> None:
    window = runtime.window
    window.show()
    window.navigate("settings", animate=False)
    QApplication.processEvents()
    labels = [
        label
        for label in window.settings_page.findChildren(QLabel)
        if label.text() in {"テーマ", "アクセントカラー", "アニメーション"}
    ]
    assert len(labels) == 3
    xs = {label.geometry().x() for label in labels}
    assert len(xs) == 1, xs


def test_ui_font_supports_japanese(runtime) -> None:
    japanese_families = QFontDatabase.families(QFontDatabase.WritingSystem.Japanese)
    if not japanese_families:
        pytest.skip("the offscreen Qt platform exposes no font database")
    family = QFontInfo(runtime.app.font()).family()
    assert family in japanese_families


def test_custom_rows_grow_with_larger_fonts(qapp: QApplication) -> None:
    from vela.ui.pages.history import _history_layout
    from vela.ui.pages.queue import _queue_layout

    small = QFont()
    small.setPointSizeF(10.0)
    large = QFont()
    large.setPointSizeF(20.0)
    assert _queue_layout(large)["row_height"] > _queue_layout(small)["row_height"]
    assert _history_layout(large)["row_height"] > _history_layout(small)["row_height"]


def test_home_site_chips_keep_their_height_after_hero_is_shown_again(runtime) -> None:
    window = runtime.window
    window.show()
    window.navigate("home", animate=False)
    QTest.qWait(100)

    home = window.home
    flow = next(flow for flow in home.findChildren(FlowLayout) if flow.count() == 12)
    chips = flow.parentWidget()
    expected = flow.heightForWidth(chips.width())
    assert expected > 0
    assert chips.height() >= expected

    # The hero is hidden while an analysis result is displayed and shown
    # again when the result is cleared.  The flow layout must not cache the
    # zero height produced while its parent was hidden.
    home._hero_extra.hide()
    QTest.qWait(80)
    home._hero_extra.show()
    QTest.qWait(120)

    assert flow.heightForWidth(chips.width()) == expected
    assert chips.height() >= expected


def test_segmented_control_ignores_deleted_buttons(qapp: QApplication) -> None:
    control = SegmentedControl([("a", "A"), ("b", "B")], "a")
    control.show()
    QTest.qWait(20)

    selected = control._buttons["a"]
    selected.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(selected)

    # A pending indicator sync must not dereference a QPushButton whose C++
    # object was deleted with the previous analysis result.
    control._sync_indicator()
    control.close()
    control.deleteLater()


def test_segmented_controls_do_not_clip_their_labels(runtime) -> None:
    window = runtime.window
    window.show()
    window.navigate("settings", animate=False)
    QApplication.processEvents()
    controls = [
        window.settings_page.theme_control,
        window.settings_page.container_control,
        window.settings_page.overwrite_control,
        window.settings_page.audio_control,
    ]
    window.navigate("queue", animate=False)
    QApplication.processEvents()
    controls.append(window.queue_page.filter)

    for control in controls:
        assert control.height() >= control.sizeHint().height()
        for button in control.findChildren(QPushButton):
            assert button.text()
            assert button.height() >= button.sizeHint().height(), (
                button.text(),
                button.height(),
                button.sizeHint().height(),
            )


def test_switch_snaps_knob_when_signals_are_blocked(qapp: QApplication) -> None:
    # Settings sync calls setChecked() inside blockSignals(True); toggled() is
    # skipped then, so the knob offset must still be updated.
    switch = Switch(checked=False)
    switch.blockSignals(True)
    switch.setChecked(True)
    switch.blockSignals(False)

    assert switch.isChecked()
    assert switch._offset == 1.0  # noqa: SLF001
    switch.deleteLater()


def test_theme_button_tooltip_matches_light_palette(runtime) -> None:
    window = runtime.window
    window.ctx.theme.apply("light", window.ctx.settings.accent, False)

    assert "ダークテーマに切り替え" in window.theme_button.toolTip()


def test_theme_switch_keeps_playlist_selection(runtime) -> None:
    window = runtime.window
    window.show()
    window.navigate("home", animate=False)
    home = window.home
    info = VideoInfo(
        url="https://example.com/list",
        title="List",
        is_playlist=True,
        playlist_title="List",
        entries=[
            PlaylistEntry(index=0, title="a", url="https://example.com/a"),
            PlaylistEntry(index=1, title="b", url="https://example.com/b"),
        ],
    )
    home._video = info  # noqa: SLF001
    home._render_result(info)  # noqa: SLF001
    QApplication.processEvents()

    home._playlist_table.item(0, 0).setCheckState(Qt.Unchecked)  # noqa: SLF001
    home._playlist_quality.set_value("audio", emit=False)  # noqa: SLF001

    home.refresh_theme()
    QApplication.processEvents()

    table = home._playlist_table  # noqa: SLF001
    assert table.item(0, 0).checkState() == Qt.Unchecked
    assert table.item(1, 0).checkState() == Qt.Checked
    assert home._playlist_quality.selected() == "audio"  # noqa: SLF001


def test_restore_session_reports_queue_warnings(runtime, monkeypatch) -> None:
    window = runtime.window
    monkeypatch.setattr(runtime.ctx.queue, "load_state", lambda *a, **k: 0)
    monkeypatch.setattr(
        type(runtime.ctx.queue),
        "warnings",
        property(lambda self: ["前回のキューを復元できませんでした。"]),
    )

    window._restore_session()  # noqa: SLF001

    titles = {
        label.text()
        for toast in window.toasts._toasts  # noqa: SLF001
        for label in toast.findChildren(QLabel)
    }
    assert "キューを確認しました" in titles


def test_choose_ffmpeg_rejects_folder_without_ffmpeg(
    runtime, monkeypatch, tmp_path: Path
) -> None:
    window = runtime.window
    window.show()
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path)),
    )
    before = runtime.ctx.settings.ffmpeg_dir

    window.settings_page._choose_ffmpeg()  # noqa: SLF001

    assert runtime.ctx.settings.ffmpeg_dir == before


def test_reset_settings_does_not_write_before_apply(
    runtime, monkeypatch
) -> None:
    window = runtime.window
    page = window.settings_page
    called = {"reset": False}

    def fake_reset():
        called["reset"] = True
        return runtime.ctx.settings

    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: True))
    monkeypatch.setattr(runtime.ctx.store, "reset", fake_reset)
    monkeypatch.setattr(page, "_apply_settings", lambda changes: None)

    page._reset_settings()  # noqa: SLF001

    assert called["reset"] is False
