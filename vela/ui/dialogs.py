from __future__ import annotations

from PySide6.QtCore import (
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .theme import EASING, MOTION_BASE, animations_enabled
from .widgets import make_button, make_label, set_named_icon


class AnimatedDialog(QDialog):
    """Modal dialog with a short, consistent fade-and-rise entrance."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._entrance_started = False
        self._entrance_animation: QParallelAnimationGroup | None = None
        if animations_enabled():
            self.setWindowOpacity(0.0)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._entrance_started:
            return
        if not animations_enabled():
            # The opacity was primed for the entrance animation; make sure a
            # preference change between construction and show never leaves the
            # dialog invisible.
            self.setWindowOpacity(1.0)
            return
        self._entrance_started = True
        target = self.pos()
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(MOTION_BASE)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(EASING)
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(MOTION_BASE)
        slide.setStartValue(target + QPoint(0, 8))
        slide.setEndValue(target)
        slide.setEasingCurve(EASING)
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(slide)
        group.start()
        self._entrance_animation = group


class ConfirmDialog(AnimatedDialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        confirm_text: str = "実行",
        cancel_text: str = "キャンセル",
        danger: bool = False,
        detail: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("確認")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setMaximumWidth(600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        badge = QLabel(self)
        badge.setProperty("role", "dialogIcon")
        badge.setProperty("tone", "danger" if danger else "accent")
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignCenter)
        set_named_icon(
            badge,
            "alert-triangle" if danger else "info",
            color="danger" if danger else "accent",
            size=20,
        )
        head.addWidget(badge, 0, Qt.AlignTop)
        heading = make_label(title, "h2", wrap=True)
        head.addWidget(heading, 1, Qt.AlignVCenter)
        layout.addLayout(head)

        body = make_label(message, "secondary", wrap=True)
        if "\\" in message:
            body.setProperty("path", True)
        layout.addWidget(body)

        if detail:
            detail_box = QFrame(self)
            detail_box.setProperty("role", "detailBox")
            detail_layout = QVBoxLayout(detail_box)
            detail_layout.setContentsMargins(11, 9, 11, 9)
            detail_label = make_label(detail, "caption", wrap=True)
            if "\\" in detail:
                detail_label.setProperty("path", True)
            detail_layout.addWidget(detail_label)
            layout.addWidget(detail_box)

        layout.addSpacing(4)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = make_button(cancel_text, "secondary", parent=self)
        cancel.clicked.connect(self.reject)
        confirm = make_button(
            confirm_text, "danger" if danger else "primary", parent=self
        )
        confirm.clicked.connect(self.accept)
        if danger:
            # Destructive actions should not fire on a reflexive Enter press.
            cancel.setDefault(True)
            cancel.setFocus(Qt.OtherFocusReason)
            confirm.setAutoDefault(False)
        else:
            confirm.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        confirm_text: str = "実行",
        cancel_text: str = "キャンセル",
        danger: bool = False,
        detail: str = "",
    ) -> bool:
        dialog = cls(
            parent,
            title,
            message,
            confirm_text=confirm_text,
            cancel_text=cancel_text,
            danger=danger,
            detail=detail,
        )
        return dialog.exec() == QDialog.Accepted


class HelpDialog(AnimatedDialog):
    SHORTCUTS = (
        ("Ctrl+L", "URL 入力欄にフォーカス"),
        ("Ctrl+V", "URL を貼り付けて解析"),
        ("Ctrl+Enter", "入力中の URL を解析"),
        ("Ctrl+F", "キュー・履歴を検索"),
        ("Ctrl+1 – Ctrl+5", "画面を切り替え"),
        ("Ctrl+,", "設定を開く"),
        ("Delete", "選択中の項目を削除"),
        ("F1", "このヘルプを表示"),
        ("Esc", "解析を中止 / ダイアログを閉じる"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vela の使い方")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        badge = QLabel(self)
        badge.setProperty("role", "dialogIcon")
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignCenter)
        set_named_icon(badge, "help", color="accent", size=20)
        head.addWidget(badge, 0, Qt.AlignTop)
        head.addWidget(make_label("Vela の使い方", "h1"), 1, Qt.AlignVCenter)
        layout.addLayout(head)

        layout.addWidget(
            make_label(
                "動画の URL を貼り付けて「解析」を押すと、保存できる画質と形式が表示されます。"
                "必要な画質を選び、保存先を確認してダウンロードを開始してください。",
                "secondary",
                wrap=True,
            )
        )
        layout.addWidget(
            make_label(
                "ダウンロードはキューで順番に処理されます。映像と音声が別々に配信されている場合は、"
                "自動的に FFmpeg で結合します。",
                "caption",
                wrap=True,
            )
        )
        layout.addSpacing(4)
        layout.addWidget(make_label("キーボードショートカット", "h3"))
        key_metrics = QFontMetrics(self.font())
        key_width = (
            max(key_metrics.horizontalAdvance(keys) for keys, _ in self.SHORTCUTS) + 28
        )
        for keys, description in self.SHORTCUTS:
            row = QHBoxLayout()
            row.setSpacing(12)
            key_label = QLabel(keys, self)
            key_label.setProperty("role", "pill")
            key_label.setFixedWidth(key_width)
            key_label.setAlignment(Qt.AlignCenter)
            row.addWidget(key_label)
            row.addWidget(make_label(description, "secondary"), 1)
            layout.addLayout(row)
        layout.addSpacing(6)
        note = make_label(
            "利用する権利のあるコンテンツのみをダウンロードしてください。DRM の解除やアクセス制限の回避は行いません。",
            "caption",
            wrap=True,
        )
        layout.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = make_button("閉じる", "primary", parent=self)
        close.clicked.connect(self.accept)
        close.setDefault(True)
        buttons.addWidget(close)
        layout.addLayout(buttons)
