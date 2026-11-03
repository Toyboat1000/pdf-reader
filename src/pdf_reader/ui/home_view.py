"""The home page: start something new, or continue where you left off.

Two calm starting points sit at the top (open a PDF, or paste text), and below them
the recently read documents appear as covers made from their first page, with a
slim bar showing how far you've got. Everything is one click away.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QGuiApplication,
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
    QVBoxLayout,
    QWidget,
)

from pdf_reader.library import DocumentRecord
from pdf_reader.ui.icons import Glyph, make_icon

_CARD_WIDTH = 176
_COVER_HEIGHT = 204
_GRID_SPACING = 22


def greeting(hour: int) -> str:
    """Return a friendly greeting for the hour of the day."""
    if hour < 5:
        return "Good evening"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


class _Cover(QWidget):
    """A document's first page, with rounded corners and a soft shadow."""

    def __init__(self, image: Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_CARD_WIDTH, _COVER_HEIGHT)
        self._pixmap = QPixmap(str(image)) if image is not None and image.exists() else None
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the cover image (or a placeholder) clipped to rounded corners."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 10, 10)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(255, 255, 255))
        if self._pixmap is not None and not self._pixmap.isNull():
            # Fill the card width; crop the bottom of tall pages.
            scaled = self._pixmap.scaledToWidth(
                int(rect.width() * self.devicePixelRatioF()),
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            painter.drawPixmap(0, 0, scaled)
        else:
            icon = make_icon(Glyph.OPEN, self).pixmap(QSize(40, 40))
            painter.drawPixmap(int(rect.center().x() - 20), int(rect.center().y() - 20), icon)
        painter.setClipping(False)
        painter.setPen(QColor(128, 128, 128, 60))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.end()


class _ProgressLine(QWidget):
    """A thin, rounded progress bar."""

    def __init__(self, value: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self.setFixedHeight(4)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the track and the read portion."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(QColor(128, 128, 128, 60))
        painter.drawRoundedRect(rect, 2, 2)
        if self._value > 0:
            painter.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
            painter.drawRoundedRect(QRectF(0, 0, max(4.0, rect.width() * self._value), 4), 2, 2)
        painter.end()


class DocumentCard(QFrame):
    """A recently read document: cover, title, details, and progress."""

    clicked = Signal(str)  # Path.
    remove_requested = Signal(str)  # Document id.

    def __init__(self, record: DocumentRecord, cover: Path | None) -> None:
        super().__init__()
        self.setObjectName("doc-card")
        self.record = record
        path = Path(record.path) if record.path else None
        self._available = path is not None and path.is_file()
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self._available else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(record.path or "")
        self.setFixedWidth(_CARD_WIDTH + 16)

        title = QLabel(record.title)
        title.setObjectName("card-title")
        title.setWordWrap(True)
        title.setMaximumHeight(title.fontMetrics().lineSpacing() * 2 + 4)
        title.setFixedWidth(_CARD_WIDTH)
        details = QLabel(self._details())
        details.setObjectName("card-meta")

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 10)
        column.setSpacing(6)
        column.addWidget(_Cover(cover if self._available else None))
        column.addSpacing(4)
        column.addWidget(title)
        column.addWidget(details)
        if self._available:
            column.addWidget(_ProgressLine(record.progress))
        if not self._available:
            self.setEnabled(False)

    def _details(self) -> str:
        if not self._available:
            return "File not found"
        parts = []
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

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Open the document."""
        if event.button() == Qt.MouseButton.LeftButton and self._available and self.record.path:
            self.clicked.emit(self.record.path)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Offer to remove the document from the list."""
        menu = QMenu(self)
        if self._available and self.record.path:
            path = self.record.path
            menu.addAction("Open", lambda: self.clicked.emit(path))
        menu.addAction(
            "Remove from Recents", lambda: self.remove_requested.emit(self.record.doc_id)
        )
        menu.exec(event.globalPos())


class _ActionCard(QFrame):
    """A large, clickable starting point (e.g. Open a PDF)."""

    clicked = Signal()

    def __init__(self, glyph: Glyph, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("drop-card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        icon = QLabel()
        icon.setPixmap(make_icon(glyph, self).pixmap(QSize(34, 34)))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel(title)
        heading.setObjectName("card-heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QLabel(subtitle)
        detail.setObjectName("card-meta")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 24)
        column.addStretch()
        column.addWidget(icon)
        column.addSpacing(8)
        column.addWidget(heading)
        column.addWidget(detail)
        column.addStretch()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Trigger the action."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _PasteCard(QFrame):
    """Type or paste text, then listen."""

    listen_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("paste-card")
        heading = QLabel("Paste or type text")
        heading.setObjectName("card-heading")
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("paste-editor")
        self.editor.setPlaceholderText(
            "Paste an article, an email, notes \u2014 anything you'd like to hear\u2026"
        )
        self.editor.textChanged.connect(self._update)
        paste = QPushButton("Paste from Clipboard")
        paste.setObjectName("link-button")
        paste.setCursor(Qt.CursorShape.PointingHandCursor)
        paste.clicked.connect(
            lambda: self.editor.insertPlainText(QGuiApplication.clipboard().text())
        )
        self._listen = QPushButton("\u25b6  Listen")
        self._listen.setObjectName("primary-button")
        self._listen.setCursor(Qt.CursorShape.PointingHandCursor)
        self._listen.clicked.connect(self._emit)
        row = QHBoxLayout()
        row.addWidget(paste)
        row.addStretch()
        row.addWidget(self._listen)
        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 16)
        column.setSpacing(10)
        column.addWidget(heading)
        column.addWidget(self.editor, 1)
        column.addLayout(row)
        self._update()

    def _update(self) -> None:
        self._listen.setEnabled(bool(self.editor.toPlainText().strip()))

    def _emit(self) -> None:
        text = self.editor.toPlainText()
        if text.strip():
            self.listen_requested.emit(text)


class HomeView(QScrollArea):
    """The home page."""

    open_requested = Signal()
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
        self._title = QLabel()
        self._title.setObjectName("home-title")
        subtitle = QLabel("Pick up where you left off, or start something new.")
        subtitle.setObjectName("home-subtitle")

        open_card = _ActionCard(
            Glyph.OPEN,
            "Open a PDF",
            "Click to browse, or drop a file anywhere.\nScanned PDFs work too.",
        )
        open_card.clicked.connect(self.open_requested)
        self.paste_card = _PasteCard()
        self.paste_card.listen_requested.connect(self.listen_text_requested)
        starters = QHBoxLayout()
        starters.setSpacing(20)
        starters.addWidget(open_card, 2)
        starters.addWidget(self.paste_card, 3)
        open_card.setFixedHeight(190)
        self.paste_card.setFixedHeight(190)

        recent_title = QLabel("Continue listening")
        recent_title.setObjectName("section-title")
        self._empty = QLabel("Documents you open will appear here, ready to pick up again.")
        self._empty.setObjectName("home-subtitle")
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(_GRID_SPACING)
        self._grid.setVerticalSpacing(_GRID_SPACING)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._cards: list[DocumentCard] = []

        self._column = QVBoxLayout(page)
        self._column.setContentsMargins(48, 36, 48, 150)  # Room for the floating player.
        self._column.setSpacing(0)
        self._column.addWidget(self._title)
        self._column.addSpacing(4)
        self._column.addWidget(subtitle)
        self._column.addSpacing(28)
        self._column.addLayout(starters)
        self._column.addSpacing(34)
        self._column.addWidget(recent_title)
        self._column.addSpacing(16)
        self._column.addWidget(self._empty)
        self._column.addWidget(self._grid_host)
        self._column.addStretch()
        page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setWidget(page)
        self.set_recents([], lambda _doc_id: None)

    def set_recents(
        self, records: list[DocumentRecord], cover_for: Callable[[str], Path | None]
    ) -> None:
        """Show ``records`` as cards; ``cover_for(doc_id)`` gives each cover image path."""
        self._title.setText(greeting(datetime.now().hour))
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        for record in records:
            cover = cover_for(record.doc_id)
            card = DocumentCard(record, cover)
            card.clicked.connect(self.open_path_requested)
            card.remove_requested.connect(self.remove_requested)
            self._cards.append(card)
        self._empty.setVisible(not records)
        self._grid_host.setVisible(bool(records))
        self._arrange()

    def cards(self) -> list[DocumentCard]:
        """Return the document cards shown."""
        return list(self._cards)

    def _arrange(self) -> None:
        width = self.viewport().width() - 96
        columns = max(1, (width + _GRID_SPACING) // (_CARD_WIDTH + 16 + _GRID_SPACING))
        for card in self._cards:
            self._grid.removeWidget(card)
        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // columns, i % columns)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Reflow the cards to the new width."""
        super().resizeEvent(event)
        self._arrange()
