from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QToolTip, QWidget


@dataclass(frozen=True)
class Palette:
    mode: str
    bg: str
    bg_elevated: str
    sidebar: str
    surface: str
    surface_alt: str
    surface_hover: str
    card: str
    border: str
    border_strong: str
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_strong: str
    accent_soft: str
    accent_border: str
    accent_text: str
    gradient_a: str
    gradient_b: str
    on_accent: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    info: str
    info_soft: str
    input_bg: str
    selection: str
    shadow: str
    overlay: str
    nav_active: str
    pill_bg: str
    card_highlight: str
    input_bg_focus: str

    @property
    def is_dark(self) -> bool:
        return self.mode == "dark"


ACCENTS: dict[str, dict[str, tuple[str, str]]] = {
    # accent, gradient end per mode
    "indigo": {
        "dark": ("#A5B4FC", "#8B5CF6"),
        "light": ("#4F46E5", "#7C3AED"),
    },
    "ocean": {
        "dark": ("#67E8F9", "#3B82F6"),
        "light": ("#0891B2", "#2563EB"),
    },
    "rose": {
        "dark": ("#FDA4AF", "#F43F5E"),
        "light": ("#E11D48", "#DB2777"),
    },
    "amber": {
        "dark": ("#FCD34D", "#F97316"),
        "light": ("#B45309", "#EA580C"),
    },
}

ACCENT_LABELS = {
    "indigo": "インディゴ",
    "ocean": "オーシャン",
    "rose": "ローズ",
    "amber": "アンバー",
}

# Design tokens shared by widgets and pages.  Qt style sheets cannot animate
# transitions, so motion values live here and are applied by QPropertyAnimation
# in the shared widgets.  Keeping the numbers in one place makes every screen
# feel like part of the same product instead of a collection of local choices.
MOTION_FAST = 110
MOTION_BASE = 170
MOTION_SLOW = 260
EASING = QEasingCurve.OutCubic

RADIUS_SM = 8
RADIUS_MD = 10
RADIUS_LG = 14
RADIUS_XL = 16
RADIUS_PILL = 999

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 18
SPACE_XL = 26


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    a = QColor(color_a)
    b = QColor(color_b)
    r = round(a.red() * ratio + b.red() * (1 - ratio))
    g = round(a.green() * ratio + b.green() * (1 - ratio))
    bl = round(a.blue() * ratio + b.blue() * (1 - ratio))
    return QColor(r, g, bl).name()


