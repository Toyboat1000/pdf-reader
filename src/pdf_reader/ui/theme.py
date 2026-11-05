"""The app's look: system typography, quiet chrome, and floating material layers.

Inspired by Apple's design principles (restraint, hierarchy through weight and size,
depth for floating controls, instant feedback), applied with native Windows type.
Colours come from the palette, so every theme works; hairlines and hover tints use
neutral translucent greys that read well on any of them.

Themes: the system's choice, light, sepia (warm paper, easy on the eyes), and dark.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

_UI_FONTS = ("Segoe UI Variable Text", "Segoe UI")
_FONT_DIR = Path(__file__).parent / "fonts"

DYSLEXIC_FONT = "OpenDyslexic"
"""Family name of the bundled dyslexia-friendly font (SIL Open Font License)."""

THEME_LABELS = {"system": "&System", "light": "&Light", "sepia": "S&epia", "dark": "&Dark"}
"""Menu labels of the themes, in menu order."""

SEPIA_PAGE_TINT = QColor(246, 236, 214)
"""Multiplied over page images in the sepia theme: white paper turns warm, ink stays."""

_SEPIA = {
    QPalette.ColorRole.Window: "#f1e7d2",
    QPalette.ColorRole.WindowText: "#4a3b2a",
    QPalette.ColorRole.Base: "#faf3e3",
    QPalette.ColorRole.AlternateBase: "#efe3cb",
    QPalette.ColorRole.Text: "#4a3b2a",
    QPalette.ColorRole.PlaceholderText: "#8c7a63",
    QPalette.ColorRole.Button: "#ece0c6",
    QPalette.ColorRole.ButtonText: "#4a3b2a",
    QPalette.ColorRole.BrightText: "#ffffff",
    QPalette.ColorRole.Highlight: "#a8692f",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.Accent: "#a8692f",
    QPalette.ColorRole.Link: "#8f5524",
    QPalette.ColorRole.LinkVisited: "#7a4a22",
    QPalette.ColorRole.ToolTipBase: "#faf3e3",
    QPalette.ColorRole.ToolTipText: "#4a3b2a",
    QPalette.ColorRole.Light: "#fffaf0",
    QPalette.ColorRole.Midlight: "#f3e9d6",
    QPalette.ColorRole.Mid: "#cdbb9c",
    QPalette.ColorRole.Dark: "#7d5a35",
    QPalette.ColorRole.Shadow: "#5a4630",
}

STYLE_SHEET = """
/* ------------------------------------------------------------ toolbar */
QToolBar#main-toolbar {
    spacing: 2px;
    padding: 6px 12px;
    border: none;
}
QToolBar#main-toolbar QToolButton {
    border: none;
    border-radius: 8px;
    padding: 6px;
    margin: 1px;
}
QToolBar#main-toolbar QToolButton:hover { background: rgba(128, 128, 128, 0.16); }
QToolBar#main-toolbar QToolButton:pressed,
QToolBar#main-toolbar QToolButton:checked { background: rgba(128, 128, 128, 0.26); }
QLabel#title-label { font-size: 10.5pt; font-weight: 600; }
QLabel#subtitle-label { font-size: 8.5pt; color: palette(placeholder-text); }

/* ------------------------------------------------------------- tabs */
QTabBar#doc-tabs { background: transparent; }
QTabBar#doc-tabs::tab {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 5px 8px 5px 12px;
    margin: 3px 2px;
    min-width: 36px;
    max-width: 220px;
    color: palette(placeholder-text);
}
QTabBar#doc-tabs::tab:hover { background: rgba(128, 128, 128, 0.12); color: palette(window-text); }
QTabBar#doc-tabs::tab:selected {
    background: palette(base);
    color: palette(window-text);
    border: 1px solid rgba(128, 128, 128, 0.24);
}
QTabBar#doc-tabs::tab:first { padding: 5px 12px; }
QTabBar#doc-tabs QToolButton#tab-close {
    border: none;
    border-radius: 9px;
    background: transparent;
    padding: 0px;
    margin: 0px 0px 0px 4px;
}
QTabBar#doc-tabs QToolButton#tab-close:hover { background: rgba(128, 128, 128, 0.24); }
QPushButton#now-playing {
    border: none;
    border-radius: 10px;
    padding: 2px 10px;
    background: rgba(128, 128, 128, 0.14);
    color: palette(highlight);
    font-size: 8.5pt;
    font-weight: 600;
}
QPushButton#now-playing:hover { background: rgba(128, 128, 128, 0.24); }

