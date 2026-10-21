from __future__ import annotations

from PySide6.QtCore import QByteArray, QPoint, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygon,
)
from PySide6.QtSvg import QSvgRenderer

from .theme import current_palette

_PATHS: dict[str, str] = {
    "home": '<path d="M3 10.2L12 3l9 7.2"/><path d="M5.5 8.8V21h13V8.8"/><path d="M9.5 21v-6h5v6"/>',
    "download": '<path d="M12 3v12"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M4 17v3h16v-3"/>',
    "download-cloud": '<path d="M7 17H5.5A3.5 3.5 0 0 1 5 10a6 6 0 0 1 11.6-1.4A4 4 0 0 1 18 17h-1.5"/><path d="M12 11v8"/><path d="M8.8 15.8L12 19l3.2-3.2"/>',
    "queue": '<path d="M4 6h16"/><path d="M4 12h10"/><path d="M4 18h7"/><path d="M17 15v6"/><path d="M14 18h6"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4.5V10H9"/><path d="M12 7.5V12l3 2"/>',
    "settings": '<path d="M4 6h9"/><path d="M17 6h3"/><circle cx="15" cy="6" r="2"/><path d="M4 12h3"/><path d="M11 12h9"/><circle cx="9" cy="12" r="2"/><path d="M4 18h11"/><path d="M19 18h1"/><circle cx="17" cy="18" r="2"/>',
    "diagnostics": '<path d="M3 12h4l2-5 3.5 10L15 9l1.8 3H21"/>',
    "link": '<path d="M10 13.5a4.5 4.5 0 0 0 6.4 0l2.1-2.1a4.5 4.5 0 0 0-6.4-6.4L10.8 6.3"/><path d="M14 10.5a4.5 4.5 0 0 0-6.4 0l-2.1 2.1a4.5 4.5 0 0 0 6.4 6.4l1.3-1.3"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2.8h6V4"/><path d="M8.5 10h7"/><path d="M8.5 14h7"/><path d="M8.5 18h4"/>',
    "clipboard-check": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2.8h6V4"/><path d="M8.5 13l2.4 2.4L16 10.8"/>',
    "x": '<path d="M6 6l12 12"/><path d="M18 6L6 18"/>',
    "x-circle": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6"/><path d="M15 9l-6 6"/>',
    "arrow-right": '<path d="M4 12h15"/><path d="M14 7l5 5-5 5"/>',
    "arrow-left": '<path d="M20 12H5"/><path d="M10 7l-5 5 5 5"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M6 15l6-6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "folder": '<path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4l2 2.5h8A1.5 1.5 0 0 1 20.5 9v9A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18z"/>',
    "folder-open": '<path d="M3.5 7A1.5 1.5 0 0 1 5 5.5h4l2 2.5h7.5A1.5 1.5 0 0 1 20 9.5v1"/><path d="M3.5 9h18l-2 10.5h-16z"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4.5h6V7"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v5"/><path d="M14 11v5"/>',
    "play": '<path d="M8 5.5l11 6.5-11 6.5z"/>',
    "pause": '<path d="M8.5 5v14"/><path d="M15.5 5v14"/>',
    "retry": '<path d="M20 11a8 8 0 1 0-2.3 6.3"/><path d="M20 4.5V11h-6.5"/>',
    "check": '<path d="M4.5 12.5l5 5L20 6.5"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.4l2.7 2.7L16.4 9"/>',
    "alert-triangle": '<path d="M12 3.5L21 20H3z"/><path d="M12 9v5"/><path d="M12 17.2v.1"/>',
    "alert-circle": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.5v.1"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.5v.1"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.3 15.3L21 21"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5.5H4.5V6H10"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 6.3"/><path d="M20 4.5V11h-6.5"/>',
    "plus": '<path d="M12 4v16"/><path d="M4 12h16"/>',
    "minus": '<path d="M4 12h16"/>',
    "music": '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    "video": '<rect x="3" y="5.5" width="13" height="13" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16"/><path d="M17 4v16"/><path d="M3 9h4"/><path d="M3 15h4"/><path d="M17 9h4"/><path d="M17 15h4"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.4 2.4 4.6-4.8"/>',
    "terminal": '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M13 15h4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5"/>',
    "zap": '<path d="M13 3L4.5 14H11l-1 7 9-12h-6z"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3.5 9h17"/><path d="M3.5 15h17"/><path d="M12 3c3 3.2 3 14.8 0 18"/><path d="M12 3c-3 3.2-3 14.8 0 18"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 16l9 5 9-5"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "sparkles": '<path d="M12 3l1.7 4.8L18.5 9.5l-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7z"/><path d="M18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "database": '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4.2 1.8c-.9.8-1.7 1.3-1.7 2.7"/><path d="M12 17v.1"/>',
    "command": '<path d="M8 8a3 3 0 1 1-3-3 3 3 0 0 1 3 3z"/><path d="M16 8a3 3 0 1 0 3-3 3 3 0 0 0-3 3z"/><path d="M8 16a3 3 0 1 0-3 3 3 3 0 0 0 3-3z"/><path d="M16 16a3 3 0 1 1 3 3 3 3 0 0 1-3-3z"/><rect x="8" y="8" width="8" height="8"/>',
    "wifi": '<path d="M3 9a14 14 0 0 1 18 0"/><path d="M6 12.5a9.5 9.5 0 0 1 12 0"/><path d="M9 16a5 5 0 0 1 6 0"/><path d="M12 19.5v.1"/>',
    "lock": '<rect x="4.5" y="10" width="15" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "palette": '<path d="M12 3a9 9 0 0 0 0 18c1.4 0 2-1 2-2 0-1.4 1-2 2-2h2a3 3 0 0 0 3-3A9 9 0 0 0 12 3z"/><circle cx="8" cy="9" r="1"/><circle cx="12" cy="7" r="1"/><circle cx="16" cy="9" r="1"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2"/><path d="M12 19.5v2"/><path d="M2.5 12h2"/><path d="M19.5 12h2"/><path d="M5.3 5.3l1.4 1.4"/><path d="M17.3 17.3l1.4 1.4"/><path d="M18.7 5.3l-1.4 1.4"/><path d="M6.7 17.3l-1.4 1.4"/>',
    "moon": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
    "monitor": '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M8 20h8"/><path d="M12 16.5V20"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.3 2"/>',
    "list": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3.5 6h.1"/><path d="M3.5 12h.1"/><path d="M3.5 18h.1"/>',
    "upload": '<path d="M12 21V9"/><path d="M7.5 13.5L12 9l4.5 4.5"/><path d="M4 4h16"/>',
    "filter": '<path d="M3 5h18"/><path d="M6 12h12"/><path d="M10 19h4"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.1"/><path d="M10 10h.1"/><path d="M14 10h.1"/><path d="M18 10h.1"/><path d="M7 14h10"/>',
    "power": '<path d="M12 3v9"/><path d="M6.5 6.5a8 8 0 1 0 11 0"/>',
    "rotate-ccw": '<path d="M4 11a8 8 0 1 1 2.3 6.3"/><path d="M4 4.5V11h6.5"/>',
    "heart": '<path d="M12 20s-8-4.8-8-10a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.2-8 10-8 10z"/>',
}


