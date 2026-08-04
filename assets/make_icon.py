"""One-off generator for the app and menu bar icons (run manually, not at runtime).

A 2×2 grid of tiles on a teal gradient: the app is a set of other apps. Kept to
four large shapes on purpose — a busier mark turns to mush at 16px.

The menu bar needs the same mark drawn differently: solid black on transparent,
no tile, no gradient. macOS treats that as a template image and recolours it for
a light or dark menu bar, which is why the colour here is thrown away.

    python assets/make_icon.py

Drawn with QPainter rather than PIL so icon generation needs nothing the app
does not already depend on. Each size is rendered natively instead of being
downsampled from one master, which keeps the corners crisp when small.
"""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
)

ASSETS = Path(__file__).resolve().parent
ICONSET = ASSETS / "icon.iconset"

TEAL_TOP = QColor("#2BB3A3")
TEAL_BOTTOM = QColor("#146E75")
WHITE = QColor("#FFFFFF")
DIM = QColor(255, 255, 255, 150)

SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


BLACK = QColor("#000000")

# macOS menu bar art is ~18pt; @2x covers Retina.
TRAY_SIZES = {"tray.png": 18, "tray@2x.png": 36}


def _grid(painter: QPainter, size: int, fills: list[QColor], margin_ratio: float) -> None:
    """The 2×2 mark. The gap is what reads as 'separate things' when small, so
    it stays proportionally wide rather than shrinking to a hairline."""
    margin = size * margin_ratio
    gap = size * 0.09
    cell = (size - margin * 2 - gap) / 2
    radius = cell * 0.28

    painter.setPen(Qt.PenStyle.NoPen)
    for index, (row, column) in enumerate([(0, 0), (0, 1), (1, 0), (1, 1)]):
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(
                margin + column * (cell + gap),
                margin + row * (cell + gap),
                cell,
                cell,
            ),
            radius,
            radius,
        )
        painter.fillPath(path, QBrush(fills[index]))


def draw_tray(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # No dimmed tile: a template image is recoloured wholesale, so a partial
    # alpha reads as a smudge rather than as a fourth tile.
    _grid(painter, size, [BLACK] * 4, margin_ratio=0.10)
    painter.end()
    return image


def draw_icon(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Rounded-square tile with a diagonal gradient.
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, TEAL_TOP)
    gradient.setColorAt(1.0, TEAL_BOTTOM)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    painter.fillPath(tile, QBrush(gradient))

    # One tile dimmed: a flat grid of four identical squares looks like a
    # pattern, not a mark.
    _grid(painter, size, [WHITE, WHITE, WHITE, DIM], margin_ratio=0.24)

    painter.end()
    return image


def main() -> int:
    QGuiApplication([])  # QImage/QPainter need an application instance.
    ICONSET.mkdir(exist_ok=True)

    for name, px in SIZES.items():
        if not draw_icon(px).save(str(ICONSET / name)):
            print(f"Failed to write {name}", file=sys.stderr)
            return 1

    for name, px in TRAY_SIZES.items():
        if not draw_tray(px).save(str(ASSETS / name)):
            print(f"Failed to write {name}", file=sys.stderr)
            return 1

    icns = ASSETS / "icon.icns"
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(icns)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    print(f"Wrote {len(SIZES)} PNGs to {ICONSET}")
    print(f"Wrote {len(TRAY_SIZES)} menu bar PNGs to {ASSETS}")
    print(f"Wrote {icns} ({icns.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