def build_palette(mode: str, accent_name: str = "indigo") -> Palette:
    mode = "light" if mode == "light" else "dark"
    accent_name = accent_name if accent_name in ACCENTS else "indigo"
    accent, gradient_b = ACCENTS[accent_name][mode]
    if mode == "dark":
        bg = "#080C15"
        bg_elevated = "#0D1422"
        sidebar = "#0A101B"
        surface = "#101827"
        surface_alt = "#151F31"
        surface_hover = "#1B2739"
        card = "#0F1828"
        border = "#21304A"
        border_strong = "#34496A"
        text = "#F2F6FD"
        text_secondary = "#C8D3E5"
        text_muted = "#93A3BC"
        accent_soft = _mix(accent, bg, 0.16)
        accent_border = _mix(accent, bg, 0.45)
        gradient_a = "#5B5BD6" if accent_name == "indigo" else accent
        on_accent = "#FFFFFF"
        success = "#3DDC97"
        success_soft = _mix(success, bg, 0.14)
        warning = "#F7C65B"
        warning_soft = _mix(warning, bg, 0.14)
        danger = "#FF7A90"
        danger_soft = _mix(danger, bg, 0.14)
        info = "#74B9FF"
        info_soft = _mix(info, bg, 0.14)
        input_bg = "#0B1220"
        selection = _mix(accent, bg, 0.28)
        shadow = "#000000"
        overlay = "#05070C"
        nav_active = _mix(accent, bg, 0.14)
        pill_bg = "#172235"
        card_highlight = "#2A3D5C"
        input_bg_focus = "#0D1727"
    else:
        bg = "#F3F6FB"
        bg_elevated = "#FFFFFF"
        sidebar = "#FAFCFF"
        surface = "#FFFFFF"
        surface_alt = "#F3F6FC"
        surface_hover = "#E9EFF9"
        card = "#FFFFFF"
        border = "#DEE5F1"
        border_strong = "#BFCBE0"
        text = "#131D30"
        text_secondary = "#3B4A63"
        text_muted = "#5F6E86"
        accent_soft = _mix(accent, "#FFFFFF", 0.10)
        accent_border = _mix(accent, "#FFFFFF", 0.45)
        gradient_a = accent
        on_accent = "#FFFFFF"
        success = "#0E9F6E"
        success_soft = _mix(success, "#FFFFFF", 0.10)
        warning = "#B45309"
        warning_soft = _mix(warning, "#FFFFFF", 0.10)
        danger = "#D92D4E"
        danger_soft = _mix(danger, "#FFFFFF", 0.09)
        info = "#2563EB"
        info_soft = _mix(info, "#FFFFFF", 0.08)
        input_bg = "#F8FAFE"
        selection = _mix(accent, "#FFFFFF", 0.18)
        shadow = "#1C2A46"
        overlay = "#0B1220"
        nav_active = _mix(accent, "#FFFFFF", 0.10)
        pill_bg = "#EEF2FA"
        card_highlight = "#FFFFFF"
        input_bg_focus = "#FFFFFF"
    if accent_name == "indigo" and mode == "dark":
        gradient_a = "#6366F1"
        gradient_b = "#8B5CF6"
    return Palette(
        mode=mode,
        bg=bg,
        bg_elevated=bg_elevated,
        sidebar=sidebar,
        surface=surface,
        surface_alt=surface_alt,
        surface_hover=surface_hover,
        card=card,
        border=border,
        border_strong=border_strong,
        text=text,
        text_secondary=text_secondary,
        text_muted=text_muted,
        accent=accent,
        accent_strong=gradient_b,
        accent_soft=accent_soft,
        accent_border=accent_border,
        accent_text=accent,
        gradient_a=gradient_a,
        gradient_b=gradient_b,
        on_accent=on_accent,
        success=success,
        success_soft=success_soft,
        warning=warning,
        warning_soft=warning_soft,
        danger=danger,
        danger_soft=danger_soft,
        info=info,
        info_soft=info_soft,
        input_bg=input_bg,
        selection=selection,
        shadow=shadow,
        overlay=overlay,
        nav_active=nav_active,
        pill_bg=pill_bg,
        card_highlight=card_highlight,
        input_bg_focus=input_bg_focus,
    )


_current: Palette = build_palette("dark")
_asset_dir: Path | None = None
_animations_enabled = True


def current_palette() -> Palette:
    return _current


def animations_enabled() -> bool:
    return _animations_enabled


def set_animations_enabled(value: bool) -> None:
    global _animations_enabled
    _animations_enabled = bool(value)


_UI_FONT_CANDIDATES = (
    "Yu Gothic UI",
    "Meiryo UI",
    "Noto Sans JP",
    "Meiryo",
    "Segoe UI",
)

# Japanese system fonts usually draw U+005C as a yen sign.  File paths use a
# Latin-first stack so Windows paths keep their backslashes, while Japanese
# characters in the same path still fall back to the UI font.
_PATH_FONT_FAMILIES = (
    "Segoe UI",
    "Cascadia Mono",
    "Consolas",
    "Yu Gothic UI",
    "Meiryo UI",
    "Noto Sans JP",
)


def path_font(base: QFont | None = None) -> QFont:
    font = QFont(base) if base is not None else QFont()
    font.setFamilies(list(_PATH_FONT_FAMILIES))
    return font


