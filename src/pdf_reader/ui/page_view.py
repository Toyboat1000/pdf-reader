"""PDF pages shown as images, with the spoken sentence highlighted.

Click a word to read from there, hover to preview what a click will play, drag to
select text and copy it, and zoom with Ctrl + mouse wheel. Works for scanned pages
(text from OCR) and ordinary PDFs (text from the file) alike.
"""

import logging
from collections import OrderedDict

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
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
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QMenu, QWidget

from pdf_reader.core.document import ReadingDocument
from pdf_reader.core.word_map import WordBox, WordMap, line_bands
from pdf_reader.pdf.render import PageRenderer

log = logging.getLogger(__name__)

_GAP = 20  # Pixels between pages.
_MARGIN = 24  # Pixels around the pages.
_MAX_FIT = 2.0  # Fit-to-width never enlarges beyond this many pixels per point.
_MAX_RENDER = 4.0  # Never render more pixels per point than this (memory).
_CACHE_PAGES = 8
_PLAYER_CLEARANCE = 130  # Room under the last page for the floating player.
_CLICK_TOLERANCE = 6
_HOVER_REACH = 14.0  # Points from a word within which the hover preview appears.
MIN_ZOOM = 0.5
MAX_ZOOM = 4.0


class PageView(QAbstractScrollArea):
    """Shows a document's pages, fitted to the width and scaled by the zoom level.

    Only visible pages are rendered, and recently shown ones are cached.
    """

    sentence_clicked = Signal(int)
    zoom_changed = Signal(float)
    copy_requested = Signal()
    copy_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Keyboard focus stays on the window so Space and the arrows control playback.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.viewport().setMouseTracking(True)
        self._renderer: PageRenderer | None = None
        self._sizes: list[tuple[float, float]] = []  # Page sizes in points.
        self._tops: list[float] = []  # Page tops in pixels, at the current zoom.
        self._scale = 1.0  # Pixels per point actually drawn.
        self._zoom = 1.0  # User zoom relative to fit-to-width.
        self._word_map: WordMap | None = None
        self._words: list[WordBox] = []  # All words in reading order, for selection.
        self._current = -1
        self._cache: OrderedDict[tuple[int, float], QPixmap] = OrderedDict()
        self._press_pos: QPoint | None = None
        self._press_word: int | None = None
        self._selection: tuple[int, int] | None = None  # Word indexes, inclusive.
        self._hover = -1
        self._hover_opacity = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(140)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._on_fade)
        self._scroll = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll.setDuration(320)
        self._scroll.setEasingCurve(QEasingCurve.Type.OutCubic)

    # -------------------------------------------------------------- content

    def set_document(self, document: ReadingDocument) -> None:
        """Show the pages of a PDF that has word positions."""
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
        self._words = [
            w for page in sorted(self._word_map.by_page) for w in self._word_map.by_page[page]
        ]
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
        self._words = []
        self._current = -1
        self._hover = -1
        self._selection = None
        self._cache.clear()
        self.viewport().update()

    def highlight(self, index: int) -> None:
        """Highlight sentence ``index`` and scroll it into view if needed."""
        self._current = index
        if self._word_map is not None and self._tops:
            lines = self._word_map.sentence_lines(index)
            if lines:
                top = self._tops[lines[0][0] - 1] + lines[0][1][1] * self._scale
                bottom = self._tops[lines[-1][0] - 1] + lines[-1][1][3] * self._scale
                bar = self.verticalScrollBar()
                height = self.viewport().height()
                visible_bottom = bar.value() + height - _PLAYER_CLEARANCE
                if top < bar.value() + height * 0.1 or bottom > visible_bottom:
                    self._glide_to(int(top - height / 3))
        self.viewport().update()

    def _glide_to(self, value: int) -> None:
        """Scroll smoothly, starting from wherever the view is now (interruptible)."""
        bar = self.verticalScrollBar()
        value = max(bar.minimum(), min(bar.maximum(), value))
        self._scroll.stop()
        self._scroll.setStartValue(bar.value())
        self._scroll.setEndValue(value)
        self._scroll.start()

    # ----------------------------------------------------------------- zoom

    @property
    def zoom(self) -> float:
        """Return the zoom level (1.0 = page width fits the window)."""
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        """Set the zoom level, keeping the middle of the view in place."""
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(zoom - self._zoom) < 1e-3:
            return
        bar = self.verticalScrollBar()
        anchor = (bar.value() + self.viewport().height() / 2) / max(self._scale, 1e-6)
        self._zoom = zoom
        self._relayout()
        bar.setValue(int(anchor * self._scale - self.viewport().height() / 2))
        self.viewport().update()
        self.zoom_changed.emit(zoom)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl + wheel zooms; the wheel alone scrolls."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            self.set_zoom(self._zoom * (1.1**steps))
            event.accept()
        else:
            super().wheelEvent(event)

    # --------------------------------------------------------------- layout

    def _relayout(self) -> None:
        if not self._sizes:
            return
        widest = max(w for w, _ in self._sizes)
        available = max(self.viewport().width() - 2 * _MARGIN, 100)
        self._scale = min(_MAX_FIT, available / widest) * self._zoom
        y = float(_MARGIN)
        self._tops = []
        for _, h in self._sizes:
            self._tops.append(y)
            y += h * self._scale + _GAP
        vbar = self.verticalScrollBar()
        bottom = _MARGIN + _PLAYER_CLEARANCE  # The last page can scroll clear of the player.
        vbar.setRange(0, max(0, int(y + bottom - _GAP - self.viewport().height())))
        vbar.setPageStep(self.viewport().height())
        vbar.setSingleStep(48)
        content_width = widest * self._scale + 2 * _MARGIN
        hbar = self.horizontalScrollBar()
        hbar.setRange(0, max(0, int(content_width - self.viewport().width())))
        hbar.setPageStep(self.viewport().width())

    def _page_rect(self, index: int) -> QRectF:
        w, h = self._sizes[index]
        widest = max(pw for pw, _ in self._sizes)
        content_width = widest * self._scale + 2 * _MARGIN
        if content_width <= self.viewport().width():
            left = (self.viewport().width() - w * self._scale) / 2
        else:
            left = _MARGIN + (widest - w) * self._scale / 2 - self.horizontalScrollBar().value()
        top = self._tops[index] - self.verticalScrollBar().value()
        return QRectF(left, top, w * self._scale, h * self._scale)

    def _to_view(self, page: int, box: tuple[float, float, float, float]) -> QRectF:
        rect = self._page_rect(page - 1)
        x0, y0, x1, y1 = box
        return QRectF(
            rect.left() + x0 * self._scale,
            rect.top() + y0 * self._scale,
            (x1 - x0) * self._scale,
            (y1 - y0) * self._scale,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Refit the pages to the new width."""
        super().resizeEvent(event)
        self._relayout()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """Repaint after scrolling (pages are drawn by hand)."""
        self.viewport().update()

    # ---------------------------------------------------------------- paint

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the pages, the selection, the hover preview, and the spoken sentence."""
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        background = self.palette().color(QPalette.ColorRole.Window).darker(112)
        painter.fillRect(self.viewport().rect(), background)
        height = self.viewport().height()
        for index in range(len(self._sizes)):
            rect = self._page_rect(index)
            if rect.bottom() < 0 or rect.top() > height:
                continue
            self._draw_shadow(painter, rect)
            pixmap = self._pixmap(index + 1)
            if pixmap is None:
                painter.fillRect(rect, Qt.GlobalColor.white)
            else:
                painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
        self._draw_selection(painter)
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

    @staticmethod
    def _draw_shadow(painter: QPainter, rect: QRectF) -> None:
        """A soft drop shadow under a page, so it reads as paper."""
        painter.setPen(Qt.PenStyle.NoPen)
        for spread, alpha in ((6, 0.05), (4, 0.07), (2, 0.10)):
            shadow = QColor(0, 0, 0)
            shadow.setAlphaF(alpha)
            painter.setBrush(shadow)
            painter.drawRoundedRect(rect.adjusted(-spread, -spread + 2, spread, spread + 2), 4, 4)

    def _pills(self, sentence: int) -> list[QRectF]:
        """Return a sentence's highlight pills in viewport coordinates."""
        if self._word_map is None:
            return []
        pills = []
        for page, band in self._word_map.sentence_lines(sentence):
            rect = self._to_view(page, band)
            pad_y = rect.height() * 0.10  # Clears ascenders and descenders; lines don't touch.
            pad_x = rect.height() * 0.16
            pills.append(rect.adjusted(-pad_x, -pad_y, pad_x, pad_y))
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
        """Draw evenly sized, softly rounded highlight pills with a faint glow."""
        for pill in pills:
            radius = pill.height() * 0.28  # Softly rounded corners, not a full capsule.
            glow = QColor(accent)
            glow.setAlphaF(0.10 * opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(pill.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
            top = QColor(accent).lighter(115)
            top.setAlphaF(fill * opacity)
            bottom = QColor(accent)
            bottom.setAlphaF(min(1.0, fill * 1.25 * opacity))
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
        gradient = QLinearGradient(badge.topLeft(), badge.bottomLeft())
        gradient.setColorAt(0.0, QColor.fromHslF(hue, saturation, min(lightness, 0.46), opacity))
        gradient.setColorAt(
            1.0, QColor.fromHslF(hue, saturation, min(lightness, 0.46) * 0.8, opacity)
        )
        painter.setBrush(gradient)
        painter.drawRoundedRect(badge, height / 2, height / 2)
        label = QColor(Qt.GlobalColor.white)
        label.setAlphaF(opacity)
        painter.setPen(label)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_selection(self, painter: QPainter) -> None:
        if self._selection is None:
            return
        color = QColor(self.palette().color(QPalette.ColorRole.Highlight))
        color.setAlphaF(0.35)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for page, band in line_bands(self.selected_words()):
            rect = self._to_view(page, band).adjusted(-2, -2, 2, 2)
            painter.drawRoundedRect(rect, 3, 3)

    def _pixmap(self, page_number: int) -> QPixmap | None:
        if self._renderer is None:
            return None
        ratio = self.devicePixelRatioF()
        render_scale = min(self._scale * ratio, _MAX_RENDER)
        key = (page_number, round(render_scale, 3))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        try:
            page = self._renderer.render(page_number, render_scale)
        except Exception:
            log.exception("Cannot render page %d", page_number)
            return None
        image = QImage(
            page.samples, page.width, page.height, page.stride, QImage.Format.Format_RGB888
        ).copy()  # Copy: the bytes object must not be referenced after this call.
        pixmap = QPixmap.fromImage(image)
        self._cache[key] = pixmap
        while len(self._cache) > _CACHE_PAGES:
            self._cache.popitem(last=False)
        return pixmap

    # ------------------------------------------------------------ selection

    def has_selection(self) -> bool:
        """Return whether some text is selected."""
        return self._selection is not None

    def selected_words(self) -> list[WordBox]:
        """Return the selected words in reading order."""
        if self._selection is None:
            return []
        first, last = sorted(self._selection)
        return self._words[first : last + 1]

    def selected_text(self) -> str:
        """Return the selected text, with line and page breaks."""
        return words_to_text(self.selected_words())

    def select_all(self) -> None:
        """Select every word in the document."""
        if self._words:
            self._selection = (0, len(self._words) - 1)
            self.viewport().update()

    def clear_selection(self) -> None:
        """Deselect."""
        if self._selection is not None:
            self._selection = None
            self.viewport().update()

    def _word_index_at(self, pos: QPoint, reach: float | None) -> int | None:
        """Return the index of the word at (or near) ``pos`` in :attr:`_words`."""
        page = self._page_at(pos)
        if page is None or not self._words:
            return None
        rect = self._page_rect(page - 1)
        x = (pos.x() - rect.left()) / self._scale
        y = (pos.y() - rect.top()) / self._scale
        best, best_distance = None, float("inf")
        for i, word in enumerate(self._words):
            if word.page != page:
                continue
            x0, y0, x1, y1 = word.bbox
            dx = max(x0 - x, 0.0, x - x1)
            dy = max(y0 - y, 0.0, y - y1)
            distance = dx * dx + 4 * dy * dy
            if distance < best_distance:
                best, best_distance = i, distance
        if reach is not None and best_distance > reach**2:
            return None
        return best

    def _page_at(self, pos: QPoint) -> int | None:
        for index in range(len(self._sizes)):
            if self._page_rect(index).contains(QPointF(pos)):
                return index + 1
        return None

    # --------------------------------------------------------------- clicks

    def sentence_at(self, pos: QPoint) -> int | None:
        """Return the sentence of the word at (or nearest to) viewport position ``pos``."""
        index = self._word_index_at(pos, reach=None)
        return self._words[index].sentence if index is not None else None

    def hovered(self) -> int:
        """Return the sentence under the mouse, or -1."""
        return self._hover

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a click or a text selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_word = self._word_index_at(self._press_pos, reach=None)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Extend a selection while dragging; otherwise preview the sentence."""
        pos = event.position().toPoint()
        dragging = (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (pos - self._press_pos).manhattanLength() > _CLICK_TOLERANCE
        )
        if dragging and self._press_word is not None:
            end = self._word_index_at(pos, reach=None)
            if end is not None:
                self._selection = (self._press_word, end)
                self._set_hover(-1)
                self.viewport().update()
        elif not dragging:
            self._set_hover(self._sentence_near(pos))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """A click (not a drag) reads from the clicked word's sentence."""
        press, self._press_pos = self._press_pos, None
        pos = event.position().toPoint()
        is_click = (
            event.button() == Qt.MouseButton.LeftButton
            and press is not None
            and (pos - press).manhattanLength() <= _CLICK_TOLERANCE
        )
        if is_click:
            self.clear_selection()
            if (index := self.sentence_at(pos)) is not None:
                self.sentence_clicked.emit(index)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Offer copying and reading from the right-clicked sentence."""
        menu = QMenu(self)
        sentence = self.sentence_at(event.pos())
        if sentence is not None:
            menu.addAction("\u25b6  Read from Here", lambda: self.sentence_clicked.emit(sentence))
            menu.addSeparator()
        copy = menu.addAction("Copy", self.copy_requested.emit)
        copy.setShortcut("Ctrl+C")
        copy.setEnabled(self.has_selection())
        menu.addAction("Copy All Text", self.copy_all_requested.emit).setShortcut("Ctrl+Shift+C")
        menu.addAction("Select All", self.select_all).setShortcut("Ctrl+A")
        menu.exec(event.globalPos())

    def leaveEvent(self, event: QEvent) -> None:
        """Clear the preview when the mouse leaves."""
        self._set_hover(-1)
        super().leaveEvent(event)

    def _sentence_near(self, pos: QPoint) -> int:
        index = self._word_index_at(pos, reach=_HOVER_REACH)
        return self._words[index].sentence if index is not None else -1

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


def words_to_text(words: list[WordBox]) -> str:
    """Join words into text, with line breaks between lines and blank lines between pages."""
    parts: list[str] = []
    previous: WordBox | None = None
    for word in words:
        if previous is not None:
            if word.page != previous.page:
                parts.append("\n\n")
            elif not _on_same_line(previous, word):
                parts.append("\n")
            else:
                parts.append(" ")
        parts.append(word.text)
        previous = word
    return "".join(parts)


def _on_same_line(a: WordBox, b: WordBox) -> bool:
    height = a.bbox[3] - a.bbox[1]
    return abs((a.bbox[1] + a.bbox[3]) / 2 - (b.bbox[1] + b.bbox[3]) / 2) < 0.6 * height