/* ---------------------------------------------------------- loading */
QWidget#loading-view { background: palette(window); }
QLabel#loading-title { font-size: 15pt; font-weight: 600; letter-spacing: -0.2px; }
QLabel#loading-detail { font-size: 9.5pt; color: palette(placeholder-text); }
QProgressBar#loading-bar {
    border: none;
    border-radius: 2px;
    background: rgba(128, 128, 128, 0.18);
}
QProgressBar#loading-bar::chunk { border-radius: 2px; background: palette(highlight); }

/* ------------------------------------------------------ player capsule */
QFrame#player-bar {
    background: palette(base);
    border: 1px solid rgba(128, 128, 128, 0.22);
    border-radius: 26px;
}
QToolButton#player-button {
    border: none;
    border-radius: 17px;
    background: transparent;
}
QToolButton#player-button:hover { background: rgba(128, 128, 128, 0.16); }
QToolButton#player-button:pressed { background: rgba(128, 128, 128, 0.30); }
QToolButton#player-play {
    border: none;
    border-radius: 26px;
    background: palette(highlight);
}
QToolButton#player-play:hover { background: palette(link); }
QToolButton#player-play:pressed { background: palette(dark); }
QToolButton#player-play:disabled { background: rgba(128, 128, 128, 0.25); }
QToolButton#player-pill {
    border: 1px solid rgba(128, 128, 128, 0.30);
    border-radius: 14px;
    padding: 4px 12px;
    font-weight: 600;
}
QToolButton#player-pill:hover { background: rgba(128, 128, 128, 0.14); }
QToolButton#player-pill::menu-indicator { image: none; width: 0px; }
QLabel#player-meta { font-size: 8.5pt; color: palette(placeholder-text); }
QLabel#player-time { font-size: 8.5pt; color: palette(placeholder-text); }

/* ------------------------------------------------------- speed popover */
QWidget#speed-panel { background: transparent; }
QLabel#popover-title { font-weight: 600; }
QLabel#popover-value { font-weight: 600; color: palette(highlight); }
QPushButton#speed-chip {
    border: 1px solid rgba(128, 128, 128, 0.30);
    border-radius: 12px;
    padding: 4px 10px;
    background: transparent;
}
QPushButton#speed-chip:hover { background: rgba(128, 128, 128, 0.16); }
QPushButton#speed-chip:pressed { background: rgba(128, 128, 128, 0.30); }

/* ---------------------------------------------------------- feedback */
QLabel#toast {
    background: rgba(28, 28, 30, 0.92);
    color: white;
    border-radius: 15px;
    padding: 8px 18px;
    font-weight: 600;
}
QFrame#resume-banner {
    background: palette(base);
    border: 1px solid rgba(128, 128, 128, 0.22);
    border-radius: 12px;
    margin: 10px 16px 0 16px;
}

