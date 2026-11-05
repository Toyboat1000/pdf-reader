"""Document tabs: several documents open at once, one of them being listened to.

The rules, which mirror a web browser playing audio in one tab:

* The first tab is Home and can't be closed; every opened document gets a tab.
* Exactly one tab is the *listening* tab (a speaker icon marks it). The player,
  media keys, and bookmarks act on it.
* While reading aloud, other tabs can be browsed without interrupting it.
* When nothing is playing, the tab being looked at becomes the listening tab, so
  the player always matches what's on screen.
* Pressing Play, or clicking a sentence, on another tab switches listening to it.
"""

import itertools
from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import QTabBar, QToolButton, QWidget

from pdf_reader.core.document import ReadingDocument
from pdf_reader.ui.icons import Glyph, make_icon

_keys = itertools.count(1)


@dataclass(eq=False)
class DocumentTab:
    """An open document (or one still loading) and where its reader is.

    Attributes:
        title: Shown on the tab.
        location: File path or web address it was opened from (``None`` for pasted
            text); used to find an already open document and to restore tabs.
        document: The loaded document, or ``None`` while loading.
        request: The session's id of a load in progress.
        position: Sentence reached in this tab (``None``: never read here yet).
        progress: Loading progress text, e.g. "Reading scanned pages... 3 of 9".
        scroll: Where the tab was scrolled to when last left.
        quiet: Don't announce "continuing where you left off" when it is next read
            (it was only re-read with new settings).
        key: Unique id, stored in the tab bar.
    """

    title: str
    location: str | None = None
    document: ReadingDocument | None = None
    request: int | None = None
    position: int | None = None
    progress: str | None = None
    quiet: bool = False
    scroll: int | None = None
    key: int = field(default_factory=lambda: next(_keys))

    @property
    def loading(self) -> bool:
        """Return whether the document is still being opened."""
        return self.document is None


class TabStrip(QTabBar):
    """The tab bar: a pinned Home tab, then one tab per document."""

    close_requested = Signal(int)
    """The user asked to close the tab with this key."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("doc-tabs")
        self.setDocumentMode(True)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setIconSize(QSize(14, 14))
        self.addTab(make_icon(Glyph.HOME, self), "Home")
        self.setTabData(0, 0)
        self.setTabToolTip(0, "Home: recent documents and new text (Ctrl+H)")

    # --------------------------------------------------------------- tabs

    def add_document_tab(self, tab: DocumentTab) -> int:
        """Append a tab for ``tab`` and return its index."""
        index = self.addTab(tab.title)
        self.setTabData(index, tab.key)
        close = QToolButton(self)
        close.setObjectName("tab-close")
        close.setIcon(make_icon(Glyph.CLOSE, self))
        close.setIconSize(QSize(9, 9))
        close.setFixedSize(18, 18)
        close.setToolTip("Close tab (Ctrl+W)")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(lambda _=False, key=tab.key: self.close_requested.emit(key))
        self.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        self.update_tab(tab, listening=False)
        return index

    def index_of(self, key: int) -> int:
        """Return the index of the tab with ``key``, or -1."""
        return next((i for i in range(self.count()) if self.tabData(i) == key), -1)

    def key_at(self, index: int) -> int:
        """Return the key of the tab at ``index`` (0 for Home)."""
        key = self.tabData(index)
        return key if isinstance(key, int) else 0

    def update_tab(self, tab: DocumentTab, *, listening: bool) -> None:
        """Refresh a tab's title, tooltip, and listening icon."""
        index = self.index_of(tab.key)
        if index < 0:
            return
        self.setTabText(index, tab.title)
        self.setTabToolTip(
            index, (tab.location or tab.title) + ("  \u2014  listening" if listening else "")
        )
        self.setTabIcon(index, make_icon(Glyph.VOLUME, self) if listening else QIcon())

    def refresh_icons(self) -> None:
        """Redraw icons in the current theme's colours."""
        self.setTabIcon(0, make_icon(Glyph.HOME, self))
        for i in range(1, self.count()):
            button = self.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(button, QToolButton):
                button.setIcon(make_icon(Glyph.CLOSE, self))

    # -------------------------------------------------------------- mouse

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """A middle click closes a document tab, as in a browser."""
        if event.button() == Qt.MouseButton.MiddleButton:
            index = self.tabAt(event.position().toPoint())
            if index > 0:
                self.close_requested.emit(self.key_at(index))
                return
        super().mouseReleaseEvent(event)
