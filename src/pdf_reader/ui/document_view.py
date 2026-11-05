"""The scrolling text panel that shows the document and highlights the spoken sentence.

The word being spoken is marked within the sentence, word by word.
"""

import bisect
import re

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
"""Widest reading column in pixels; wider windows get side margins."""

_PLAYER_CLEARANCE = 130
"""Pixels kept free under the text for the floating player capsule."""

_WORD = re.compile(r"\S+")

DEFAULT_FONT = "Segoe UI"

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
        self._family = DEFAULT_FONT
        self.setFont(QFont(self._family, 12))
        # Fill the side margins (see resizeEvent) with the text background colour.
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, palette.color(QPalette.ColorRole.Base))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.document().setDocumentMargin(24)

        self._starts: list[int] = []
        self._ends: list[int] = []
        self._current = -1
        self._word: tuple[int, int] | None = None  # (sentence, word) being spoken.
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
        self._restyle()
        self.zoom_changed.emit(zoom)

    def set_font_family(self, family: str) -> None:
        """Show the text in ``family`` (for example a dyslexia-friendly font)."""
        if family != self._family:
            self._family = family
            self._restyle()

    def refresh_colors(self) -> None:
        """Re-apply palette-dependent colours after the theme changed."""
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, palette.color(QPalette.ColorRole.Base))
        self.setPalette(palette)
        self._restyle()

    def _restyle(self) -> None:
        """Lay the text out again with the current font and zoom, keeping the place."""
        self.setFont(QFont(self._family, round(12 * self._zoom, 1)))
        self._side_margin = -1  # Recompute for the wider reading column.
        self.resizeEvent(QResizeEvent(self.size(), self.size()))
        if self._document is not None:
            bar = self.verticalScrollBar()
            fraction = bar.value() / max(bar.maximum(), 1)
            current, bookmarked, word = self._current, self._bookmarked, self._word
            self.set_document(self._document)
            self._bookmarked = bookmarked
            self._current = current
            self._word = word
            self._refresh_marks()
            bar.setValue(int(fraction * bar.maximum()))

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
        self._word = None
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
        self._word = None
        self._bookmarked = set()
        self._document = None
        self.setExtraSelections([])
        self.clear()

    # ------------------------------------------------------------- highlight

    def highlight(self, index: int) -> None:
        """Highlight sentence ``index`` and scroll it into view if needed."""
        if not 0 <= index < len(self._starts):
            self._current = -1
            self._word = None
            self._refresh_marks()
            return
        moved = index != self._current
        if moved:
            self._word = None
        self._current = index
        self._refresh_marks()
        if moved:  # The same sentence again keeps the reader's scroll position.
            self._scroll_to(index)

    def restore_scroll(self, value: int) -> None:
        """Scroll to ``value`` at once, cancelling any scroll in progress."""
        self._scroll_animation.stop()
        self.verticalScrollBar().setValue(value)

    def highlight_word(self, sentence: int, word: int) -> None:
        """Mark word ``word`` (in ``text.split()``) of the current sentence as spoken.

        Ignored unless ``sentence`` is the highlighted sentence; ``word`` -1 removes
        the word mark.
        """
        if sentence != self._current or self._document is None:
            return
        target = (sentence, word) if word >= 0 else None
        if target == self._word:
            return
        self._word = target
        self._refresh_marks()
        span = self._word_span()
        if span is not None:
            self._keep_visible(span[1])

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
        span = self._word_span()
        if self._current >= 0:
            current = QTextEdit.ExtraSelection()
            current.cursor = self._cursor_for(self._current)
            fmt = QTextCharFormat()
            # With a spoken word shown, the sentence steps back so the word stands out.
            fmt.setBackground(self._highlight_color(55 if span is not None else 90))
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, False)
            current.format = fmt
            selections.append(current)
        if span is not None:
            spoken = QTextEdit.ExtraSelection()
            cursor = QTextCursor(self.document())
            cursor.setPosition(span[0])
            cursor.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
            spoken.cursor = cursor
            fmt = QTextCharFormat()
            fmt.setBackground(self._highlight_color(150))
            spoken.format = fmt
            selections.append(spoken)
        self.setExtraSelections(selections)

    def _word_span(self) -> tuple[int, int] | None:
        """Return the document positions of the spoken word, if one is shown."""
        if self._word is None or self._document is None:
            return None
        sentence, word = self._word
        if not 0 <= sentence < len(self._starts):
            return None
        matches = list(_WORD.finditer(self._document.sentences[sentence].text))
        if not 0 <= word < len(matches):
            return None
        start = self._starts[sentence]
        return start + matches[word].start(), start + matches[word].end()

    def _highlight_color(self, alpha: int = 90) -> QColor:
        color = QColor(self.palette().color(QPalette.ColorRole.Highlight))
        color.setAlpha(alpha)
        return color

    def _keep_visible(self, position: int) -> None:
        """Scroll on when the spoken word reaches the bottom of the visible text."""
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        rect = self.cursorRect(cursor)
        height = self.viewport().height()
        if rect.top() >= 0 and rect.bottom() <= height - _PLAYER_CLEARANCE:
            return
        if self._scroll_animation.state() == QPropertyAnimation.State.Running:
            return
        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), bar.value() + rect.top() - height // 3))
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

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
