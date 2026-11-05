"""The home page: start something new, or continue where you left off.

Calm hierarchy, top to bottom: the date and a greeting; a composer to paste text or a
link and listen at once; three quick starts (open a document, open a link, read the
clipboard); and the documents being read, as book covers with a slim progress line.
Documents without a picture of their first page get a typeset cover of their own.
"""

import hashlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QEnterEvent,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdf_reader.library import DocumentRecord
from pdf_reader.sources import is_web_address
from pdf_reader.ui.icons import Glyph, glyph_pixmap

_COVER_WIDTH = 156
_COVER_HEIGHT = 208  # 3:4, like a book.
_LIFT = 6  # Pixels a cover rises when hovered.
_CARD_WIDTH = _COVER_WIDTH + 16
_GRID_SPACING = 24
_CONTENT_MAX_WIDTH = 1080

# Calm, deep colours for typeset covers (picked per document, so each keeps its own).
_COVER_COLOURS = (
    ("#3b5bdb", "#5f3dc4"),
    ("#0b7285", "#1864ab"),
    ("#2b8a3e", "#0b7285"),
    ("#c2255c", "#862e9c"),
    ("#e8590c", "#c92a2a"),
    ("#495057", "#212529"),
)


def greeting(hour: int) -> str:
    """Return a friendly greeting for the hour of the day."""
    if hour < 5:
        return "Good evening"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _shadow(widget: QWidget, blur: float, offset: float, alpha: int) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return effect


class _Cover(QWidget):
    """A document's cover: its first page, or a typeset one; rises when hovered."""

    def __init__(self, record: DocumentRecord, image: Path | None, kind: str) -> None:
        super().__init__()
        self.setFixedSize(_COVER_WIDTH, _COVER_HEIGHT + _LIFT)
        self._record = record
        self._kind = kind
        self._pixmap = (
            _trimmed(QPixmap(str(image))) if image is not None and image.exists() else None
        )
        self._lift = 0.0
        self._shadow = _shadow(self, 18, 5, 46)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_lift)

    def hover(self, on: bool) -> None:
        """Rise (or settle), starting from wherever the cover is now (interruptible)."""
        self._animation.stop()
        self._animation.setStartValue(self._lift)
        self._animation.setEndValue(1.0 if on else 0.0)
        self._animation.start()

    def _set_lift(self, value: float) -> None:
        self._lift = float(value)
        self._shadow.setBlurRadius(18 + 14 * self._lift)
        self._shadow.setOffset(0, 5 + 7 * self._lift)
        self._shadow.setColor(QColor(0, 0, 0, int(46 + 24 * self._lift)))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the cover clipped to softly rounded corners."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, _LIFT * (1 - self._lift), _COVER_WIDTH, _COVER_HEIGHT)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        painter.setClipPath(clip)
        if self._pixmap is not None and not self._pixmap.isNull():
            painter.fillRect(rect, QColor(255, 255, 255))
            self._draw_page(painter, rect)
        else:
            self._draw_typeset(painter, rect)
        painter.setClipping(False)
        painter.setPen(QColor(0, 0, 0, 28))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        painter.end()

    def _draw_page(self, painter: QPainter, rect: QRectF) -> None:
        """Fill the cover with the page, cropping the excess (centred, top kept)."""
        assert self._pixmap is not None
        ratio = self.devicePixelRatioF()
        source = QRectF(self._pixmap.rect())
        scale = max(rect.width() / source.width(), rect.height() / source.height())
        width, height = rect.width() / scale, rect.height() / scale
        crop = QRectF((source.width() - width) / 2, 0, width, height)
        target = QSize(int(rect.width() * ratio), int(rect.height() * ratio))
        scaled = self._pixmap.copy(crop.toRect()).scaled(
            target,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        painter.drawPixmap(rect.topLeft(), scaled)

    def _draw_typeset(self, painter: QPainter, rect: QRectF) -> None:
        """A cover for documents without a page picture: colour, title, and kind."""
        digest = hashlib.sha256(self._record.doc_id.encode()).digest()
        top, bottom = _COVER_COLOURS[digest[0] % len(_COVER_COLOURS)]
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(top))
        gradient.setColorAt(1, QColor(bottom))
        painter.fillRect(rect, gradient)
        glyph = glyph_pixmap(
            Glyph.LINK if self._kind == "Web page" else Glyph.NEW_TEXT,
            QColor(255, 255, 255, 40),
            96,
            self.devicePixelRatioF(),
        )
        painter.drawPixmap(int(rect.right() - 84), int(rect.bottom() - 84), glyph)
        font = QFont(self.font())
        font.setPointSizeF(12.5)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        text_rect = rect.adjusted(14, 16, -14, -40)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self._record.title,
        )
        small = QFont(self.font())
        small.setPointSizeF(7.5)
        small.setWeight(QFont.Weight.DemiBold)
        small.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        painter.setFont(small)
        painter.setPen(QColor(255, 255, 255, 190))
        painter.drawText(
            rect.adjusted(14, 0, -14, -14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            self._kind.upper(),
        )


def _trimmed(pixmap: QPixmap) -> QPixmap:
    """Crop away blank margins around a page picture, so the cover shows the content."""
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8, count=stride * height)
    ink = pixels.reshape(height, stride)[:, :width] < 235
    rows = np.flatnonzero(ink.mean(axis=1) > 0.004)
    columns = np.flatnonzero(ink.mean(axis=0) > 0.004)
    if rows.size == 0 or columns.size == 0:
        return pixmap
    margin = 4
    left, right = max(0, columns[0] - margin), min(width, columns[-1] + margin + 1)
    top, bottom = max(0, rows[0] - margin), min(height, rows[-1] + margin + 1)
    if (right - left) * (bottom - top) > 0.9 * width * height:
        return pixmap  # Hardly any margin: keep the whole page.
    if right - left < 0.4 * width or bottom - top < 0.4 * height:
        return pixmap  # A nearly empty page: trimming would blow up a few lines.
    return pixmap.copy(int(left), int(top), int(right - left), int(bottom - top))


