"""Scanned pages shown as images, with the spoken sentence highlighted.

Click a word to read from there; the spoken sentence
is highlighted on the image.
"""

import logging
from collections import OrderedDict

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QRectF,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

from pdf_reader.core.document import ReadingDocument
from pdf_reader.core.word_map import WordMap
from pdf_reader.pdf.render import PageRenderer

log = logging.getLogger(__name__)

_GAP = 16  # Pixels between pages.
_MARGIN = 16  # Pixels around the pages.
_MAX_ZOOM = 2.0  # Pixels per PDF point at most (about 144 dpi).
_CACHE_PAGES = 8
_CLICK_TOLERANCE = 6
_HOVER_REACH = 14.0  # Points from a word within which the hover preview appears.


class PageView(QAbstractScrollArea):
    """Shows a document's pages as images, scrolled vertically and fitted to the width.

    Only visible pages are rendered, and recently shown ones are cached.
    """

    sentence_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Keyboard focus stays on the window so Space and the arrows control playback.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._renderer: PageRenderer | None = None
        self._sizes: list[tuple[float, float]] = []  # Page sizes in points.
        self._tops: list[float] = []  # Page tops in pixels, at the current zoom.
        self._zoom = 1.0
        self._word_map: WordMap | None = None
        self._current = -1
        self._cache: OrderedDict[tuple[int, float], QPixmap] = OrderedDict()
        self._press_pos: QPoint | None = None
        self._hover = -1
        self._hover_opacity = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(140)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._on_fade)
        self.viewport().setMouseTracking(True)

    # -------------------------------------------------------------- content

    def set_document(self, document: ReadingDocument) -> None:
        """Show the pages of a scanned PDF."""
        self.clear_document()
        if document.pdf is None or document.path is None or document.word_map is None:
            return
        try:
            self._renderer = PageRenderer(document.path)
        except Exception:
            log.exception("Cannot open %s for display", document.path)
            return
        self._sizes = [(p.width, p.height) for p in document.pdf.pages]
        self._word_map = document.word_map
        self._relayout()
        self.verticalScrollBar().setValue(0)
        self.viewport().update()

    def clear_document(self) -> None:
        """Show nothing and release the file."""
        if self._renderer is not None:
            self._renderer.close()
        self._renderer = None
        self._sizes = []
        self._tops = []
        self._word_map = None
        self._current = -1
        self._hover = -1
        self._cache.clear()
        self.viewport().update()

    def highlight(self, index: int) -> None:
        """Highlight sentence ``index`` and scroll it into view if needed."""
        self._current = index
        if self._word_map is not None:
            boxes = self._word_map.sentence_boxes(index)
            if boxes:
                first = boxes[0]
                top = self._tops[first.page - 1] + first.bbox[1] * self._zoom
                bottom = self._tops[first.page - 1] + boxes[-1].bbox[3] * self._zoom
                bar = self.verticalScrollBar()
                height = self.viewport().height()
                if top < bar.value() + height * 0.1 or bottom > bar.value() + height * 0.9:
                    bar.setValue(int(top - height / 3))
        self.viewport().update()

    # --------------------------------------------------------------- layout

    def _relayout(self) -> None:
        if not self._sizes:
            return
        widest = max(w for w, _ in self._sizes)
        available = max(self.viewport().width() - 2 * _MARGIN, 100)
        self._zoom = min(_MAX_ZOOM, available / widest)
        y = float(_MARGIN)
        self._tops = []
        for _, h in self._sizes:
            self._tops.append(y)
            y += h * self._zoom + _GAP
        bar = self.verticalScrollBar()
        bar.setRange(0, max(0, int(y + _MARGIN - _GAP - self.viewport().height())))
        bar.setPageStep(self.viewport().height())
        bar.setSingleStep(40)

    def _page_rect(self, index: int) -> QRectF:
        w, h = self._sizes[index]
        left = (self.viewport().width() - w * self._zoom) / 2
        top = self._tops[index] - self.verticalScrollBar().value()
        return QRectF(left, top, w * self._zoom, h * self._zoom)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Refit the pages to the new width."""
        super().resizeEvent(event)
        self._relayout()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """Repaint after scrolling (pages are drawn by hand)."""
        self.viewport().update()

    # ---------------------------------------------------------------- paint

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the visible pages and the highlighted sentence."""
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.viewport().rect(), self.palette().color(QPalette.ColorRole.Mid))
        height = self.viewport().height()
        for index in range(len(self._sizes)):
            rect = self._page_rect(index)
            if rect.bottom() < 0 or rect.top() > height:
                continue
            pixmap = self._pixmap(index + 1)
            if pixmap is None:
                painter.fillRect(rect, Qt.GlobalColor.white)
            else:
                painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
        accent = self.palette().color(QPalette.ColorRole.Accent)
        if self._hover >= 0 and self._hover != self._current and self._hover_opacity > 0:
            hover_pills = self._pills(self._hover)
            self._draw_pills(
                painter, hover_pills, accent, fill=0.16, outline=0.75, opacity=self._hover_opacity
            )
            if hover_pills:
                self._draw_badge(painter, hover_pills[0], accent, self._hover_opacity)
        if self._current >= 0:
            self._draw_pills(
                painter, self._pills(self._current), accent, fill=0.32, outline=0.9, opacity=1.0
            )
        painter.end()

    def _pills(self, sentence: int) -> list[QRectF]:
        """Return a sentence's highlight pills in viewport coordinates."""
        if self._word_map is None:
            return []
        pills = []
        for page, (x0, y0, x1, y1) in self._word_map.sentence_lines(sentence):
            rect = self._page_rect(page - 1)
            band = (y1 - y0) * self._zoom
            pad_y = band * 0.28
            pad_x = band * 0.28
            pills.append(
                QRectF(
                    rect.left() + x0 * self._zoom - pad_x,
                    rect.top() + y0 * self._zoom - pad_y,
                    (x1 - x0) * self._zoom + 2 * pad_x,
                    band + 2 * pad_y,
                )
            )
        return pills

    @staticmethod
    def _draw_pills(
        painter: QPainter,
        pills: list[QRectF],
        accent: QColor,
        *,
        fill: float,
        outline: float,
        opacity: float,
    ) -> None:
        """Draw rounded, evenly sized highlight pills with a soft glow."""
        for pill in pills:
            radius = pill.height() / 2
            glow = QColor(accent)
            glow.setAlphaF(0.10 * opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(pill.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
            top = QColor(accent).lighter(115)
            top.setAlphaF(fill * opacity)
            bottom = QColor(accent)
            bottom.setAlphaF(fill * 1.25 * opacity)
            gradient = QLinearGradient(pill.topLeft(), pill.bottomLeft())
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, bottom)
            edge = QColor(accent)
            edge.setAlphaF(outline * opacity)
            painter.setPen(QPen(edge, 1.4))
            painter.setBrush(gradient)
            painter.drawRoundedRect(pill, radius, radius)

    def _draw_badge(
        self, painter: QPainter, anchor: QRectF, accent: QColor, opacity: float
    ) -> None:
        """Draw a small "Read from here" tag above the first hovered pill."""
        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF() - 0.5, 8.0))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        text = "\u25b6  Read from here"
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 20
        height = metrics.height() + 8
        x = max(anchor.left(), 4.0)
        y = anchor.top() - height - 6
        if y < 4:
            y = anchor.bottom() + 6
        badge = QRectF(x, y, width, height)
        shadow = QColor(0, 0, 0)
        shadow.setAlphaF(0.25 * opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawRoundedRect(badge.translated(0, 2), height / 2, height / 2)
        # A deep shade of the accent colour, so white text always stands out.
        hue, saturation, lightness, _ = accent.getHslF()
        top = QColor.fromHslF(hue, saturation, min(lightness, 0.46), opacity)
        bottom = QColor.fromHslF(hue, saturation, min(lightness, 0.46) * 0.8, opacity)
        gradient = QLinearGradient(badge.topLeft(), badge.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.setBrush(gradient)
        painter.drawRoundedRect(badge, height / 2, height / 2)
        label = QColor(Qt.GlobalColor.white)
        label.setAlphaF(opacity)
        painter.setPen(label)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def _pixmap(self, page_number: int) -> QPixmap | None:
        if self._renderer is None:
            return None
        ratio = self.devicePixelRatioF()
        key = (page_number, round(self._zoom * ratio, 3))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        try:
            page = self._renderer.render(page_number, self._zoom * ratio)
        except Exception:
            log.exception("Cannot render page %d", page_number)
            return None
        image = QImage(
            page.samples, page.width, page.height, page.stride, QImage.Format.Format_RGB888
        ).copy()  # Copy: the bytes object must not be referenced after this call.
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        self._cache[key] = pixmap
        while len(self._cache) > _CACHE_PAGES:
            self._cache.popitem(last=False)
        return pixmap

    # --------------------------------------------------------------- clicks

    def sentence_at(self, pos: QPoint) -> int | None:
        """Return the sentence of the word at viewport position ``pos``, if any."""
        if self._word_map is None:
            return None
        for index in range(len(self._sizes)):
            rect = self._page_rect(index)
            if rect.contains(pos.toPointF()):
                x = (pos.x() - rect.left()) / self._zoom
                y = (pos.y() - rect.top()) / self._zoom
                return self._word_map.sentence_at(index + 1, x, y)
        return None

    def hovered(self) -> int:
        """Return the sentence under the mouse, or -1."""
        return self._hover

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Preview the sentence that a click would start reading."""
        self._set_hover(self._sentence_near(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Clear the preview when the mouse leaves."""
        self._set_hover(-1)
        super().leaveEvent(event)

    def _sentence_near(self, pos: QPoint) -> int:
        """Return the sentence of a word close to ``pos`` (not just the nearest one)."""
        if self._word_map is None:
            return -1
        for index in range(len(self._sizes)):
            rect = self._page_rect(index)
            if rect.contains(pos.toPointF()):
                x = (pos.x() - rect.left()) / self._zoom
                y = (pos.y() - rect.top()) / self._zoom
                found = self._word_map.sentence_at(index + 1, x, y, max_distance=_HOVER_REACH)
                return -1 if found is None else found
        return -1

    def _set_hover(self, sentence: int) -> None:
        if sentence == self._hover:
            return
        self._hover = sentence
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if sentence >= 0 else Qt.CursorShape.ArrowCursor
        )
        self._fade.stop()
        if sentence >= 0:
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self._hover_opacity = 0.0
        self.viewport().update()

    def _on_fade(self, value: float) -> None:
        self._hover_opacity = float(value)
        self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Remember where a click started."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Emit :attr:`sentence_clicked` for a click on (or near) a word."""
        press, self._press_pos = self._press_pos, None
        pos = event.position().toPoint()
        if (
            event.button() == Qt.MouseButton.LeftButton
            and press is not None
            and (pos - press).manhattanLength() <= _CLICK_TOLERANCE
            and (index := self.sentence_at(pos)) is not None
        ):
            self.sentence_clicked.emit(index)
        super().mouseReleaseEvent(event)
