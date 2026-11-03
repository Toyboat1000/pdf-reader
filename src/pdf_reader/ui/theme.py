"""The app's look: system typography, quiet chrome, and floating material layers.

Inspired by Apple's design principles (restraint, hierarchy through weight and size,
depth for floating controls, instant feedback), applied with native Windows type.
Colours come from the palette, so light and dark mode both work; hairlines and
hover tints use neutral translucent greys that read well on either.
"""

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

_UI_FONTS = ("Segoe UI Variable Text", "Segoe UI")

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
QLabel#home-title { font-size: 26pt; font-weight: 600; letter-spacing: -0.6px; }
QLabel#home-subtitle { font-size: 10.5pt; color: palette(placeholder-text); }
QLabel#section-title { font-size: 14pt; font-weight: 600; letter-spacing: -0.2px; }
QLabel#card-heading { font-size: 12pt; font-weight: 600; }
QLabel#card-title { font-size: 9.5pt; font-weight: 600; }
QLabel#card-meta { font-size: 8.5pt; color: palette(placeholder-text); }
QFrame#drop-card {
    border: 2px dashed rgba(128, 128, 128, 0.35);
    border-radius: 18px;
    background: rgba(128, 128, 128, 0.05);
}
QFrame#drop-card:hover {
    border-color: palette(highlight);
    background: rgba(128, 128, 128, 0.10);
}
QFrame#paste-card {
    background: palette(base);
    border: 1px solid rgba(128, 128, 128, 0.22);
    border-radius: 18px;
}
QPlainTextEdit#paste-editor {
    border: none;
    background: transparent;
    font-size: 10.5pt;
}
QFrame#doc-card { border-radius: 14px; background: transparent; }
QFrame#doc-card:hover { background: rgba(128, 128, 128, 0.12); }

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


def apply_theme(app: QApplication) -> None:
    """Use the Windows UI font and the app style sheet."""
    families = set(QFontDatabase.families())
    family = next((name for name in _UI_FONTS if name in families), None)
    if family is not None:
        font = QFont(family)
        font.setPointSizeF(9.5)
        app.setFont(font)
    app.setStyleSheet(STYLE_SHEET)
