"""Scanned pages shown as images, with the spoken sentence highlighted.

Click a word to read from there; the spoken sentence
is highlighted on the image.
"""

import logging
from collections import OrderedDict

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
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

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 - Qt override.
        """Repaint after scrolling (pages are drawn by hand)."""
        self.viewport().update()

    # ---------------------------------------------------------------- paint

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override.
        """Draw the visible pages and the highlighted sentence."""
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), self.palette().color(QPalette.ColorRole.Mid))
        height = self.viewport().height()
        highlight = QColor(self.palette().color(QPalette.ColorRole.Highlight))
        highlight.setAlpha(90)
        boxes = self._word_map.sentence_boxes(self._current) if self._word_map else []
        for index in range(len(self._sizes)):
            rect = self._page_rect(index)
            if rect.bottom() < 0 or rect.top() > height:
                continue
            pixmap = self._pixmap(index + 1)
            if pixmap is None:
                painter.fillRect(rect, Qt.GlobalColor.white)
            else:
                painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
            for box in boxes:
                if box.page == index + 1:
                    x0, y0, x1, y1 = box.bbox
                    painter.fillRect(
                        QRectF(
                            rect.left() + x0 * self._zoom - 2,
                            rect.top() + y0 * self._zoom - 2,
                            (x1 - x0) * self._zoom + 4,
                            (y1 - y0) * self._zoom + 4,
                        ),
                        highlight,
                    )
        painter.end()

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