def scaled_font(base: QFont, factor: float, weight=None) -> QFont:
    """Return a copy of *base* scaled relative to its current font size."""
    font = QFont(base)
    if base.pointSizeF() > 0:
        font.setPointSizeF(base.pointSizeF() * factor)
    elif base.pixelSize() > 0:
        font.setPixelSize(max(1, round(base.pixelSize() * factor)))
    if weight is not None:
        font.setWeight(weight)
    return font


def resolve_ui_font_family() -> str:
    """Return an installed UI font that contains Japanese glyphs.

    Segoe UI Variable is a good Latin font but has no Japanese coverage, so
    putting it first makes Qt fall back to another family for every Japanese
    character.  That mixes two typefaces inside a single label.  Prefer a
    Japanese-capable family and use the remaining fonts only as fallbacks.
    """
    available = set(QFontDatabase.families())
    japanese_families = set(QFontDatabase.families(QFontDatabase.WritingSystem.Japanese))
    for family in _UI_FONT_CANDIDATES:
        if family in available and family in japanese_families:
            return family
    for family in available:
        if family in japanese_families:
            return family
    return "Segoe UI"


def configure_font(app: QApplication) -> str:
    family = resolve_ui_font_family()
    fallbacks = [family, *_UI_FONT_CANDIDATES]
    font = QFont()
    font.setFamilies(list(dict.fromkeys(fallbacks)))
    font.setPointSizeF(10.0)
    font.setHintingPreference(QFont.PreferFullHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    return family


def _write_assets(directory: Path, palette: Palette) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    check = f"""<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">
<path d="M4 9.4l3.1 3.1L14.2 5.4" fill="none" stroke="{palette.on_accent}" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""
    chevron = f"""<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
<path d="M6 9l6 6 6-6" fill="none" stroke="{palette.text_muted}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""
    (directory / "check.svg").write_text(check, encoding="utf-8")
    (directory / "chevron.svg").write_text(chevron, encoding="utf-8")


def build_qt_palette(palette: Palette) -> QPalette:
    """Create the native palette used by tooltips and unstyled popups."""
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: palette.bg,
        QPalette.ColorRole.WindowText: palette.text,
        QPalette.ColorRole.Base: palette.surface,
        QPalette.ColorRole.AlternateBase: palette.surface_alt,
        QPalette.ColorRole.ToolTipBase: palette.surface,
        QPalette.ColorRole.ToolTipText: palette.text,
        QPalette.ColorRole.Text: palette.text,
        QPalette.ColorRole.Button: palette.surface_alt,
        QPalette.ColorRole.ButtonText: palette.text,
        QPalette.ColorRole.BrightText: palette.on_accent,
        QPalette.ColorRole.Light: palette.border_strong,
        QPalette.ColorRole.Midlight: palette.border_strong,
        QPalette.ColorRole.Mid: palette.border_strong,
        QPalette.ColorRole.Dark: palette.border,
        QPalette.ColorRole.Shadow: palette.shadow,
        QPalette.ColorRole.Highlight: palette.accent,
        QPalette.ColorRole.HighlightedText: palette.on_accent,
        QPalette.ColorRole.Link: palette.accent,
        QPalette.ColorRole.LinkVisited: palette.accent_strong,
        QPalette.ColorRole.PlaceholderText: palette.text_muted,
    }
    for role, color in roles.items():
        result.setColor(role, QColor(color))
    return result


