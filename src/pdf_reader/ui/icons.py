"""Toolbar icons drawn from the Windows icon font in the current text colour.

Qt's built-in media icons are dark grey and nearly invisible on a dark toolbar.
Windows 10 and 11 ship an icon font (Segoe Fluent Icons / Segoe MDL2 Assets) whose
glyphs match the native look; drawing them in the palette's text colour keeps them
legible in both light and dark mode. Without the font, Qt's standard icons are used.
"""

from enum import StrEnum

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QStyle, QWidget

_ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
_PIXMAP_SIZE = 64  # Drawn large and scaled down, so it stays crisp on high-DPI screens.


class Glyph(StrEnum):
    """Code points shared by Segoe Fluent Icons and Segoe MDL2 Assets."""

    OPEN = "\ue8e5"
    PLAY = "\ue768"
    PAUSE = "\ue769"
    STOP = "\ue71a"
    PREVIOUS = "\ue892"
    NEXT = "\ue893"
    NEW_TEXT = "\ue8a5"
    PASTE = "\ue77f"
    EDIT = "\ue70f"
    BOOKMARK = "\ue734"
    BOOKMARKS = "\ue8a4"


_FALLBACKS: dict[Glyph, QStyle.StandardPixmap] = {
    Glyph.OPEN: QStyle.StandardPixmap.SP_DialogOpenButton,
    Glyph.PLAY: QStyle.StandardPixmap.SP_MediaPlay,
    Glyph.PAUSE: QStyle.StandardPixmap.SP_MediaPause,
    Glyph.STOP: QStyle.StandardPixmap.SP_MediaStop,
    Glyph.PREVIOUS: QStyle.StandardPixmap.SP_MediaSkipBackward,
    Glyph.NEXT: QStyle.StandardPixmap.SP_MediaSkipForward,
    Glyph.NEW_TEXT: QStyle.StandardPixmap.SP_FileIcon,
    Glyph.PASTE: QStyle.StandardPixmap.SP_FileDialogDetailedView,
    Glyph.EDIT: QStyle.StandardPixmap.SP_FileDialogContentsView,
    Glyph.BOOKMARK: QStyle.StandardPixmap.SP_DialogApplyButton,
    Glyph.BOOKMARKS: QStyle.StandardPixmap.SP_FileDialogListView,
}


def _icon_font_family() -> str | None:
    families = set(QFontDatabase.families())
    return next((name for name in _ICON_FONTS if name in families), None)


def make_icon(glyph: Glyph, widget: QWidget) -> QIcon:
    """Return an icon for ``glyph`` styled for ``widget``'s palette."""
    family = _icon_font_family()
    if family is None:
        return widget.style().standardIcon(_FALLBACKS[glyph])
    palette = widget.palette()
    icon = QIcon()
    for mode, group in (
        (QIcon.Mode.Normal, QPalette.ColorGroup.Active),
        (QIcon.Mode.Disabled, QPalette.ColorGroup.Disabled),
    ):
        color = palette.color(group, QPalette.ColorRole.WindowText)
        icon.addPixmap(_render(glyph, family, color), mode)
    return icon


def _render(glyph: Glyph, family: str, color: QColor) -> QPixmap:
    pixmap = QPixmap(_PIXMAP_SIZE, _PIXMAP_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont(family)
    font.setPixelSize(int(_PIXMAP_SIZE * 0.75))
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(
        QRectF(0, 0, _PIXMAP_SIZE, _PIXMAP_SIZE), Qt.AlignmentFlag.AlignCenter, glyph.value
    )
    painter.end()
    return pixmap
