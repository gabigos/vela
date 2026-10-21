from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from .icons import icon
from .theme import (
    EASING,
    MOTION_BASE,
    MOTION_FAST,
    animations_enabled,
    current_palette,
)


class MotionButton(QPushButton):
    """QPushButton with a cheap, smooth hover/press tint.

    Qt style sheets have no transition support, so swapping :hover colours
    snaps.  This subclass paints a translucent overlay after the normal style
    and animates its strength.  It does not change geometry, so layouts never
    jump, and only two property animations exist per button.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._hover_progress = 0.0
        self._press_progress = 0.0
        self._hover_animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setDuration(MOTION_FAST)
        self._hover_animation.setEasingCurve(EASING)
        self._press_animation = QPropertyAnimation(self, b"pressProgress", self)
        self._press_animation.setDuration(90)
        self._press_animation.setEasingCurve(EASING)
        self.setAttribute(Qt.WA_Hover, True)

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float) -> None:
        self._hover_progress = value
        self.update()

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)

    def _get_press_progress(self) -> float:
        return self._press_progress

    def _set_press_progress(self, value: float) -> None:
        self._press_progress = value
        self.update()

    pressProgress = Property(float, _get_press_progress, _set_press_progress)

    def _animate_hover(self, target: float) -> None:
        self._hover_animation.stop()
        if not animations_enabled() or not self.isEnabled():
            self._set_hover_progress(target)
            return
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def _animate_press(self, target: float) -> None:
        self._press_animation.stop()
        if not animations_enabled() or not self.isEnabled():
            self._set_press_progress(target)
            return
        self._press_animation.setStartValue(self._press_progress)
        self._press_animation.setEndValue(target)
        self._press_animation.start()

    def _motion_radius(self) -> int:
        if self.property("role") == "icon":
            return 9
        variant = self.property("variant")
        if variant == "chip":
            return 14
        if variant == "segment":
            return 8
        if variant == "link":
            return 4
        return 10

    def enterEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled():
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_hover(0.0)
        self._animate_press(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.isEnabled():
            self._animate_press(1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._animate_press(0.0)
        super().mouseReleaseEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange and not self.isEnabled():
            self._hover_animation.stop()
            self._press_animation.stop()
            self._hover_progress = 0.0
            self._press_progress = 0.0
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        strength = 0.045 * self._hover_progress + 0.085 * self._press_progress
        if strength <= 0.001:
            return
        radius = self._motion_radius()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
        )
        painter.setClipPath(path)
        tint = QColor(current_palette().text)
        tint.setAlphaF(min(0.14, strength))
        painter.fillRect(self.rect(), tint)
        painter.end()


def fade_in(widget: QWidget, *, duration: int = MOTION_BASE) -> None:
    """Fade a widget in without touching its layout geometry.

    The effect is removed as soon as the animation finishes so the page is
    composited normally afterwards.  Nested or repeated calls are ignored
    while an effect is active, which prevents animation pile-ups when the
    user triggers the same state change repeatedly.
    """
    if not animations_enabled() or widget.graphicsEffect() is not None:
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(EASING)

    def _finish() -> None:
        if isValid(widget):
            widget.setGraphicsEffect(None)

    animation.finished.connect(_finish)
    animation.start()
    widget._fade_animation = animation  # type: ignore[attr-defined]



def set_variant(widget: QWidget, variant: str) -> None:
    widget.setProperty("variant", variant)
    refresh_style(widget)


def set_role(widget: QWidget, role: str) -> None:
    widget.setProperty("role", role)
    refresh_style(widget)


def refresh_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def make_button(
    text: str,
    variant: str = "secondary",
    *,
    icon_name: str | None = None,
    parent: QWidget | None = None,
    tooltip: str = "",
) -> QPushButton:
    button = MotionButton(text, parent)
    button.setProperty("variant", variant)
    button.setCursor(Qt.PointingHandCursor)
    if icon_name:
        set_named_icon(button, icon_name, color=_button_icon_role(variant), size=17)
    if tooltip:
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
    elif text:
        button.setAccessibleName(text)
    return button


def _button_icon_role(variant: str) -> str:
    if variant == "primary":
        return "on_accent"
    if variant == "danger":
        return "danger"
    return "secondary"


def make_icon_button(
    icon_name: str,
    tooltip: str,
    *,
    size: int = 18,
    color: str | None = None,
    parent: QWidget | None = None,
) -> QPushButton:
    button = MotionButton(parent)
    button.setProperty("role", "icon")
    set_named_icon(button, icon_name, color=color, size=size)
    button.setFixedSize(34, 34)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    return button


def add_shadow(widget: QWidget, *, blur: int = 28, alpha: int = 70, y_offset: int = 8) -> None:
    if not animations_enabled():
        return
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    color = QColor(current_palette().shadow)
    color.setAlpha(alpha)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, subtle: bool = False) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        if subtle:
            self.setProperty("subtle", True)

    def set_layout(self, layout: QLayout) -> None:
        self.setLayout(layout)


class ElidedLabel(QLabel):
    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        mode: Qt.TextElideMode = Qt.ElideRight,
    ) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elide()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        metrics = QFontMetrics(self.font())
        available = max(20, self.width() - 2)
        elided = metrics.elidedText(self._full_text, self._mode, available)
        super().setText(elided)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            widget = item.widget()
            # Use isHidden() instead of isVisible(): while this layout's
            # parent is hidden (for example the home hero during a result
            # view), children also report isVisible() == False.  Treating
            # them as hidden makes heightForWidth() return 0 and Qt caches
            # that height, leaving the chips clipped when the hero returns.
            if widget is not None and widget.isHidden():
                continue
            width = item.sizeHint().width()
            height = item.sizeHint().height()
            if x + width > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y += line_height + self._spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x += width + self._spacing
            line_height = max(line_height, height)
        return y + line_height - rect.y() + margins.bottom()


class SegmentedControl(QWidget):
    changed = Signal(str)

    def __init__(
        self,
        items: Iterable[tuple[str, str]],
        value: str | None = None,
        *,
        parent: QWidget | None = None,
        icon_names: dict[str, str] | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._values = [item[0] for item in self._items]
        self._icon_names = icon_names or {}
        self._buttons: dict[str, QPushButton] = {}
        self._indicator = QRectF()
        self._animation = QPropertyAnimation(self, b"indicatorRect", self)
        self._animation.setDuration(MOTION_BASE)
        self._animation.setEasingCurve(EASING)
        # Own the single-shot timer instead of using QTimer.singleShot():
        # result cards are destroyed and rebuilt frequently, and the timer
        # must be cancelled with this control before its buttons disappear.
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_indicator)
        self._initialised = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, label in self._items:
            button = MotionButton(label, self)
            button.setCheckable(True)
            button.setProperty("variant", "segment")
            button.setProperty("compact", "true" if compact else "false")
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setAccessibleName(label)
            icon_name = self._icon_names.get(key)
            if icon_name:
                set_named_icon(button, icon_name, color="muted", size=15)
            button.clicked.connect(lambda _checked=False, key=key: self.set_value(key, emit=True))
            button.installEventFilter(self)
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button, 1)
        # Let the buttons' real size hints (font metrics + QSS padding)
        # determine the control height.  A fixed height clips Japanese text
        # whenever the font is larger than the one used during development.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        selected = value if value in self._buttons else self._values[0]
        self._selected = selected
        self._buttons[selected].setChecked(True)
        self._sync_timer.start(0)

    def selected(self) -> str:
        return self._selected

    def set_value(self, value: str, *, emit: bool = False, animate: bool = True) -> None:
        if not isValid(self) or value not in self._buttons:
            return
        button = self._buttons[value]
        if not isValid(button):
            return
        changed = value != self._selected
        if not changed:
            # Programmatic settings syncs often call set_value() with the
            # value that is already selected.  Do not cancel an in-flight
            # indicator animation in that case.
            if (
                isValid(self._animation)
                and self._animation.state() == QAbstractAnimation.State.Stopped
            ):
                self._move_indicator(animate=False)
            return
        self._selected = value
        button.setChecked(True)
        self._move_indicator(animate=animate)
        if emit:
            self.changed.emit(value)

    def _sync_indicator(self) -> None:
        if isValid(self):
            self._move_indicator(animate=False)

    def _move_indicator(self, *, animate: bool) -> None:
        if not isValid(self) or not isValid(self._animation):
            return
        button = self._buttons.get(self._selected)
        if button is None or not isValid(button):
            return
        target = QRectF(button.geometry()).adjusted(0, 0, 0, 0)
        self._animation.stop()
        if not self._indicator.isValid() or not self._initialised:
            self._indicator = target
            self._initialised = True
            self.update()
            return
        if not animate or not animations_enabled():
            self._indicator = target
            self.update()
            return
        self._animation.setStartValue(self._indicator)
        self._animation.setEndValue(target)
        self._animation.start()

    def _get_indicator(self) -> QRectF:
        return self._indicator

    def _set_indicator(self, rect: QRectF) -> None:
        self._indicator = rect
        self.update()

    indicatorRect = Property(QRectF, _get_indicator, _set_indicator)

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.setBrush(QColor(palette.surface_alt))
        painter.drawRoundedRect(track, 10, 10)
        if self._indicator.isValid():
            painter.setPen(QPen(QColor(palette.accent_border), 1))
            painter.setBrush(QColor(palette.accent_soft))
            painter.drawRoundedRect(self._indicator.adjusted(1, 1, -1, -1), 8, 8)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._move_indicator(animate=False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_timer.start(0)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                index = self._values.index(self._selected)
                delta = -1 if event.key() in (Qt.Key_Left, Qt.Key_Up) else 1
                new_index = max(0, min(len(self._values) - 1, index + delta))
                value = self._values[new_index]
                self.set_value(value, emit=True)
                self._buttons[value].setFocus(Qt.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def refresh_theme(self) -> None:
        for key, button in self._buttons.items():
            icon_name = self._icon_names.get(key)
            if icon_name:
                set_named_icon(
                    button,
                    icon_name,
                    color="accent" if key == self._selected else "muted",
                    size=16,
                )
        self.update()


class Switch(QAbstractButton):
    def __init__(self, parent: QWidget | None = None, *, checked: bool = False) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._offset = 1.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(MOTION_FAST)
        self._animation.setEasingCurve(EASING)
        self.toggled.connect(self._animate)
        self.setFixedSize(46, 26)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(46, 26)

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        # Settings pages sync the switch inside blockSignals(True), so toggled()
        # never fires and the knob would keep its old offset.  Snap it into
        # place then, otherwise the first later click acts on a stale visual.
        if not self.signalsBlocked():
            return
        animation = getattr(self, "_animation", None)
        if animation is not None and isValid(animation):
            animation.stop()
        self._offset = 1.0 if checked else 0.0
        self.update()

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        self._animation.stop()
        if not animations_enabled():
            self._offset = target
            self.update()
            return
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(target)
        self._animation.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        track = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(palette.accent))
        else:
            painter.setPen(QPen(QColor(palette.border_strong), 1))
            painter.setBrush(QColor(palette.input_bg))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = 18
        x = 4 + (self.width() - 8 - diameter) * self._offset
        knob = QRectF(x, (self.height() - diameter) / 2, diameter, diameter)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(knob)
        if self.hasFocus():
            painter.setPen(QPen(QColor(palette.accent), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), 13, 13)
        painter.end()


class Stepper(QWidget):
    valueChanged = Signal(int)

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        *,
        step: int = 1,
        suffix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._value = max(minimum, min(maximum, value))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        box = QFrame(self)
        box.setProperty("role", "stepper")
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(3, 2, 3, 2)
        box_layout.setSpacing(2)
        self._minus = make_icon_button("minus", "減らす", size=14, parent=box)
        self._minus.setFixedSize(28, 28)
        self._value_label = QLabel(str(value), box)
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setMinimumWidth(34)
        self._value_label.setProperty("role", "secondary")
        self._plus = make_icon_button("plus", "増やす", size=14, parent=box)
        self._plus.setFixedSize(28, 28)
        box_layout.addWidget(self._minus)
        box_layout.addWidget(self._value_label)
        box_layout.addWidget(self._plus)
        layout.addWidget(box)
        if suffix:
            suffix_label = QLabel(suffix, self)
            suffix_label.setProperty("role", "caption")
            layout.addSpacing(6)
            layout.addWidget(suffix_label)
        layout.addStretch(1)
        self._minus.clicked.connect(lambda: self._change(-self._step))
        self._plus.clicked.connect(lambda: self._change(self._step))
        self._update_buttons()
        self.setAccessibleName("数値設定")

    def value(self) -> int:
        return self._value

    def set_value(self, value: int, *, emit: bool = False) -> None:
        value = max(self._minimum, min(self._maximum, value))
        if value == self._value:
            return
        self._value = value
        self._value_label.setText(str(value))
        self._update_buttons()
        if emit:
            self.valueChanged.emit(value)

    def _change(self, delta: int) -> None:
        self.set_value(self._value + delta, emit=True)

    def _update_buttons(self) -> None:
        self._minus.setEnabled(self._value > self._minimum)
        self._plus.setEnabled(self._value < self._maximum)


class Spinner(QWidget):
    def __init__(self, parent: QWidget | None = None, *, size: int = 22, color: str | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._color = color
        self._running = False
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if animations_enabled():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self.update()

    def is_running(self) -> bool:
        return self._running

    def _tick(self) -> None:
        # 16 ms gives a 60 fps rotation; keep roughly the same angular speed
        # as the previous 35 ms / 9 degree step.
        self._angle = (self._angle + 4.2) % 360
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._running and animations_enabled():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = current_palette()
        color = QColor(self._color or palette.accent)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor(palette.border), 2.2))
        painter.drawArc(rect, 0, 5760)
        pen = QPen(color, 2.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, int(self._angle * 16), 100 * 16)
        painter.end()


class MessageBanner(QFrame):
    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "infoBanner")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(12)
        self._icon = QLabel(self)
        self._icon.setFixedSize(22, 22)
        self._layout.addWidget(self._icon, 0, Qt.AlignTop)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        self._title = QLabel(self)
        self._title.setProperty("role", "h3")
        self._title.setWordWrap(True)
        self._body = QLabel(self)
        self._body.setProperty("role", "secondary")
        self._body.setWordWrap(True)
        self._remedy = QLabel(self)
        self._remedy.setProperty("role", "caption")
        for label in (self._title, self._body, self._remedy):
            # Error messages and remedies embed titles and file paths from
            # external sources, so show them literally.
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._remedy.setWordWrap(True)
        text_layout.addWidget(self._title)
        text_layout.addWidget(self._body)
        text_layout.addWidget(self._remedy)
        self._layout.addLayout(text_layout, 1)
        self._action = make_button("ログを開く", "secondary", icon_name="terminal", parent=self)
        self._action.clicked.connect(self.action_clicked.emit)
        self._layout.addWidget(self._action, 0, Qt.AlignTop)
        self.hide()

    def set_action(self, text: str, icon_name: str = "terminal") -> None:
        self._action.setText(text)
        self._action.setVisible(bool(text))
        set_named_icon(self._action, icon_name, color="secondary", size=16)

    def show_message(
        self,
        kind: str,
        title: str,
        body: str,
        remedy: str = "",
        action_text: str = "",
    ) -> None:
        role = {
            "error": "errorBanner",
            "warning": "warningBanner",
            "success": "successBanner",
            "info": "infoBanner",
        }.get(kind, "infoBanner")
        self.setProperty("role", role)
        refresh_style(self)
        palette = current_palette()
        colors = {
            "error": (palette.danger, "alert-circle"),
            "warning": (palette.warning, "alert-triangle"),
            "success": (palette.success, "check-circle"),
            "info": (palette.info, "info"),
        }
        color, icon_name = colors.get(kind, colors["info"])
        self._icon.setPixmap(icon(icon_name, color, 22).pixmap(22, 22))
        self._title.setText(title)
        self._body.setText(body)
        self._body.setProperty("path", "\\" in body)
        refresh_style(self._body)
        self._body.setVisible(bool(body))
        self._remedy.setText(remedy)
        self._remedy.setProperty("path", "\\" in remedy)
        refresh_style(self._remedy)
        self._remedy.setVisible(bool(remedy))
        self._action.setVisible(bool(action_text))
        if action_text:
            self.set_action(action_text)
        self.show()
        fade_in(self, duration=160)


class EmptyState(QWidget):
    action_clicked = Signal()

    def __init__(
        self,
        icon_name: str,
        title: str,
        description: str,
        *,
        action_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 48, 24, 48)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignCenter)
        circle = QFrame(self)
        circle.setFixedSize(72, 72)
        circle.setProperty("role", "emptyIcon")
        circle_layout = QVBoxLayout(circle)
        circle_layout.setContentsMargins(0, 0, 0, 0)
        self._icon_name = icon_name
        self._icon = QLabel(circle)
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setPixmap(icon(icon_name, current_palette().text_muted, 30).pixmap(30, 30))
        circle_layout.addWidget(self._icon)
        layout.addWidget(circle, 0, Qt.AlignHCenter)
        self._title = QLabel(title, self)
        self._title.setProperty("role", "h2")
        self._title.setAlignment(Qt.AlignCenter)
        self._description = QLabel(description, self)
        self._description.setProperty("role", "muted")
        self._description.setWordWrap(True)
        self._description.setAlignment(Qt.AlignCenter)
        self._description.setMaximumWidth(460)
        layout.addWidget(self._title)
        layout.addWidget(self._description, 0, Qt.AlignHCenter)
        self._action = make_button(action_text, "primary", icon_name="plus", parent=self)
        self._action.clicked.connect(self.action_clicked.emit)
        self._action.setVisible(bool(action_text))
        layout.addSpacing(6)
        layout.addWidget(self._action, 0, Qt.AlignHCenter)

    def refresh_theme(self) -> None:
        self._icon.setPixmap(
            icon(self._icon_name, current_palette().text_muted, 30).pixmap(30, 30)
        )

    def set_content(
        self,
        icon_name: str,
        title: str,
        description: str,
        action_text: str = "",
    ) -> None:
        self._icon_name = icon_name
        self._title.setText(title)
        self._description.setText(description)
        self._action.setText(action_text)
        self._action.setVisible(bool(action_text))
        self.refresh_theme()


class ToastWidget(QFrame):
    closed = Signal(object)

    def __init__(
        self,
        title: str,
        message: str,
        kind: str = "info",
        *,
        action_label: str = "",
        action_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "toast")
        self.setFixedWidth(380)
        self._closing = False
        palette = current_palette()
        colors = {
            "success": (palette.success, "check-circle"),
            "error": (palette.danger, "alert-circle"),
            "warning": (palette.warning, "alert-triangle"),
            "info": (palette.info, "info"),
        }
        color, icon_name = colors.get(kind, colors["info"])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 14, 14)
        layout.setSpacing(12)
        icon_label = QLabel(self)
        icon_label.setPixmap(icon(icon_name, color, 22).pixmap(22, 22))
        icon_label.setFixedSize(22, 22)
        layout.addWidget(icon_label, 0, Qt.AlignTop)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        title_label = QLabel(title, self)
        title_label.setProperty("role", "h3")
        title_label.setWordWrap(True)
        title_label.setTextFormat(Qt.TextFormat.PlainText)
        message_label = QLabel(message, self)
        message_label.setProperty("role", "caption")
        message_label.setProperty("path", "\\" in message)
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.PlainText)
        text_layout.addWidget(title_label)
        if message:
            text_layout.addWidget(message_label)
        if action_label and action_callback:
            action = make_button(action_label, "link", parent=self)
            action.clicked.connect(lambda: (action_callback(), self.dismiss()))
            text_layout.addWidget(action, 0, Qt.AlignLeft)
        layout.addLayout(text_layout, 1)
        close = make_icon_button("x", "通知を閉じる", size=13, parent=self)
        close.setFixedSize(26, 26)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignTop)
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(5200)
        self._close_timer.timeout.connect(self.dismiss)
        self._close_timer.start()
        self._appear()

    def _appear(self) -> None:
        if not animations_enabled():
            add_shadow(self, blur=30, alpha=90, y_offset=8)
            return
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(170)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(self._clear_effect)
        animation.start()
        self._appear_animation = animation

    def _clear_effect(self) -> None:
        self._appear_animation = None
        self.setGraphicsEffect(None)
        add_shadow(self, blur=30, alpha=90, y_offset=8)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._close_timer.start()
        super().leaveEvent(event)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._close_timer.stop()
        appear = getattr(self, "_appear_animation", None)
        if appear is not None:
            appear.stop()
            self._appear_animation = None
        if not animations_enabled():
            self.closed.emit(self)
            return
        self.setGraphicsEffect(None)
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(1.0)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(140)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.finished.connect(lambda: self.closed.emit(self))
        animation.start()
        self._close_animation = animation


class ToastHost(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignBottom)
        self._toasts: list[ToastWidget] = []
        self._host_width = 400
        self._repositioning = False
        self.hide()

    def show_toast(
        self,
        title: str,
        message: str = "",
        kind: str = "info",
        *,
        action_label: str = "",
        action_callback: Callable[[], None] | None = None,
    ) -> None:
        toast = ToastWidget(
            title,
            message,
            kind,
            action_label=action_label,
            action_callback=action_callback,
            parent=self,
        )
        toast.closed.connect(self._remove)
        self._toasts.append(toast)
        self._layout.addWidget(toast, 0, Qt.AlignRight)
        while len(self._toasts) > 3:
            oldest = self._toasts[0]
            self._remove(oldest)
            oldest.deleteLater()
        self.show()
        self.raise_()
        self._reposition()
        toast.show()

    def _remove(self, toast: ToastWidget) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            self._layout.removeWidget(toast)
            toast.hide()
        QTimer.singleShot(0, toast.deleteLater)
        self._reposition()

    def _reposition(self) -> None:
        if self._repositioning:
            return
        parent = self.parentWidget()
        if parent is None:
            return
        self._repositioning = True
        try:
            self._layout.activate()
            height = self._layout.sizeHint().height()
            width = self._host_width
            margin = 22
            self.setGeometry(
                max(0, parent.width() - width - margin),
                max(0, parent.height() - height - margin),
                width,
                max(0, height),
            )
            if not self._toasts:
                self.hide()
            else:
                self.show()
                self.raise_()
        finally:
            self._repositioning = False

    def reposition(self) -> None:
        self._reposition()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition()


def set_named_icon(
    widget: QWidget,
    name: str,
    *,
    color: str | None = None,
    size: int = 16,
) -> None:
    widget.setProperty("velaIconName", name)
    widget.setProperty("velaIconColor", color or "")
    widget.setProperty("velaIconSize", size)
    _apply_named_icon(widget)


def _apply_named_icon(widget: QWidget) -> None:
    name = widget.property("velaIconName")
    if not name:
        return
    palette = current_palette()
    color = str(widget.property("velaIconColor") or "secondary")
    color = {
        "accent": palette.accent,
        "secondary": palette.text_secondary,
        "muted": palette.text_muted,
        "text": palette.text,
        "danger": palette.danger,
        "success": palette.success,
        "warning": palette.warning,
        "info": palette.info,
        "on_accent": palette.on_accent,
    }.get(color, color)
    size = int(widget.property("velaIconSize") or 16)
    if isinstance(widget, QLabel):
        widget.setPixmap(icon(str(name), str(color), size).pixmap(size, size))
    elif isinstance(widget, QAbstractButton):
        widget.setIcon(icon(str(name), str(color), size))
        widget.setIconSize(QSize(size, size))


def refresh_named_icons(root: QWidget) -> None:
    for child in root.findChildren(QWidget):
        if child.property("velaIconName"):
            _apply_named_icon(child)


def shake(widget: QWidget) -> None:
    if not animations_enabled():
        return
    base = widget.pos()
    animation = QPropertyAnimation(widget, b"pos", widget)
    animation.setDuration(260)
    animation.setStartValue(base)
    animation.setKeyValueAt(0.15, base + QPoint(7, 0))
    animation.setKeyValueAt(0.35, base + QPoint(-6, 0))
    animation.setKeyValueAt(0.55, base + QPoint(4, 0))
    animation.setKeyValueAt(0.75, base + QPoint(-2, 0))
    animation.setEndValue(base)
    animation.start()
    widget._shake_animation = animation  # type: ignore[attr-defined]


def tone_colors(tone: str) -> tuple[str, str]:
    """Return (foreground, soft background) for a semantic tone name."""
    palette = current_palette()
    return {
        "accent": (palette.accent, palette.accent_soft),
        "success": (palette.success, palette.success_soft),
        "warning": (palette.warning, palette.warning_soft),
        "danger": (palette.danger, palette.danger_soft),
        "muted": (palette.text_muted, palette.surface_alt),
    }.get(tone, (palette.text_secondary, palette.surface_alt))


class StatCard(QFrame):
    """Compact metric card used on the queue and history pages."""

    def __init__(
        self,
        icon_name: str,
        label: str,
        tone: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "statCard")
        self._icon_name = icon_name
        self._tone = tone
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        self._badge = QLabel(self)
        self._badge.setFixedSize(38, 38)
        self._badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._badge, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(1)
        self._value = QLabel("0", self)
        value_font = QFont(self.font())
        value_font.setPointSizeF(16.5)
        value_font.setWeight(QFont.DemiBold)
        self._value.setFont(value_font)
        self._label = make_label(label, "caption")
        text.addWidget(self._value)
        text.addWidget(self._label)
        layout.addLayout(text, 1)
        self.refresh_theme()

    def set_value(self, value: object) -> None:
        self._value.setText(str(value))

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def refresh_theme(self) -> None:
        color, soft = tone_colors(self._tone)
        self._badge.setStyleSheet(f"background-color: {soft}; border-radius: 19px;")
        self._badge.setPixmap(icon(self._icon_name, color, 19).pixmap(19, 19))


def make_divider(parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setProperty("role", "separator")
    line.setFixedHeight(1)
    return line


def make_label(text: str, role: str = "", *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    # Titles, URLs and other externally supplied strings must never be parsed
    # as rich text: a video called "<b>..." would otherwise render as markup.
    label.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(wrap)
    return label