def build_stylesheet(palette: Palette, asset_dir: Path, font_family: str | None = None) -> str:
    tokens = {key: value for key, value in palette.__dict__.items()}
    check_url = (asset_dir / "check.svg").as_posix()
    chevron_url = (asset_dir / "chevron.svg").as_posix()
    tokens["check_url"] = check_url
    tokens["chevron_url"] = chevron_url
    tokens["ui_font"] = font_family or resolve_ui_font_family()
    tokens["radius_sm"] = RADIUS_SM
    tokens["radius_md"] = RADIUS_MD
    tokens["radius_lg"] = RADIUS_LG
    tokens["radius_xl"] = RADIUS_XL
    tokens["space_sm"] = SPACE_SM
    tokens["space_md"] = SPACE_MD
    tokens["space_lg"] = SPACE_LG

    qss = """
* {
    text-decoration: none;
}
QWidget {
    color: @text;
    font-family: "@ui_font", "Yu Gothic UI", "Meiryo UI", "Noto Sans JP", "Segoe UI";
    font-size: 10pt;
}
QMainWindow {
    background-color: @bg;
}
QDialog {
    background-color: @bg_elevated;
}
QWidget#centralRoot {
    background-color: @bg;
}
QWidget#pageRoot {
    background-color: qlineargradient(x1:0, y1:0, x2:0.9, y2:1, stop:0 @bg, stop:0.62 @bg, stop:1 @bg_elevated);
}
QScrollArea#pageScroll, QWidget#scrollBody {
    background-color: transparent;
}
QFrame[role="sidebar"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 @sidebar, stop:1 @bg_elevated);
    border: none;
    border-right: 1px solid @border;
}
QFrame[role="topbar"] {
    background-color: @bg;
    border: none;
    border-bottom: 1px solid @border;
}
QWidget[role="activity"] {
    background-color: @accent_soft;
    border: 1px solid @accent_border;
    border-radius: 12px;
}
QWidget[role="activity"] QLabel {
    color: @accent;
    font-weight: 600;
}
QFrame[role="separator"] {
    background-color: @border;
    border: none;
    max-height: 1px;
    min-height: 1px;
}
QFrame[card="true"] {
    background-color: @card;
    border: 1px solid @border;
    border-top-color: @card_highlight;
    border-radius: 16px;
}
QFrame[card="true"][subtle="true"] {
    background-color: @surface_alt;
    border: 1px solid @border;
}
QFrame[role="statCard"] {
    background-color: @card;
    border: 1px solid @border;
    border-top-color: @card_highlight;
    border-radius: 14px;
}
QFrame[role="toast"] {
    background-color: @surface;
    border: 1px solid @border_strong;
    border-radius: 14px;
}
QFrame[role="stepper"] {
    background-color: @input_bg;
    border: 1px solid @border;
    border-radius: 10px;
}
QFrame[role="inset"] {
    background-color: @surface_alt;
    border: 1px solid @border;
    border-radius: 12px;
}
QFrame[role="detailBox"] {
    background-color: @surface_alt;
    border: 1px solid @border;
    border-radius: 10px;
}
QFrame[role="dialogIcon"] {
    background-color: @accent_soft;
    border: 1px solid @accent_border;
    border-radius: 20px;
}
QLabel[role="dialogIcon"] {
    background-color: @accent_soft;
    border: 1px solid @accent_border;
    border-radius: 20px;
}
QLabel[role="dialogIcon"][tone="danger"] {
    background-color: @danger_soft;
    border-color: @danger;
}
QLabel[role="featureIcon"] {
    background-color: @accent_soft;
    border: 1px solid @accent_border;
    border-radius: 10px;
}
QFrame[role="emptyIcon"] {
    background-color: @surface_alt;
    border: 1px solid @border;
    border-radius: 36px;
}
QFrame[role="banner"] {
    background-color: @accent_soft;
    border: 1px solid @accent_border;
    border-radius: 12px;
}
QFrame[role="errorBanner"] {
    background-color: @danger_soft;
    border: 1px solid @danger;
    border-radius: 14px;
}
QFrame[role="warningBanner"] {
    background-color: @warning_soft;
    border: 1px solid @warning;
    border-radius: 14px;
}
QFrame[role="successBanner"] {
    background-color: @success_soft;
    border: 1px solid @success;
    border-radius: 14px;
}
QFrame[role="infoBanner"] {
    background-color: @info_soft;
    border: 1px solid @info;
    border-radius: 14px;
}
QLabel {
    background: transparent;
}
QLabel[role="display"] {
    font-size: 24pt;
    font-weight: 700;
    color: @text;
}
QLabel[role="h1"] {
    font-size: 18pt;
    font-weight: 700;
}
QLabel[role="h2"] {
    font-size: 13.5pt;
    font-weight: 600;
}
QLabel[role="videoTitle"] {
    font-size: 15pt;
    font-weight: 600;
    color: @text;
}
QLabel[role="h3"] {
    font-size: 11pt;
    font-weight: 600;
}
QLabel[role="metric"] {
    font-size: 17pt;
    font-weight: 600;
    color: @text;
}
QLabel[role="muted"] {
    color: @text_muted;
}
QLabel[role="secondary"] {
    color: @text_secondary;
}
QLabel[role="caption"] {
    color: @text_muted;
    font-size: 9pt;
}
QLabel[role="eyebrow"] {
    color: @accent;
    font-size: 8.5pt;
    font-weight: 700;
}
QLabel[role="mono"] {
    font-family: "Cascadia Mono", "Consolas", "Courier New";
    font-size: 9pt;
    color: @text_secondary;
}
QLabel[path="true"] {
    font-family: "Segoe UI", "Cascadia Mono", "Consolas", "Yu Gothic UI", "Meiryo UI", "Noto Sans JP";
}
QLabel[role="danger"] { color: @danger; }
QLabel[role="success"] { color: @success; }
QLabel[role="warning"] { color: @warning; }
QLabel[role="accent"] { color: @accent; }
QLabel[role="pill"] {
    background-color: @pill_bg;
    border-radius: 8px;
    padding: 3px 8px;
    color: @text_secondary;
    font-size: 8.5pt;
    font-weight: 600;
}
QPushButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 8px 14px;
    color: @text_secondary;
    font-weight: 500;
}
QPushButton:hover {
    background-color: @surface_hover;
    color: @text;
}
QPushButton:pressed {
    background-color: @surface_alt;
}
QPushButton:focus {
    border: 1px solid @accent;
}
QPushButton:disabled {
    color: @text_muted;
    background-color: transparent;
}
QPushButton[variant="primary"] {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @gradient_a, stop:1 @gradient_b);
    color: @on_accent;
    border: 1px solid transparent;
    padding: 10px 18px;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent, stop:1 @gradient_a);
    color: @on_accent;
}
QPushButton[variant="primary"]:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent_strong, stop:1 @gradient_a);
}
QPushButton[variant="primary"]:focus {
    border: 2px solid @on_accent;
}
QPushButton[variant="primary"]:disabled {
    background-color: @surface_alt;
    color: @text_muted;
    border: 1px solid @border;
}
QPushButton[variant="secondary"] {
    background-color: @surface_alt;
    border: 1px solid @border;
    color: @text_secondary;
}
QPushButton[variant="secondary"]:hover {
    background-color: @surface_hover;
    border-color: @border_strong;
    color: @text;
}
QPushButton[variant="secondary"]:pressed {
    background-color: @surface_alt;
}
QPushButton[variant="secondary"]:focus {
    border-color: @accent;
}
QPushButton[variant="secondary"]:disabled {
    background-color: transparent;
    border-color: @border;
    color: @text_muted;
}
QPushButton[variant="ghost"] {
    background-color: transparent;
    color: @text_secondary;
    border: 1px solid transparent;
}
QPushButton[variant="ghost"]:hover {
    background-color: @surface_hover;
    color: @text;
}
QPushButton[variant="ghost"]:pressed {
    background-color: @surface_alt;
}
QPushButton[variant="ghost"]:disabled {
    background-color: transparent;
    color: @text_muted;
}
QPushButton[variant="link"] {
    background-color: transparent;
    border: 1px solid transparent;
    color: @accent;
    padding: 2px 0px;
    font-weight: 600;
    text-align: left;
}
QPushButton[variant="link"]:hover {
    background-color: transparent;
    color: @accent_strong;
}
QPushButton[variant="link"]:focus {
    border: 1px dotted @accent;
    border-radius: 4px;
}
QPushButton[variant="danger"] {
    background-color: @danger_soft;
    color: @danger;
    border: 1px solid transparent;
}
QPushButton[variant="danger"]:hover {
    background-color: @danger;
    color: @on_accent;
}
QPushButton[variant="danger"]:pressed {
    background-color: @danger;
    color: @on_accent;
}
QPushButton[variant="danger"]:focus {
    border: 1px solid @danger;
}
QPushButton[variant="danger"]:disabled {
    background-color: transparent;
    color: @text_muted;
    border-color: @border;
}
QPushButton[variant="nav"] {
    text-align: left;
    padding: 10px 12px 10px 9px;
    color: @text_secondary;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    border-radius: 10px;
    font-weight: 500;
}
QPushButton[variant="nav"]:hover {
    background-color: @surface_hover;
    color: @text;
}
QPushButton[variant="nav"]:checked {
    background-color: @nav_active;
    border-left-color: @accent;
    color: @text;
    font-weight: 600;
}
QPushButton[variant="nav"]:focus {
    border: 1px solid @accent;
    border-left: 3px solid @accent;
}
QPushButton[variant="chip"] {
    background-color: @surface_alt;
    border: 1px solid @border;
    border-radius: 14px;
    padding: 6px 12px;
    color: @text_secondary;
    font-size: 9pt;
}
QPushButton[variant="chip"]:hover {
    background-color: @surface_hover;
    border-color: @border_strong;
    color: @text;
}
QPushButton[variant="chip"]:pressed {
    background-color: @surface_alt;
}
QPushButton[variant="chip"]:checked {
    background-color: @accent_soft;
    border-color: @accent_border;
    color: @accent;
    font-weight: 600;
}
QPushButton[variant="chip"]:focus {
    border-color: @accent;
}
QPushButton[variant="segment"] {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 12px;
    color: @text_muted;
    font-size: 9.5pt;
}
QPushButton[variant="segment"]:hover {
    background-color: transparent;
    color: @text;
}
QPushButton[variant="segment"]:checked {
    color: @accent;
    font-weight: 600;
    background-color: transparent;
}
QPushButton[variant="segment"]:focus {
    border: 1px solid @accent;
}
QPushButton[variant="segment"][compact="true"] {
    padding: 4px 10px;
    font-size: 9.5pt;
}
QPushButton[role="icon"] {
    padding: 6px;
    border-radius: 9px;
}
QPushButton[role="icon"]:hover {
    background-color: @surface_hover;
}
QPushButton[role="icon"]:disabled {
    background-color: transparent;
}
QLineEdit, QPlainTextEdit, QTextEdit {
    background-color: @input_bg;
    border: 1px solid @border;
    border-radius: 10px;
    padding: 8px 12px;
    color: @text;
    selection-background-color: @selection;
    selection-color: @text;
}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {
    border-color: @border_strong;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid @accent;
    background-color: @input_bg_focus;
}
QLineEdit[invalid="true"] {
    border: 1px solid @danger;
}
QLineEdit#urlInput {
    background-color: @surface;
    border: 1px solid @border_strong;
    border-radius: 12px;
    padding: 12px 14px;
    font-size: 11pt;
}
QLineEdit#urlInput:hover {
    border-color: @border_strong;
}
QLineEdit#urlInput:focus {
    border: 1px solid @accent;
    background-color: @input_bg_focus;
}
QLineEdit#urlInput[dragActive="true"] {
    border: 1px dashed @accent;
    background-color: @accent_soft;
}
QLineEdit#urlInput[invalid="true"] {
    border: 1px solid @danger;
}
QPlainTextEdit#logView {
    font-family: "Cascadia Mono", "Consolas";
    font-size: 8.5pt;
    background-color: @input_bg;
    color: @text_secondary;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: @border_strong;
    min-height: 30px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: @text_muted;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: @border_strong;
    min-width: 30px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal:hover {
    background: @text_muted;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QTableView, QTableWidget {
    background-color: transparent;
    border: none;
    gridline-color: transparent;
    alternate-background-color: @surface_alt;
    selection-background-color: @accent_soft;
    selection-color: @text;
}
QTableView::item, QTableWidget::item {
    padding: 8px;
    border: none;
    border-bottom: 1px solid @border;
}
QTableView::item:selected, QTableWidget::item:selected {
    background-color: @accent_soft;
    color: @text;
}
QTableView::indicator, QTableWidget::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid @border_strong;
    border-radius: 5px;
    background-color: @input_bg;
}
QTableView::indicator:checked, QTableWidget::indicator:checked {
    background-color: @accent;
    border-color: @accent;
    image: url("@check_url");
}
QHeaderView {
    background-color: transparent;
}
QHeaderView::section {
    background-color: transparent;
    color: @text_muted;
    border: none;
    border-bottom: 1px solid @border;
    padding: 8px;
    font-size: 9pt;
    font-weight: 600;
}
QTableCornerButton::section {
    background-color: transparent;
    border: none;
}
QCheckBox {
    spacing: 8px;
    color: @text_secondary;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid @border_strong;
    border-radius: 5px;
    background-color: @input_bg;
}
QCheckBox::indicator:hover {
    border-color: @accent;
}
QCheckBox::indicator:checked {
    background-color: @accent;
    border-color: @accent;
    image: url("@check_url");
}
QCheckBox::indicator:focus {
    border: 1px solid @accent;
}
QRadioButton {
    spacing: 8px;
    color: @text_secondary;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid @border_strong;
    background-color: @input_bg;
}
QRadioButton::indicator:checked {
    background-color: @accent;
    border: 4px solid @input_bg;
}
QSlider::groove:horizontal {
    height: 4px;
    background: @surface_alt;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: @accent;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: @accent;
}
QSlider::handle:horizontal:hover {
    background: @accent_strong;
}
QProgressBar {
    background-color: @surface_alt;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    border-radius: 4px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @gradient_a, stop:1 @gradient_b);
}
QToolTip {
    background-color: @surface;
    color: @text;
    border: 1px solid @border_strong;
    border-radius: 8px;
    padding: 6px 9px;
}
QMenu {
    background-color: @surface;
    border: 1px solid @border;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 26px 7px 12px;
    border-radius: 6px;
    color: @text_secondary;
}
QMenu::item:selected {
    background-color: @accent_soft;
    color: @text;
}
QMenu::item:disabled {
    color: @text_muted;
}
QMenu::separator {
    height: 1px;
    background-color: @border;
    margin: 4px 8px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px;
    color: @text_secondary;
}
QToolButton:hover {
    background-color: @surface_hover;
    color: @text;
}
QToolButton:focus {
    border: 1px solid @accent;
}
QToolButton:checked {
    background-color: @accent_soft;
    color: @accent;
}
QListView {
    background: transparent;
    border: none;
    outline: none;
}
QMessageBox {
    background-color: @surface;
}
QDialogButtonBox QPushButton {
    min-width: 92px;
}
QComboBox {
    background-color: @input_bg;
    border: 1px solid @border;
    border-radius: 10px;
    padding: 8px 12px;
}
QComboBox:hover {
    border-color: @border_strong;
}
QComboBox:focus {
    border-color: @accent;
}
QComboBox::drop-down {
    border: none;
    width: 26px;
}
QComboBox::down-arrow {
    image: url("@chevron_url");
    width: 14px;
    height: 14px;
}
QComboBox QAbstractItemView {
    background-color: @surface;
    border: 1px solid @border;
    border-radius: 8px;
    selection-background-color: @accent_soft;
    selection-color: @text;
    padding: 4px;
}
"""
    for key in sorted(tokens, key=len, reverse=True):
        qss = qss.replace(f"@{key}", str(tokens[key]))
    return qss


