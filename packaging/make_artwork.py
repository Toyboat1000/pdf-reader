"""Draw the app icon and the installer's artwork (run again after changing the design).

Usage::

    uv run python packaging/make_artwork.py

Writes ``src/pdf_reader/ui/assets/app.png`` and ``app.ico`` (window and taskbar icon)
and ``packaging/assets/*.bmp`` (setup wizard pictures). Everything is drawn here, so
no image editor or downloaded artwork is needed.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from pdf_reader.config.constants import APP_NAME

ROOT = Path(__file__).resolve().parent.parent
APP_ASSETS = ROOT / "src" / "pdf_reader" / "ui" / "assets"
SETUP_ASSETS = ROOT / "packaging" / "assets"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

TOP = QColor("#4f7cff")
BOTTOM = QColor("#6a3df0")


def draw_icon(size: int) -> QImage:
    """Return the icon: a page with sound waves on a rounded blue-violet tile."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256  # Designed on a 256 grid.
    tile = QRectF(8 * s, 8 * s, 240 * s, 240 * s)
    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0, TOP)
    gradient.setColorAt(1, BOTTOM)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(tile, 56 * s, 56 * s)

    # The page, with a folded corner.
    page = QPainterPath()
    left, top, width, height, fold = 46 * s, 58 * s, 100 * s, 140 * s, 30 * s
    page.moveTo(left, top)
    page.lineTo(left + width - fold, top)
    page.lineTo(left + width, top + fold)
    page.lineTo(left + width, top + height)
    page.lineTo(left, top + height)
    page.closeSubpath()
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawPath(page)
    corner = QPainterPath()
    corner.moveTo(left + width - fold, top)
    corner.lineTo(left + width - fold, top + fold)
    corner.lineTo(left + width, top + fold)
    corner.closeSubpath()
    p.setBrush(QColor(210, 205, 255))
    p.drawPath(corner)
    if size >= 32:  # Lines of text; too small to see below this size.
        p.setBrush(QColor(BOTTOM.red(), BOTTOM.green(), BOTTOM.blue(), 150))
        for i, length in enumerate((64, 72, 52, 68)):
            p.drawRoundedRect(
                QRectF(left + 18 * s, top + (44 + i * 22) * s, length * s, 9 * s),
                4.5 * s,
                4.5 * s,
            )

    # Sound waves coming from the page.
    pen = QPen(QColor("white"), max(1.5, 13 * s), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    centre = QPointF(156 * s, 128 * s)
    for radius in (28, 52) if size < 32 else (26, 48, 70):
        r = radius * s
        p.drawArc(QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r), -45 * 16, 90 * 16)
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    """Return ``image`` encoded as PNG."""
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def write_ico(path: Path, sizes: tuple[int, ...]) -> None:
    """Write a Windows .ico holding a PNG image per size."""
    images = [png_bytes(draw_icon(size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in zip(sizes, images, strict=True):
        dimension = 0 if size >= 256 else size  # 0 means 256 in the ICO format.
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(header + entries + b"".join(images))


def draw_wizard(width: int, height: int) -> QImage:
    """The tall picture on the setup wizard's welcome and finish pages."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, width * 0.4, height)
    gradient.setColorAt(0, TOP)
    gradient.setColorAt(1, BOTTOM)
    p.fillRect(image.rect(), gradient)
    icon_size = int(width * 0.62)
    p.drawImage(
        QRectF((width - icon_size) / 2, height * 0.22, icon_size, icon_size),
        draw_icon(512),
    )
    font = QFont("Segoe UI", 1)
    font.setPixelSize(int(width * 0.105))
    font.setWeight(QFont.Weight.DemiBold)
    p.setFont(font)
    p.setPen(QColor("white"))
    text_top = height * 0.22 + icon_size + height * 0.05
    p.drawText(
        QRectF(0, text_top, width, width * 0.16), Qt.AlignmentFlag.AlignHCenter, APP_NAME
    )
    font.setPixelSize(int(width * 0.06))
    font.setWeight(QFont.Weight.Normal)
    p.setFont(font)
    p.setPen(QColor(255, 255, 255, 210))
    p.drawText(
        QRectF(width * 0.08, text_top + width * 0.17, width * 0.84, width * 0.3),
        Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap,
        "Natural voices.\nPrivate and offline.",
    )
    p.end()
    return image


def draw_small(size: int) -> QImage:
    """The small picture at the top right of the setup wizard's other pages."""
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, size, size), draw_icon(256))
    p.end()
    return image


def main() -> None:
    """Write all artwork files."""
    app = QGuiApplication(sys.argv)
    APP_ASSETS.mkdir(parents=True, exist_ok=True)
    SETUP_ASSETS.mkdir(parents=True, exist_ok=True)
    draw_icon(256).save(str(APP_ASSETS / "app.png"))
    write_ico(APP_ASSETS / "app.ico", ICON_SIZES)
    for scale, suffix in ((1, ""), (2, "@2x")):
        draw_wizard(164 * scale, 314 * scale).save(str(SETUP_ASSETS / f"wizard{suffix}.bmp"))
        draw_small(55 * scale).save(str(SETUP_ASSETS / f"wizard-small{suffix}.bmp"))
    del app


if __name__ == "__main__":
    main()
