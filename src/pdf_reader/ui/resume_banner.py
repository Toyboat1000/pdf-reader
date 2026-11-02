"""A slim notice above the text: "Continuing where you left off", with a way back."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget


class ResumeBanner(QFrame):
    """Tells the user a reopened document continues where they stopped.

    Emits :attr:`start_over` when the user asks to begin at the start instead. It
    hides itself when dismissed or after either choice.
    """

    start_over = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resume-banner")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "#resume-banner { background: palette(alternate-base); border: none; "
            "border-bottom: 1px solid palette(mid); }"
        )
        self._label = QLabel()
        start_button = QPushButton("Start from the beginning")
        start_button.clicked.connect(self._on_start_over)
        close_button = QToolButton()
        close_button.setText("\u2715")
        close_button.setToolTip("Dismiss")
        close_button.setAutoRaise(True)
        close_button.clicked.connect(self.hide)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 8, 6)
        layout.addWidget(self._label, 1)
        layout.addWidget(start_button)
        layout.addWidget(close_button)
        self.hide()

    def show_resumed(self, page: int | None) -> None:
        """Show the notice; ``page`` is included when the document has pages."""
        where = f" (page {page})" if page is not None else ""
        self._label.setText(f"Continuing where you left off{where}.")
        self.show()

    @property
    def message(self) -> str:
        """Return the text currently shown."""
        return self._label.text()

    def _on_start_over(self) -> None:
        self.hide()
        self.start_over.emit()
