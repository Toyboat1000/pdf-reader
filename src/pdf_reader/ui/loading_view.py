"""What a tab shows while its document opens: its name and a calm progress line."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class LoadingView(QWidget):
    """A quiet "Opening..." page with an indeterminate progress line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("loading-view")
        self._title = QLabel()
        self._title.setObjectName("loading-title")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail = QLabel()
        self._detail.setObjectName("loading-detail")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bar = QProgressBar()
        self._bar.setObjectName("loading-bar")
        self._bar.setRange(0, 0)  # Indeterminate until there is real progress.
        self._bar.setTextVisible(False)
        self._bar.setFixedSize(220, 4)
        column = QVBoxLayout(self)
        column.addStretch(3)
        column.addWidget(self._title)
        column.addSpacing(6)
        column.addWidget(self._detail)
        column.addSpacing(18)
        column.addWidget(self._bar, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(4)

    def show_loading(self, name: str, detail: str | None = None) -> None:
        """Show that ``name`` is opening, with optional progress such as "3 of 9"."""
        self._title.setText(f"Opening {name}")
        self._detail.setText(detail or "Preparing the text to read aloud\u2026")

    def set_progress(self, done: int, total: int) -> None:
        """Show determinate progress (scanned pages recognized)."""
        if total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(done)
        else:
            self._bar.setRange(0, 0)
