"""The floating "now playing" capsule: transport, progress, speed, and voice.

It floats over the bottom of the reading area like a material layer, so the page
keeps all the space and scrolls underneath it. Buttons are bound to the window's
actions, so shortcuts, menus, and the capsule always agree.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from pdf_reader.config.settings import MAX_SPEED, MIN_SPEED
from pdf_reader.ui.icons import Glyph, make_icon
from pdf_reader.ui.slim_slider import SlimSlider

SPEED_PRESETS = (0.75, 1.0, 1.5, 2.0, 3.0, 4.0)


def format_speed(value: float) -> str:
    """Format a speed the way the capsule shows it, e.g. "1.25\u00d7"."""
    return f"{value:.2f}\u00d7"


def format_duration(seconds: float) -> str:
    """Format a duration as "4:05" or "1:02:09"."""
    total = max(0, round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_time_left(seconds: float) -> str:
    """Describe the listening time left, e.g. "12 min left" or "1 h 5 min left"."""
    minutes = max(0, round(seconds / 60))
    if seconds < 60:
        return "Less than a minute left"
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min left" if minutes else f"{hours} h left"
    return f"{minutes} min left"


def _button(action: QAction, name: str, size: int, icon_size: int) -> QToolButton:
    button = QToolButton()
    button.setDefaultAction(action)
    button.setObjectName(name)
    button.setFixedSize(size, size)
    button.setIconSize(QSize(icon_size, icon_size))
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class PlayerBar(QFrame):
    """Transport controls, a scrubbable progress slider, and speed and voice pickers.

    Attributes:
        speed_slider: Speed in hundredths (50-200), inside the speed popover.
        speed_label: The selected speed, inside the popover.
        voice_combo: The voice list.
        preview_button: Plays a sample of the selected voice.
        position_label: "Sentence N of M".
        elapsed_label: Estimated listening time so far.
        remaining_label: Estimated listening time left.
        progress_label: Percentage read and time left, under the position.
    """

    seek_requested = Signal(int)
    """The user scrubbed to a sentence (emitted on release)."""

    def __init__(
        self,
        parent: QWidget,
        *,
        previous: QAction,
        play: QAction,
        stop: QAction,
        following: QAction,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("player-bar")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        self.previous_button = _button(previous, "player-button", 38, 18)
        self.play_button = _button(play, "player-play", 52, 22)
        self.next_button = _button(following, "player-button", 38, 18)
        self.stop_button = _button(stop, "player-button", 38, 16)

        self.progress = SlimSlider()
        self.progress.setObjectName("player-progress")
        self.progress.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.progress.setMinimumWidth(160)
        self.progress.setRange(0, 0)
        self.progress.setToolTip("Drag to move through the document")
        self.progress.setCursor(Qt.CursorShape.PointingHandCursor)
        self.progress.sliderMoved.connect(self._show_scrub_position)
        self.progress.sliderReleased.connect(
            lambda: self.seek_requested.emit(self.progress.value())
        )
        self.position_label = QLabel()
        self.position_label.setObjectName("player-meta")
        self.progress_label = QLabel()
        self.progress_label.setObjectName("player-meta")
        self.elapsed_label = QLabel()
        self.elapsed_label.setObjectName("player-time")
        self.elapsed_label.setToolTip("Listened so far (estimated)")
        self.remaining_label = QLabel()
        self.remaining_label.setObjectName("player-time")
        self.remaining_label.setToolTip("Listening time left at this speed (estimated)")
        for label in (self.elapsed_label, self.remaining_label):
            label.setMinimumWidth(44)
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._count = 0
        slider_row = QHBoxLayout()
        slider_row.setSpacing(8)
        slider_row.addWidget(self.elapsed_label)
        slider_row.addWidget(self.progress, 1)
        slider_row.addWidget(self.remaining_label)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.addStretch()
        meta_row.addWidget(self.position_label)
        meta_row.addWidget(self.progress_label)
        meta_row.addStretch()
        progress_column = QVBoxLayout()
        progress_column.setSpacing(2)
        progress_column.addLayout(slider_row)
        progress_column.addLayout(meta_row)

        self.speed_button = QToolButton()
        self.speed_button.setObjectName("player-pill")
        self.speed_button.setToolTip("Reading speed")
        self.speed_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.speed_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.speed_button.setMenu(self._speed_popover())

        self.voice_combo = QComboBox()
        self.voice_combo.setObjectName("player-voice")
        self.voice_combo.setMinimumWidth(170)
        self.voice_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.voice_combo.setToolTip("Voice")
        self.voice_combo.setPlaceholderText("Loading voices...")
        self.preview_button = QToolButton()
        self.preview_button.setObjectName("player-button")
        self.preview_button.setIcon(make_icon(Glyph.VOLUME, self))
        self.preview_button.setIconSize(QSize(16, 16))
        self.preview_button.setFixedSize(34, 34)
        self.preview_button.setToolTip("Hear a short sample of the selected voice")
        self.preview_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_button.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.play_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.stop_button)
        layout.addSpacing(10)
        layout.addLayout(progress_column, 1)
        layout.addSpacing(10)
        layout.addWidget(self.speed_button)
        layout.addSpacing(4)
        layout.addWidget(self.voice_combo)
        layout.addWidget(self.preview_button)

    # ---------------------------------------------------------------- speed

    def _speed_popover(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("speed-popover")
        panel = QWidget()
        panel.setObjectName("speed-panel")
        title = QLabel("Speed")
        title.setObjectName("popover-title")
        self.speed_label = QLabel()
        self.speed_label.setObjectName("popover-value")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.speed_label)

        self.speed_slider = SlimSlider()
        self.speed_slider.setRange(int(MIN_SPEED * 100), int(MAX_SPEED * 100))
        self.speed_slider.setSingleStep(5)
        self.speed_slider.setPageStep(25)
        self.speed_slider.setFixedWidth(300)
        self.speed_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for value in SPEED_PRESETS:
            chip = QPushButton(f"{value:g}\u00d7")
            chip.setObjectName("speed-chip")
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(
                lambda _=False, v=value: self.speed_slider.setValue(round(v * 100))
            )
            presets.addWidget(chip)

        column = QVBoxLayout(panel)
        column.setContentsMargins(16, 12, 16, 14)
        column.setSpacing(10)
        column.addLayout(header)
        column.addWidget(self.speed_slider)
        column.addLayout(presets)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        return menu

    def show_speed(self, value: float) -> None:
        """Show ``value`` on the speed pill and in the popover."""
        text = format_speed(value)
        self.speed_button.setText(text)
        self.speed_label.setText(text)

    # ------------------------------------------------------------- progress

    def set_times(self, listened: float, total: float) -> None:
        """Show estimated listening time so far and left (``total`` 0 clears them)."""
        if total <= 0:
            for label in (self.elapsed_label, self.remaining_label, self.progress_label):
                label.clear()
            return
        left = max(0.0, total - listened)
        self.elapsed_label.setText(format_duration(listened))
        self.remaining_label.setText("\u2212" + format_duration(left))
        share = min(1.0, listened / total)
        self.progress_label.setText(f"\u00b7  {share:.0%}  \u00b7  {format_time_left(left)}")

    def set_document_length(self, count: int) -> None:
        """Set how many sentences the progress slider spans (0 = no document)."""
        self._count = count
        self.progress.setRange(0, max(count - 1, 0))
        self.progress.setEnabled(count > 1)

    def set_position(self, index: int) -> None:
        """Move the progress slider to sentence ``index`` (unless the user is dragging it)."""
        if not self.progress.isSliderDown():
            self.progress.blockSignals(True)
            self.progress.setValue(index)
            self.progress.blockSignals(False)

    def _show_scrub_position(self, value: int) -> None:
        if self._count:
            self.position_label.setText(f"Sentence {value + 1} of {self._count}")
