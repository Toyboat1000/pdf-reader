"""Side panel listing the current document's bookmarks."""

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf_reader.library import Bookmark

_ID_ROLE = Qt.ItemDataRole.UserRole


class BookmarksPanel(QDockWidget):
    """Lists bookmarks; double-click or Enter jumps to one.

    Emits ids rather than acting itself, so the window decides what each action does.
    """

    add_requested = Signal()
    jump_requested = Signal(str)
    rename_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Bookmarks", parent)
        self.setObjectName("bookmarks-dock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._list = QListWidget()
        self._list.setWordWrap(True)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_menu)
        self._list.itemActivated.connect(self._on_activated)
        self._list.currentItemChanged.connect(lambda *_: self._update_buttons())

        self._empty = QLabel("No bookmarks yet.\nPress Ctrl+B to bookmark the sentence being read.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet("color: palette(placeholder-text); padding: 12px;")

        self._add_button = QPushButton("Add")
        self._add_button.setToolTip("Bookmark the current sentence (Ctrl+B)")
        self._add_button.clicked.connect(self.add_requested)
        self._rename_button = QPushButton("Rename")
        self._rename_button.clicked.connect(lambda: self._emit_for_current(self.rename_requested))
        self._remove_button = QPushButton("Remove")
        self._remove_button.clicked.connect(lambda: self._emit_for_current(self.remove_requested))

        rename_key = QAction(self._list)
        rename_key.setShortcut(QKeySequence(Qt.Key.Key_F2))
        rename_key.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        rename_key.triggered.connect(lambda: self._emit_for_current(self.rename_requested))
        remove_key = QAction(self._list)
        remove_key.setShortcut(QKeySequence(QKeySequence.StandardKey.Delete))
        remove_key.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove_key.triggered.connect(lambda: self._emit_for_current(self.remove_requested))
        self._list.addActions([rename_key, remove_key])

        buttons = QHBoxLayout()
        buttons.addWidget(self._add_button)
        buttons.addWidget(self._rename_button)
        buttons.addWidget(self._remove_button)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._empty, 1)
        layout.addLayout(buttons)
        self.setWidget(body)
        self.set_bookmarks([], show_pages=True)

    def set_bookmarks(self, bookmarks: list[Bookmark], *, show_pages: bool) -> None:
        """Show ``bookmarks``, keeping the selection if the selected one still exists."""
        selected = self.current_id()
        self._list.clear()
        for bookmark in bookmarks:
            where = f"Page {bookmark.anchor.page}" if show_pages else ""
            text = f"{bookmark.label}\n{where}" if where else bookmark.label
            item = QListWidgetItem(text)
            item.setData(_ID_ROLE, bookmark.id)
            item.setToolTip(bookmark.anchor.text)
            self._list.addItem(item)
            if bookmark.id == selected:
                self._list.setCurrentItem(item)
        has_any = bool(bookmarks)
        self._list.setVisible(has_any)
        self._empty.setVisible(not has_any)
        self._update_buttons()

    def set_can_add(self, enabled: bool) -> None:
        """Enable or disable adding bookmarks (e.g. for pasted text)."""
        self._add_button.setEnabled(enabled)

    def current_id(self) -> str | None:
        """Return the id of the selected bookmark, if any."""
        item = self._list.currentItem()
        value = item.data(_ID_ROLE) if item is not None else None
        return value if isinstance(value, str) else None

    def ids(self) -> list[str]:
        """Return the listed bookmark ids, in order."""
        return [self._list.item(i).data(_ID_ROLE) for i in range(self._list.count())]

    def _update_buttons(self) -> None:
        selected = self.current_id() is not None
        self._rename_button.setEnabled(selected)
        self._remove_button.setEnabled(selected)

    def _emit_for_current(self, signal: Signal) -> None:
        if (bookmark_id := self.current_id()) is not None:
            signal.emit(bookmark_id)

    @Slot(QListWidgetItem)
    def _on_activated(self, item: QListWidgetItem) -> None:
        bookmark_id = item.data(_ID_ROLE)
        if isinstance(bookmark_id, str):
            self.jump_requested.emit(bookmark_id)

    @Slot(QPoint)
    def _show_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        self._list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Go to Bookmark", lambda: self._on_activated(item))
        menu.addAction("Rename...", lambda: self._emit_for_current(self.rename_requested))
        menu.addAction("Remove", lambda: self._emit_for_current(self.remove_requested))
        menu.exec(self._list.viewport().mapToGlobal(pos))