class _ProgressLine(QWidget):
    """A thin, rounded progress bar."""

    def __init__(self, value: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self.setFixedHeight(3)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the track and the read portion."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(QColor(128, 128, 128, 50))
        painter.drawRoundedRect(rect, 1.5, 1.5)
        if self._value > 0:
            painter.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
            painter.drawRoundedRect(QRectF(0, 0, max(3.0, rect.width() * self._value), 3), 1.5, 1.5)
        painter.end()


class DocumentCard(QFrame):
    """A recently read document: cover, title, details, and progress."""

    clicked = Signal(str)  # Path or web address.
    remove_requested = Signal(str)  # Document id.

    def __init__(self, record: DocumentRecord, cover: Path | None) -> None:
        super().__init__()
        self.setObjectName("doc-card")
        self.record = record
        self._is_link = record.path is not None and is_web_address(record.path)
        path = Path(record.path) if record.path and not self._is_link else None
        self._available = self._is_link or (path is not None and path.is_file())
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self._available else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(record.path or "")
        self.setFixedWidth(_CARD_WIDTH)
        if self._is_link:
            kind = "Web page"
        elif path is not None and path.suffix.lower() in (".docx",):
            kind = "Word document"
        elif path is not None and path.suffix.lower() in (".epub", ".mobi", ".fb2"):
            kind = "Book"
        else:
            kind = "Document"
        self._cover = _Cover(record, cover if self._available else None, kind)

        title = QLabel(record.title)
        title.setObjectName("card-title")
        title.setWordWrap(True)
        title.setMaximumHeight(title.fontMetrics().lineSpacing() * 2 + 4)
        title.setFixedWidth(_COVER_WIDTH)
        details = QLabel(self._details())
        details.setObjectName("card-meta")

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 2, 8, 10)
        column.setSpacing(5)
        column.addWidget(self._cover)
        column.addSpacing(4)
        column.addWidget(title)
        column.addWidget(details)
        if self._available and record.progress > 0:
            column.addSpacing(2)
            column.addWidget(_ProgressLine(record.progress))
        column.addStretch()
        if not self._available:
            self.setEnabled(False)

    def _details(self) -> str:
        if not self._available:
            return "File not found"
        parts = []
        if self._is_link:
            parts.append("Web page")
        if self.record.scanned:
            parts.append("Scanned")
        if self.record.position is not None and self.record.page_count:
            parts.append(f"Page {self.record.position.page} of {self.record.page_count}")
        elif self.record.page_count:
            parts.append(f"{self.record.page_count} pages")
        if self.record.progress >= 0.995:
            parts.append("Finished")
        elif self.record.progress > 0:
            parts.append(f"{self.record.progress:.0%}")
        return "  \u00b7  ".join(parts) or "Not started"

    def enterEvent(self, event: QEnterEvent) -> None:
        """Lift the cover under the pointer."""
        if self._available:
            self._cover.hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Let the cover settle again."""
        self._cover.hover(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Open the document."""
        if event.button() == Qt.MouseButton.LeftButton and self._available and self.record.path:
            self.clicked.emit(self.record.path)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Offer to open the document or remove it from the list."""
        menu = QMenu(self)
        if self._available and self.record.path:
            path = self.record.path
            menu.addAction("Open", lambda: self.clicked.emit(path))
            menu.addSeparator()
        menu.addAction(
            "Remove from Recents", lambda: self.remove_requested.emit(self.record.doc_id)
        )
        menu.exec(event.globalPos())


class _QuickStart(QFrame):
    """A small starting point: a tinted icon, a title, and one line of detail."""

    clicked = Signal()

    def __init__(self, glyph: Glyph, title: str, detail: str) -> None:
        super().__init__()
        self.setObjectName("quick-start")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._glyph = glyph
        self._icon = QLabel()
        self._icon.setObjectName("quick-icon")
        self._icon.setFixedSize(40, 40)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel(title)
        heading.setObjectName("quick-title")
        line = QLabel(detail)
        line.setObjectName("quick-detail")
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addStretch()
        text.addWidget(heading)
        text.addWidget(line)
        text.addStretch()
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 16, 12)
        row.setSpacing(12)
        row.addWidget(self._icon)
        row.addLayout(text, 1)
        _shadow(self, 16, 2, 18)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        """Draw the icon in the theme's accent colour."""
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        self._icon.setPixmap(glyph_pixmap(self._glyph, accent, 20, self.devicePixelRatioF()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Feedback on press, at once."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.setProperty("pressed", True)
            self.style().polish(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit on release, if the pointer is still over the tile."""
        self.setProperty("pressed", False)
        self.style().polish(self)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _PasteCard(QFrame):
    """The composer: paste or type text (or a link), then listen."""

    listen_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("composer")
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("composer-editor")
        self.editor.setPlaceholderText(
            "Paste an article, an email, notes, or a web link \u2014 anything you'd like to hear"
        )
        self.editor.setFixedHeight(66)
        self.editor.setTabChangesFocus(True)
        self.editor.textChanged.connect(self._update)
        paste = QPushButton("Paste")
        paste.setObjectName("link-button")
        paste.setCursor(Qt.CursorShape.PointingHandCursor)
        paste.setToolTip("Paste what you copied")
        paste.clicked.connect(
            lambda: self.editor.insertPlainText(QGuiApplication.clipboard().text())
        )
        self._listen = QToolButton()
        self._listen.setObjectName("composer-listen")
        self._listen.setFixedSize(40, 40)
        self._listen.setIconSize(QSize(16, 16))
        self._listen.setToolTip("Listen")
        self._listen.setCursor(Qt.CursorShape.PointingHandCursor)
        self._listen.clicked.connect(self._emit)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 8, 10, 8)
        row.setSpacing(8)
        row.addWidget(self.editor, 1)
        row.addWidget(paste, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._listen, 0, Qt.AlignmentFlag.AlignVCenter)
        _shadow(self, 24, 4, 26)
        self.refresh_icon()
        self._update()

    def refresh_icon(self) -> None:
        """Draw the play icon in white on the accent button."""
        self._listen.setIcon(
            QIcon(glyph_pixmap(Glyph.PLAY, QColor("white"), 16, self.devicePixelRatioF()))
        )

    def _update(self) -> None:
        self._listen.setEnabled(bool(self.editor.toPlainText().strip()))

    def _emit(self) -> None:
        text = self.editor.toPlainText()
        if text.strip():
            self.listen_requested.emit(text)
            self.editor.clear()


class HomeView(QScrollArea):
    """The home page."""

    open_requested = Signal()
    open_link_requested = Signal()
    paste_requested = Signal()
    open_path_requested = Signal(str)
    listen_text_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("home")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("home-page")
        self._date = QLabel()
        self._date.setObjectName("home-date")
        self._title = QLabel()
        self._title.setObjectName("home-title")
        subtitle = QLabel("Pick up where you left off, or start something new.")
        subtitle.setObjectName("home-subtitle")

        self.paste_card = _PasteCard()
        self.paste_card.listen_requested.connect(self.listen_text_requested)

        self._quick = [
            _QuickStart(Glyph.OPEN, "Open a document", "PDF, EPUB, Word, or a web page"),
            _QuickStart(Glyph.LINK, "Open a link", "An article or an online PDF"),
            _QuickStart(Glyph.PASTE, "Read the clipboard", "Whatever you copied last"),
        ]
        self._quick[0].clicked.connect(self.open_requested)
        self._quick[1].clicked.connect(self.open_link_requested)
        self._quick[2].clicked.connect(self.paste_requested)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(14)
        for tile in self._quick:
            quick_row.addWidget(tile)

        recent_header = QHBoxLayout()
        recent_title = QLabel("Continue listening")
        recent_title.setObjectName("section-title")
        self._count = QLabel()
        self._count.setObjectName("home-subtitle")
        recent_header.addWidget(recent_title)
        recent_header.addStretch()
        recent_header.addWidget(self._count, 0, Qt.AlignmentFlag.AlignBottom)

        self._empty = QFrame()
        self._empty.setObjectName("empty-state")
        empty_text = QLabel(
            "Documents you open will appear here as covers, ready to pick up where you left off."
        )
        empty_text.setObjectName("home-subtitle")
        empty_text.setWordWrap(True)
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(24, 34, 24, 34)
        empty_layout.addWidget(empty_text)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(_GRID_SPACING)
        self._grid.setVerticalSpacing(_GRID_SPACING)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._cards: list[DocumentCard] = []

        self._content = QWidget()
        self._content.setMaximumWidth(_CONTENT_MAX_WIDTH)
        column = QVBoxLayout(self._content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._date)
        column.addSpacing(2)
        column.addWidget(self._title)
        column.addSpacing(4)
        column.addWidget(subtitle)
        column.addSpacing(26)
        column.addWidget(self.paste_card)
        column.addSpacing(16)
        column.addLayout(quick_row)
        column.addSpacing(40)
        column.addLayout(recent_header)
        column.addSpacing(14)
        column.addWidget(self._empty)
        column.addWidget(self._grid_host)
        column.addStretch()

        # Content keeps a comfortable width, centred on wide windows.
        outer = QHBoxLayout(page)
        outer.setContentsMargins(48, 36, 48, 150)  # Room for the floating player.
        outer.addStretch()
        outer.addWidget(self._content, 100)
        outer.addStretch()
        page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setWidget(page)
        self.set_recents([], lambda _doc_id: None)

    def refresh_style(self) -> None:
        """Redraw icons after the theme changed."""
        for tile in self._quick:
            tile.refresh_icon()
        self.paste_card.refresh_icon()

    def set_recents(
        self, records: list[DocumentRecord], cover_for: Callable[[str], Path | None]
    ) -> None:
        """Show ``records`` as cards; ``cover_for(doc_id)`` gives each cover image path."""
        now = datetime.now()
        self._date.setText(f"{now:%A}, {now:%B} {now.day}".upper())
        self._title.setText(greeting(now.hour))
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        for record in records:
            card = DocumentCard(record, cover_for(record.doc_id))
            card.clicked.connect(self.open_path_requested)
            card.remove_requested.connect(self.remove_requested)
            self._cards.append(card)
        self._empty.setVisible(not records)
        self._grid_host.setVisible(bool(records))
        self._count.setText(
            "" if not records else f"{len(records)} document{'s' if len(records) != 1 else ''}"
        )
        self._arrange()
        self.verticalScrollBar().setValue(0)

    def cards(self) -> list[DocumentCard]:
        """Return the document cards shown."""
        return list(self._cards)

    def _arrange(self) -> None:
        width = min(self.viewport().width() - 96, _CONTENT_MAX_WIDTH)
        columns = max(1, (width + _GRID_SPACING) // (_CARD_WIDTH + _GRID_SPACING))
        for card in self._cards:
            self._grid.removeWidget(card)
        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // columns, i % columns)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Reflow the cards to the new width."""
        super().resizeEvent(event)
        self._arrange()
