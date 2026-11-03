"""A light-touch style sheet that gives the native Windows look a more polished feel.

Only the toolbar, slider, and status bar are styled; menus, dialogs, and combo boxes
keep the native Windows 11 style so everything still feels familiar. Colours come
from the palette, so light and dark mode both work.
"""

STYLE_SHEET = """
QToolBar#playback-toolbar {
    spacing: 4px;
    padding: 6px 10px;
    border: none;
}
QToolBar#playback-toolbar QToolButton {
    border: none;
    border-radius: 8px;
    padding: 6px;
    margin: 1px;
}
QToolBar#playback-toolbar QToolButton:hover {
    background: rgba(128, 128, 128, 0.18);
}
QToolBar#playback-toolbar QToolButton:pressed,
QToolBar#playback-toolbar QToolButton:checked {
    background: rgba(128, 128, 128, 0.28);
}
QToolButton#play-button {
    background: palette(highlight);
    border-radius: 18px;
    padding: 8px;
    margin: 0 4px;
}
QToolButton#play-button:hover {
    background: palette(link);
}
QToolButton#play-button:disabled {
    background: rgba(128, 128, 128, 0.25);
}
QSlider::groove:horizontal {
    height: 4px;
    border-radius: 2px;
    background: rgba(128, 128, 128, 0.35);
}
QSlider::sub-page:horizontal {
    height: 4px;
    border-radius: 2px;
    background: palette(highlight);
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: palette(highlight);
    border: 2px solid palette(base);
}
QStatusBar {
    padding: 2px 8px;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    padding: 0 6px;
}
"""
