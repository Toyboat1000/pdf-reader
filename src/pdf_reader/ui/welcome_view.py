"""The calm starting screen shown when no document is open."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from pdf_reader.ui.icons import Glyph, make_icon


class WelcomeView(QWidget):
    """Invites the user to open a PDF, paste text, or drop a file."""

    open_requested = Signal()
    paste_requested = Signal()
    new_text_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome")

        icon = QLabel()
        icon.setPixmap(make_icon(Glyph.HEADPHONES, self).pixmap(QSize(56, 56)))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Listen to anything")
        title.setObjectName("welcome-title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(
            "Open a PDF, paste some text, or drop a file here.\nEverything stays on your computer."
        )
        subtitle.setObjectName("welcome-subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        open_button = QPushButton("Open PDF\u2026")
        open_button.setObjectName("primary-button")
        open_button.clicked.connect(self.open_requested)
        paste_button = QPushButton("Paste Text")
        paste_button.setObjectName("secondary-button")
        paste_button.clicked.connect(self.paste_requested)
        for button in (open_button, paste_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        buttons.addWidget(open_button)
        buttons.addWidget(paste_button)
        buttons.addStretch()

        new_text = QPushButton("or start a new text document")
        new_text.setObjectName("link-button")
        new_text.setCursor(Qt.CursorShape.PointingHandCursor)
        new_text.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        new_text.clicked.connect(self.new_text_requested)

        hints = QLabel("Ctrl+O  Open     Ctrl+V  Paste     Space  Play / Pause")
        hints.setObjectName("welcome-hints")
        hints.setAlignment(Qt.AlignmentFlag.AlignCenter)

        column = QVBoxLayout(self)
        column.addStretch(3)
        column.addWidget(icon)
        column.addSpacing(14)
        column.addWidget(title)
        column.addSpacing(6)
        column.addWidget(subtitle)
        column.addSpacing(22)
        column.addLayout(buttons)
        column.addSpacing(6)
        column.addWidget(new_text, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(4)
        column.addWidget(hints)
        column.addSpacing(110)  # Clear of the floating player.