/* ---------------------------------------------------------- home */
QScrollArea#home, QWidget#home-page { background: palette(window); }
QLabel#home-date {
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 0.8px;
    color: palette(placeholder-text);
}
QLabel#home-title { font-size: 28pt; font-weight: 600; letter-spacing: -0.8px; }
QLabel#home-subtitle { font-size: 10.5pt; color: palette(placeholder-text); }
QLabel#section-title { font-size: 15pt; font-weight: 600; letter-spacing: -0.3px; }
QLabel#card-title { font-size: 9.5pt; font-weight: 600; }
QLabel#card-meta { font-size: 8.5pt; color: palette(placeholder-text); }
QFrame#composer {
    background: palette(base);
    border: 1px solid rgba(128, 128, 128, 0.20);
    border-radius: 18px;
}
QFrame#composer:hover { border-color: rgba(128, 128, 128, 0.34); }
QPlainTextEdit#composer-editor {
    border: none;
    background: transparent;
    font-size: 10.5pt;
    padding-top: 4px;
}
QToolButton#composer-listen {
    border: none;
    border-radius: 20px;
    background: palette(highlight);
}
QToolButton#composer-listen:hover { background: palette(link); }
QToolButton#composer-listen:pressed { background: palette(dark); }
QToolButton#composer-listen:disabled { background: rgba(128, 128, 128, 0.28); }
QFrame#quick-start {
    background: palette(base);
    border: 1px solid rgba(128, 128, 128, 0.18);
    border-radius: 14px;
}
QFrame#quick-start:hover { border-color: rgba(128, 128, 128, 0.36); }
QFrame#quick-start[pressed="true"] { background: rgba(128, 128, 128, 0.10); }
QLabel#quick-icon {
    background: rgba(128, 128, 128, 0.12);
    border-radius: 11px;
}
QLabel#quick-title { font-size: 10pt; font-weight: 600; }
QLabel#quick-detail { font-size: 8.5pt; color: palette(placeholder-text); }
QFrame#empty-state {
    border: 1px solid rgba(128, 128, 128, 0.16);
    border-radius: 16px;
    background: rgba(128, 128, 128, 0.04);
}
QFrame#doc-card { border-radius: 12px; background: transparent; }

/* ---------------------------------------------------------- buttons */
QPushButton#primary-button {
    background: palette(highlight);
    color: palette(highlighted-text);
    border: none;
    border-radius: 10px;
    padding: 10px 24px;
    font-weight: 600;
}
QPushButton#primary-button:hover { background: palette(link); }
QPushButton#secondary-button {
    background: rgba(128, 128, 128, 0.16);
    border: none;
    border-radius: 10px;
    padding: 10px 24px;
    font-weight: 600;
}
QPushButton#secondary-button:hover { background: rgba(128, 128, 128, 0.26); }
QPushButton#link-button {
    border: none;
    background: transparent;
    color: palette(link);
    padding: 4px;
}
QPushButton#link-button:hover { text-decoration: underline; }

/* ---------------------------------------------------------- bookmarks */
QDockWidget#bookmarks-dock { font-weight: 600; }
QDockWidget#bookmarks-dock QListWidget {
    border: none;
    background: transparent;
    font-weight: normal;
}
QDockWidget#bookmarks-dock QListWidget::item {
    padding: 8px 10px;
    margin: 2px 0;
    border-radius: 8px;
}
QDockWidget#bookmarks-dock QListWidget::item:hover { background: rgba(128, 128, 128, 0.12); }
QDockWidget#bookmarks-dock QListWidget::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
}

QStatusBar::item { border: none; }
"""


def apply_theme(app: QApplication, theme: str = "system") -> None:
    """Use the Windows UI font, the colours of ``theme``, and the app style sheet.

    Can be called again at any time to switch themes.
    """
    families = set(QFontDatabase.families())
    family = next((name for name in _UI_FONTS if name in families), None)
    if family is not None:
        font = QFont(family)
        font.setPointSizeF(9.5)
        app.setFont(font)
    hints = QGuiApplication.styleHints()
    if theme == "dark":
        hints.setColorScheme(Qt.ColorScheme.Dark)
    elif theme in ("light", "sepia"):
        hints.setColorScheme(Qt.ColorScheme.Light)
    else:
        hints.unsetColorScheme()
    app.setPalette(sepia_palette() if theme == "sepia" else QPalette())
    app.setStyleSheet(STYLE_SHEET)  # Re-polished so palette() colours update.


def sepia_palette() -> QPalette:
    """Return warm, low-contrast colours that look like paper."""
    palette = QPalette()
    for role, value in _SEPIA.items():
        palette.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#a8977f"))
    return palette


def load_bundled_fonts() -> None:
    """Make the bundled fonts (the dyslexia-friendly font) available to the app."""
    for path in sorted(_FONT_DIR.glob("*.otf")):
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            log.warning("Could not load the font %s", path.name)
