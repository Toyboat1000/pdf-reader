"""A small transient message ("Copied", "Zoom 125%") that fades in and out."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget


class Toast(QLabel):
    """A dark rounded pill centred near the bottom of its parent.

    Showing a new message while one is visible replaces it immediately, and the
    fade always starts from the current opacity, so it never jumps.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._after_fade)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._animate(0.0, 260))
        self.bottom_offset = 120
        self.hide()

    def show_message(self, text: str, duration_ms: int = 1800) -> None:
        """Show ``text`` for ``duration_ms`` milliseconds."""
        self.setText(text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._animate(1.0, 160)
        self._timer.start(duration_ms)

    def reposition(self) -> None:
        """Centre horizontally, just above the player bar."""
        parent = self.parentWidget()
        if parent is not None:
            self.move(
                (parent.width() - self.width()) // 2,
                parent.height() - self.height() - self.bottom_offset,
            )

    def _animate(self, target: float, duration: int) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())  # From the current value.
        self._fade.setEndValue(target)
        self._fade.setDuration(duration)
        self._fade.start()

    def _after_fade(self) -> None:
        if self._effect.opacity() <= 0.01:
            self.hide()
