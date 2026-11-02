"""Dialog for typing or pasting text to read aloud, instead of opening a file."""

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TextInputDialog(QDialog):
    """A text editor where the user pastes or types text, then chooses Read Aloud.

    Ctrl+Enter is a shortcut for Read Aloud. The dialog is accepted only when there
    is some non-blank text; read it back with :meth:`text`.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        text: str = "",
        title: str = "New Text Document",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 520)

        hint = QLabel("Paste or type the text you want to hear, then choose Read Aloud.")
        hint.setWordWrap(True)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Segoe UI", 11))
        self._editor.setPlaceholderText("Paste text here (Ctrl+V)...")
        self._editor.setPlainText(text)
        self._editor.moveCursor(self._editor.textCursor().MoveOperation.End)
        self._editor.textChanged.connect(self._update_buttons)

        paste_button = QPushButton("Paste from Clipboard")
        paste_button.setToolTip("Add the text on the clipboard at the cursor")
        paste_button.clicked.connect(self._paste)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._editor.clear)
        self._count = QLabel()
        self._count.setStyleSheet("color: palette(placeholder-text);")

        tools = QHBoxLayout()
        tools.addWidget(paste_button)
        tools.addWidget(clear_button)
        tools.addStretch()
        tools.addWidget(self._count)

        self._buttons = QDialogButtonBox()
        self._read_button = self._buttons.addButton(
            "Read Aloud", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._read_button.setDefault(True)
        self._read_button.setToolTip("Read this text aloud (Ctrl+Enter)")
        self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self._editor, 1)
        layout.addLayout(tools)
        layout.addWidget(self._buttons)

        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, activated=self.accept)

        self._editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_buttons()

    def text(self) -> str:
        """Return the text as entered."""
        return self._editor.toPlainText()

    def accept(self) -> None:
        """Close with Read Aloud, but only if there is something to read."""
        if self.text().strip():
            super().accept()

    @Slot()
    def _paste(self) -> None:
        self._editor.insertPlainText(QGuiApplication.clipboard().text())
        self._editor.setFocus()

    @Slot()
    def _update_buttons(self) -> None:
        text = self.text()
        self._read_button.setEnabled(bool(text.strip()))
        words = len(text.split())
        self._count.setText(f"{words:,} word{'s' if words != 1 else ''}" if words else "")