def _apply_native_titlebar(widget: QWidget, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:
        pass


class ThemeManager(QObject):
    changed = Signal(object)
    mode_resolved = Signal(str)

    def __init__(self, app: QApplication, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        global _asset_dir
        self._app = app
        self._cache_dir = Path(cache_dir)
        self._configured_mode = "dark"
        self._accent = "indigo"
        self._animations = True
        self._palette = build_palette("dark")
        self._font_family = configure_font(self._app)
        # QToolTip owns a separate font and does not reliably inherit the
        # application font, so Japanese tooltip text can otherwise turn into
        # replacement glyphs.
        QToolTip.setFont(self._app.font())
        # The runtime calls apply() immediately after construction.  Building
        # and installing the full application stylesheet here as well would
        # force Qt to re-polish every widget twice during startup.
        _asset_dir = self._cache_dir / "ui"
        self._applied_once = False
        try:
            self._app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except AttributeError:
            pass

    @property
    def palette(self) -> Palette:
        return self._palette

    @property
    def animations(self) -> bool:
        return self._animations

    def set_animations(self, animations: bool) -> None:
        """Update the animation preference without rebuilding the theme."""
        self._animations = bool(animations)
        set_animations_enabled(animations)

    def apply(self, mode: str, accent: str, animations: bool = True) -> None:
        global _current, _asset_dir
        self._configured_mode = mode
        self._accent = accent
        self._animations = animations
        set_animations_enabled(animations)
        resolved = self._resolve(mode)
        palette = build_palette(resolved, accent)
        _current = palette
        _asset_dir = self._cache_dir / "ui"
        _write_assets(_asset_dir, palette)
        stylesheet = build_stylesheet(palette, _asset_dir, self._font_family)
        # QToolTip reuses its hidden label for repeated identical text and
        # keeps the old background.  Drop cached tip labels so the next hover
        # is created with the new palette.
        for widget in self._app.topLevelWidgets():
            if widget.windowType() == Qt.WindowType.ToolTip:
                widget.hide()
                widget.deleteLater()
        qt_palette = build_qt_palette(palette)
        self._app.setPalette(qt_palette)
        # QToolTip is a transient native top-level label.  Its palette can be
        # updated cheaply and follows the theme even when only window-level
        # style sheets are re-applied.  QToolTip paints its background with the
        # Window role, so use the card surface here to preserve the original
        # tooltip design.
        tooltip_palette = build_qt_palette(palette)
        tooltip_palette.setColor(QPalette.ColorRole.Window, QColor(palette.surface))
        QToolTip.setPalette(tooltip_palette)
        if not self._applied_once:
            self._app.setStyleSheet(stylesheet)
            self._applied_once = True
        else:
            self._apply_window_styles(stylesheet)
        self._palette = palette
        for widget in self._app.topLevelWidgets():
            if isinstance(widget, QWidget) and widget.isVisible():
                _apply_native_titlebar(widget, palette.is_dark)
        self.mode_resolved.emit(resolved)
        self.changed.emit(palette)

    def _apply_window_styles(self, stylesheet: str) -> None:
        """Re-polish open windows without invalidating every Qt widget.

        QApplication.setStyleSheet() walks the whole application and costs
        roughly 200 ms once the main window is populated.  The main window and
        its child dialogs/menus share the same style tree, so applying the new
        sheet there updates the visible UI in a fraction of the time.
        """
        targets = [
            widget
            for widget in self._app.topLevelWidgets()
            if isinstance(widget, (QMainWindow, QDialog))
        ]
        if targets:
            for widget in targets:
                widget.setStyleSheet(stylesheet)
        else:
            # No main window yet (or only transient popups): keep the global
            # sheet coherent for any window created next.
            self._app.setStyleSheet(stylesheet)

    def _resolve(self, mode: str) -> str:
        if mode in ("dark", "light"):
            return mode
        try:
            scheme = self._app.styleHints().colorScheme()
            return "dark" if scheme == Qt.ColorScheme.Dark else "light"
        except Exception:
            return "dark"

    def _on_system_scheme_changed(self, _scheme) -> None:
        if self._configured_mode == "system":
            self.apply("system", self._accent, self._animations)


def apply_window_theme(widget: QWidget) -> None:
    _apply_native_titlebar(widget, current_palette().is_dark)