def _svg(name: str, color: str, stroke: float, filled: bool = False) -> bytes:
    body = _PATHS.get(name, _PATHS["info"])
    fill = color if filled else "none"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="{fill}" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode("utf-8")


_icon_cache: dict[tuple[str, str, int, float], QIcon] = {}


def icon(name: str, color: str | None = None, size: int = 20, stroke: float = 1.8) -> QIcon:
    palette = current_palette()
    color = color or palette.text_secondary
    key = (name, color, size, stroke)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke, filled=name == "play")))
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    result = QIcon(pixmap)
    if len(_icon_cache) > 512:
        _icon_cache.clear()
    _icon_cache[key] = result
    return result


def logo_pixmap(size: int = 44) -> QPixmap:
    palette = current_palette()
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor(palette.gradient_a))
    gradient.setColorAt(1, QColor(palette.gradient_b))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    painter.fillPath(path, gradient)
    painter.setPen(QPen(QColor("#FFFFFF"), max(2.0, size * 0.07), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    w = size
    painter.drawLine(int(w * 0.5), int(w * 0.25), int(w * 0.5), int(w * 0.62))
    painter.drawPolyline(
        QPolygon(
            [
                QPoint(int(w * 0.31), int(w * 0.45)),
                QPoint(int(w * 0.5), int(w * 0.64)),
                QPoint(int(w * 0.69), int(w * 0.45)),
            ]
        )
    )
    painter.drawLine(int(w * 0.3), int(w * 0.76), int(w * 0.7), int(w * 0.76))
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    result = QIcon()
    for size in sizes:
        result.addPixmap(logo_pixmap(size))
    return result
