"""The scrolling text panel that shows the document and highlights the spoken sentence."""

import bisect

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPalette,
    QResizeEvent,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QWheelEvent,
)
from PySide6.QtWidgets import QTextEdit, QWidget

from pdf_reader.core.document import ReadingDocument

_MAX_TEXT_WIDTH = 820

_PLAYER_CLEARANCE = 130
"""Pixels kept free under the text for the floating player capsule."""
"""Widest reading column in pixels; wider windows get side margins."""

_CLICK_TOLERANCE = 6
"""A press and release closer than this (pixels) counts as a click, not a drag."""


class DocumentView(QTextEdit):
    """Read-only view of the document text, one paragraph per text block.

    Clicking a sentence emits :attr:`sentence_clicked`; :meth:`highlight` marks the
    sentence being read and scrolls it into view.
    """

    sentence_clicked = Signal(int)
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        # Drag to select and copy; a plain click reads from the clicked sentence.
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setUndoRedoEnabled(False)
        # Keyboard focus stays on the window so Space and the arrow keys always
        # control playback; the mouse wheel still scrolls.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPlaceholderText("Open a PDF with Ctrl+O, or drag one onto this window.")
        self.setFont(QFont("Segoe UI", 12))
        # Fill the side margins (see resizeEvent) with the text background colour.
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, palette.color(QPalette.ColorRole.Base))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.document().setDocumentMargin(24)

        self._starts: list[int] = []
        self._ends: list[int] = []
        self._current = -1
        self._bookmarked: set[int] = set()
        self._press_pos: QPoint | None = None
        self._side_margin = 0
        self._zoom = 1.0
        self._document: ReadingDocument | None = None
        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(250)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ---------------------------------------------------------------- content

    @property
    def zoom(self) -> float:
        """Return the text zoom level (1.0 = normal size)."""
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        """Scale the text, keeping the highlight, bookmarks, and scroll position."""
        zoom = max(0.6, min(3.0, zoom))
        if abs(zoom - self._zoom) < 1e-3:
            return
        self._zoom = zoom
        self.setFont(QFont("Segoe UI", round(12 * zoom, 1)))
        self._side_margin = -1  # Recompute for the wider reading column.
        self.resizeEvent(QResizeEvent(self.size(), self.size()))
        if self._document is not None:
            bar = self.verticalScrollBar()
            fraction = bar.value() / max(bar.maximum(), 1)
            current, bookmarked = self._current, self._bookmarked
            self.set_document(self._document)
            self._bookmarked = bookmarked
            self._current = current
            self._refresh_marks()
            bar.setValue(int(fraction * bar.maximum()))
        self.zoom_changed.emit(zoom)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl + wheel zooms the text; the wheel alone scrolls."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self._zoom * (1.1 ** (event.angleDelta().y() / 120)))
            event.accept()
        else:
            super().wheelEvent(event)

    def selected_text(self) -> str:
        """Return the selected text with ordinary line breaks."""
        return self.textCursor().selectedText().replace("\u2029", "\n")

    def set_document(self, document: ReadingDocument) -> None:
        """Show ``document``, replacing any previous content."""
        self._document = document
        self._current = -1
        self._bookmarked = set()
        self._starts.clear()
        self._ends.clear()
        self.setExtraSelections([])

        text_doc = self.document()
        text_doc.clear()
        text_doc.setDefaultFont(self.font())
        cursor = QTextCursor(text_doc)
        cursor.beginEditBlock()

        body_block = QTextBlockFormat()
        body_block.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        body_block.setBottomMargin(12)
        body_char = QTextCharFormat()

        heading_block = QTextBlockFormat()
        heading_block.setTopMargin(18)
        heading_block.setBottomMargin(8)
        heading_char = QTextCharFormat()
        heading_char.setFontWeight(QFont.Weight.DemiBold)
        # Small, tracked capitals: a quiet label that never competes with the text.
        heading_char.setFontCapitalization(QFont.Capitalization.AllUppercase)
        heading_char.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
        heading_char.setFontLetterSpacing(1.2)
        heading_char.setFontPointSize(round(9 * self._zoom, 1))
        heading_char.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))

        first = True
        last_page = None
        last_block = None
        for sentence in document.sentences:
            if document.is_paginated and sentence.page != last_page:
                if not first:
                    cursor.insertBlock()
                cursor.setBlockFormat(heading_block)
                cursor.insertText(f"Page {sentence.page}", heading_char)
                cursor.insertBlock(body_block, body_char)
                last_page, last_block = sentence.page, sentence.block
            elif first:
                cursor.setBlockFormat(body_block)
                last_block = sentence.block
            elif sentence.block != last_block:
                cursor.insertBlock(body_block, body_char)
                last_block = sentence.block
            elif not first:
                cursor.insertText(" ", body_char)
            first = False
            self._starts.append(cursor.position())
            cursor.insertText(sentence.text, body_char)
            self._ends.append(cursor.position())

        cursor.endEditBlock()
        # Room at the end so the last lines can scroll clear of the floating player.
        frame = text_doc.rootFrame().frameFormat()
        frame.setBottomMargin(_PLAYER_CLEARANCE)
        text_doc.rootFrame().setFrameFormat(frame)
        self.verticalScrollBar().setValue(0)

    def clear_document(self) -> None:
        """Remove all content and show the placeholder."""
        self._starts.clear()
        self._ends.clear()
        self._current = -1
        self._bookmarked = set()
        self.setExtraSelections([])
        self.clear()

    # ------------------------------------------------------------- highlight

    def highlight(self, index: int) -> None:
        """Highlight sentence ``index`` and scroll it into view if needed."""
        if not 0 <= index < len(self._starts):
            self._current = -1
            self._refresh_marks()
            return
        self._current = index
        self._refresh_marks()
        self._scroll_to(index)

    def set_bookmarked(self, indexes: set[int]) -> None:
        """Mark the sentences at ``indexes`` as bookmarked (shown underlined)."""
        self._bookmarked = {i for i in indexes if 0 <= i < len(self._starts)}
        self._refresh_marks()

    @property
    def bookmarked(self) -> set[int]:
        """Return the indexes of sentences currently marked as bookmarked."""
        return set(self._bookmarked)

    def _refresh_marks(self) -> None:
        """Draw bookmark underlines and the current-sentence highlight."""
        selections = []
        accent = self.palette().color(QPalette.ColorRole.Accent)
        for index in sorted(self._bookmarked):
            mark = QTextEdit.ExtraSelection()
            mark.cursor = self._cursor_for(index)
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DashUnderline)
            fmt.setUnderlineColor(accent)
            mark.format = fmt
            selections.append(mark)
        if self._current >= 0:
            current = QTextEdit.ExtraSelection()
            current.cursor = self._cursor_for(self._current)
            fmt = QTextCharFormat()
            fmt.setBackground(self._highlight_color())
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, False)
            current.format = fmt
            selections.append(current)
        self.setExtraSelections(selections)

    def _highlight_color(self) -> QColor:
        color = QColor(self.palette().color(QPalette.ColorRole.Highlight))
        color.setAlpha(90)
        return color

    def _cursor_for(self, index: int) -> QTextCursor:
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._starts[index])
        cursor.setPosition(self._ends[index], QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def _scroll_to(self, index: int) -> None:
        start = QTextCursor(self.document())
        start.setPosition(self._starts[index])
        end = QTextCursor(self.document())
        end.setPosition(self._ends[index])
        top = self.cursorRect(start).top()
        bottom = self.cursorRect(end).bottom()
        height = self.viewport().height()
        margin = height // 8
        if top >= margin and bottom <= height - margin:
            return  # Already comfortably visible.
        bar = self.verticalScrollBar()
        target = bar.value() + top - height // 3
        target = max(bar.minimum(), min(bar.maximum(), target))
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

    # ----------------------------------------------------------------- events

    def sentence_at(self, pos: QPoint) -> int | None:
        """Return the sentence under viewport position ``pos``, if any."""
        if not self._starts:
            return None
        char = self.cursorForPosition(pos).position()
        i = bisect.bisect_right(self._starts, char) - 1
        if i < 0:
            return 0
        # Between two sentences (a space or page heading) counts as the next one.
        if char > self._ends[i] and i + 1 < len(self._starts):
            return i + 1
        return i

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Remember where a click started."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Emit :attr:`sentence_clicked` for a left click on a sentence."""
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
        if not self.textCursor().hasSelection():
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep a comfortable reading width by adding side margins in wide windows.

        Qt also routes the viewport's own resize events here, and changing the margins
        resizes the viewport. The margins are therefore derived from the widget's
        width (which they don't affect) and only applied when they change.
        """
        side = max(0, (self.width() - int(_MAX_TEXT_WIDTH * self._zoom)) // 2)
        if side != self._side_margin:
            self._side_margin = side
            self.setViewportMargins(side, 0, side, 0)
        super().resizeEvent(event)
