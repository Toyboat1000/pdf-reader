"""A slim, hand-drawn horizontal slider in the app's style.

Qt's style sheets can't make the native Windows slider track thin, so this slider
paints itself: a 4 px rounded track, an accent-coloured fill, and a round knob with
a light ring that grows slightly under the mouse. Clicking anywhere on the track
jumps there (and keeps dragging), which is what people expect from a scrubber.
"""

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QMouseEvent, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QWidget

_TRACK = 4.0
_KNOB = 14.0
_KNOB_HOVER = 16.0


class SlimSlider(QSlider):
    """A horizontal :class:`QSlider` with a slim, modern look."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMinimumHeight(22)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hovered = False

    def _handle_rect(self) -> QRectF:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return QRectF(
            self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
            )
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the track, the filled part, and the knob."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        enabled = self.isEnabled()
        accent = palette.color(QPalette.ColorRole.Highlight)
        if self._hovered and enabled:
            accent = palette.color(QPalette.ColorRole.Link)
        muted = QColor(128, 128, 128, 80)
        # The knob's centre comes from the native style, so clicks and drags line up.
        handle = self._handle_rect()
        cx = handle.center().x()
        cy = self.height() / 2
        knob = _KNOB_HOVER if self._hovered and enabled else _KNOB
        left = knob / 2
        right = self.width() - knob / 2
        track = QRectF(left, cy - _TRACK / 2, right - left, _TRACK)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(muted)
        painter.drawRoundedRect(track, _TRACK / 2, _TRACK / 2)
        if enabled:
            filled = QRectF(left, track.top(), max(0.0, cx - left), _TRACK)
            painter.setBrush(accent)
            painter.drawRoundedRect(filled, _TRACK / 2, _TRACK / 2)
        shadow = QColor(0, 0, 0, 50)
        painter.setBrush(shadow)
        painter.drawEllipse(QPointF(cx, cy + 1), knob / 2, knob / 2)
        painter.setBrush(accent if enabled else QColor(128, 128, 128, 140))
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Base), 2))
        painter.drawEllipse(QPointF(cx, cy), knob / 2 - 1, knob / 2 - 1)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Jump to the clicked spot, then drag from there."""
        if event.button() == Qt.MouseButton.LeftButton and not self._handle_rect().contains(
            event.position()
        ):
            handle = self._handle_rect()
            span = max(self.width() - handle.width(), 1)
            position = int(event.position().x() - handle.width() / 2)
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), position, int(span)
            )
            self.setSliderPosition(value)
        super().mousePressEvent(event)

    def enterEvent(self, event: QEnterEvent) -> None:
        """Grow the knob slightly under the mouse."""
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Return the knob to its normal size."""
        self._hovered = False
        self.update()
        super().leaveEvent(event)
