"""Visual theme: one stylesheet, light and dark, plus layout helpers.

The app runs on the Fusion style rather than the native macOS one. Native
widgets fight a stylesheet — and, more importantly, they change layout
behaviour: macOS defaults QFormLayout to FieldsStayAtSizeHint, which pins every
input to its minimum width and elides placeholder text. Fusion behaves the same
everywhere, so what renders in a test matches what ships.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# Width of the readable content column. Without this the form sprawls across a
# 2000px display with the fields marooned in the middle.
CONTENT_WIDTH = 760
LABEL_WIDTH = 168


@dataclass(frozen=True)
class Palette:
    window: str
    card: str
    border: str
    text: str
    muted: str
    field: str
    field_border: str
    accent: str
    accent_text: str
    ok: str
    warn: str
    bad: str


DARK = Palette(
    window="#1B1B1D",
    card="#252528",
    border="#37373B",
    text="#F2F2F5",
    muted="#9B9BA3",  # readable on the card; the old palette(mid) was not
    field="#161618",
    field_border="#45454A",
    accent="#7C5CFF",
    accent_text="#FFFFFF",
    ok="#32D74B",
    warn="#FF9F0A",
    bad="#FF453A",
)

LIGHT = Palette(
    window="#F4F4F6",
    card="#FFFFFF",
    border="#E2E2E7",
    text="#1D1D1F",
    muted="#6B6B73",
    field="#FFFFFF",
    field_border="#D0D0D6",
    accent="#6D4AE0",
    accent_text="#FFFFFF",
    ok="#1E9E42",
    warn="#B26B00",
    bad="#C7362B",
)


_chosen: Palette | None = None


def active() -> Palette:
    """The palette in use — detected from the system appearance at startup."""
    if _chosen is not None:
        return _chosen
    app = QApplication.instance()
    if app is None:
        return DARK
    window = app.palette().color(QPalette.ColorRole.Window)
    return DARK if window.lightness() < 128 else LIGHT


def qpalette(p: Palette) -> QPalette:
    """A real QPalette to back the stylesheet.

    The stylesheet cannot reach everything — selection colours, placeholder
    text, disabled states and anything drawn by the style itself all come from
    here. Without it those fall back to Qt's light-theme defaults and are
    unreadable on a dark card.
    """
    pal = QPalette()
    roles = QPalette.ColorRole
    pal.setColor(roles.Window, QColor(p.window))
    pal.setColor(roles.WindowText, QColor(p.text))
    pal.setColor(roles.Base, QColor(p.field))
    pal.setColor(roles.AlternateBase, QColor(p.card))
    pal.setColor(roles.Text, QColor(p.text))
    pal.setColor(roles.Button, QColor(p.card))
    pal.setColor(roles.ButtonText, QColor(p.text))
    pal.setColor(roles.Highlight, QColor(p.accent))
    pal.setColor(roles.HighlightedText, QColor(p.accent_text))
    pal.setColor(roles.ToolTipBase, QColor(p.card))
    pal.setColor(roles.ToolTipText, QColor(p.text))
    pal.setColor(roles.PlaceholderText, QColor(p.muted))
    # Anchor colour comes from the palette, not from any document stylesheet.
    pal.setColor(roles.Link, QColor(p.accent))
    pal.setColor(roles.LinkVisited, QColor(p.accent))

    # Fusion derives control outlines (checkbox frames, spin arrows) from these.
    # Leaving them at Qt's light-theme defaults makes an unchecked box invisible
    # on a dark card.
    pal.setColor(roles.Light, QColor(p.border))
    pal.setColor(roles.Midlight, QColor(p.border))
    pal.setColor(roles.Mid, QColor(p.field_border))
    pal.setColor(roles.Dark, QColor(p.field_border))
    pal.setColor(roles.Shadow, QColor(p.field_border))

    disabled = QPalette.ColorGroup.Disabled
    for role in (roles.Text, roles.ButtonText, roles.WindowText):
        pal.setColor(disabled, role, QColor(p.muted))
    return pal


# ----------------------------------------------------------------------
# Control glyphs.
#
# Styling ::indicator or ::drop-down hands drawing to the stylesheet, which
# then draws no checkmark and no arrow unless given an image. Fusion's own
# drawing isn't usable either: it derives outlines from the Window colour,
# which is near-black here, so an unchecked box comes out invisible. So the
# glyphs are painted once at startup and referenced by path — no image files
# to ship, and they follow whatever palette is in use.
# ----------------------------------------------------------------------
def _glyph_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "lab-hub-glyphs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _paint(size: int, draw) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw(painter, size)
    painter.end()
    return image


def _check(colour: str):
    def draw(painter: QPainter, size: int) -> None:
        pen = QPen(QColor(colour), max(1.6, size * 0.135))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(size * 0.24, size * 0.52)
        path.lineTo(size * 0.43, size * 0.71)
        path.lineTo(size * 0.77, size * 0.30)
        painter.drawPath(path)

    return draw


def _chevron(colour: str, down: bool = True):
    def draw(painter: QPainter, size: int) -> None:
        pen = QPen(QColor(colour), max(1.4, size * 0.13))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        top, bottom = (size * 0.38, size * 0.62) if down else (size * 0.62, size * 0.38)
        path = QPainterPath()
        path.moveTo(QPointF(size * 0.26, top))
        path.lineTo(QPointF(size * 0.50, bottom))
        path.lineTo(QPointF(size * 0.74, top))
        painter.drawPath(path)

    return draw


def _glyph(name: str, colour: str, draw, base: int = 16) -> str:
    """Write a glyph (plus its @2x variant for Retina) and return its path."""
    stem = f"{name}-{colour.lstrip('#')}"
    path = _glyph_dir() / f"{stem}.png"
    if not path.exists():
        _paint(base, draw).save(str(path))
        _paint(base * 2, draw).save(str(_glyph_dir() / f"{stem}@2x.png"))
    return path.as_posix()


def glyphs(p: Palette) -> dict[str, str]:
    return {
        "check": _glyph("check", p.accent_text, _check(p.accent_text)),
        "check_off": _glyph("check", p.muted, _check(p.muted)),
        "down": _glyph("down", p.muted, _chevron(p.muted, True), base=14),
        "up": _glyph("up", p.muted, _chevron(p.muted, False), base=14),
    }


def stylesheet(p: Palette) -> str:
    g = glyphs(p)
    return f"""
    /* Plain containers stay transparent. Painting every QWidget with the
       window colour drew a dark slab behind each multi-widget form row. */
    QWidget {{
        background: transparent;
        color: {p.text};
        font-size: 13px;
    }}
    QMainWindow, QDialog, QMessageBox {{ background: {p.window}; }}
    QMainWindow > QWidget {{ background: {p.window}; }}

    /* --- cards ------------------------------------------------------ */
    QFrame#card {{
        background: {p.card};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    QFrame#card QLabel {{ background: transparent; }}

    QLabel#sectionTitle {{
        color: {p.muted};
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        padding: 0 2px 2px 2px;
    }}
    QLabel#hint {{ color: {p.muted}; font-size: 12px; }}
    QLabel#appName {{ font-size: 15px; font-weight: 700; }}
    QLabel#stateOk {{ color: {p.ok}; font-size: 12px; font-weight: 600; }}
    QLabel#stateWarn {{ color: {p.warn}; font-size: 12px; font-weight: 600; }}
    QLabel#stateBad {{ color: {p.bad}; font-size: 12px; font-weight: 600; }}
    QLabel#statusDetail {{ color: {p.muted}; font-size: 13px; }}
    QLabel#statusTarget {{ color: {p.muted}; font-size: 12px; font-weight: 600; }}
    QLabel#statusValue {{ font-size: 30px; font-weight: 700; }}

    /* --- inputs ----------------------------------------------------- */
    QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QListWidget {{
        background: {p.field};
        border: 1px solid {p.field_border};
        border-radius: 7px;
        padding: 6px 10px;
        min-height: 20px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus,
    QListWidget:focus {{
        border: 1px solid {p.accent};
    }}
    QListWidget::item {{ padding: 3px 4px; border-radius: 4px; }}
    QListWidget::item:selected {{
        background: {p.accent};
        color: {p.accent_text};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
        color: {p.muted};
        background: {p.card};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 26px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{ image: url({g["down"]}); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{
        background: {p.card};
        border: 1px solid {p.border};
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
        outline: none;
    }}
    QPlainTextEdit {{
        font-family: Menlo, monospace;
        font-size: 12px;
        padding: 10px;
    }}

    /* --- buttons ---------------------------------------------------- */
    QPushButton {{
        background: {p.card};
        border: 1px solid {p.field_border};
        border-radius: 7px;
        padding: 7px 16px;
        min-height: 20px;
    }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {p.border}; }}
    QPushButton:disabled {{ color: {p.muted}; border-color: {p.border}; }}
    /* Sits in the tab bar corner; needs breathing room from the edge. */
    QPushButton#cornerButton {{ margin: 6px 12px 6px 6px; }}

    QPushButton#primary {{
        background: {p.accent};
        border: 1px solid {p.accent};
        color: {p.accent_text};
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {p.accent}; border-color: {p.text}; }}
    QPushButton#primary:disabled {{
        background: {p.border};
        border-color: {p.border};
        color: {p.muted};
    }}

    QCheckBox {{ spacing: 9px; background: transparent; padding: 2px 0; }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.field_border};
        border-radius: 4px;
        background: {p.field};
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    QCheckBox::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
        image: url({g["check"]});
    }}
    QCheckBox::indicator:disabled {{
        border-color: {p.border};
        background: {p.card};
    }}
    QCheckBox::indicator:checked:disabled {{
        background: {p.border};
        image: url({g["check_off"]});
    }}

    /* The checkbox indicator made round, and filled solid when selected — the
       same "accent fill means on" language, without needing a dot asset. The
       border stays 1px in every state: Qt lays the radius out against the
       border box, so a thicker border visibly squares the circle off. */
    QRadioButton {{ spacing: 9px; background: transparent; padding: 2px 0; }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.field_border};
        border-radius: 9px;
        background: {p.field};
    }}
    QRadioButton::indicator:hover {{ border-color: {p.accent}; }}
    QRadioButton::indicator:checked {{
        background: {p.accent};
        border: 1px solid {p.accent};
        border-radius: 9px;
    }}
    QRadioButton::indicator:disabled {{
        border-color: {p.border};
        background: {p.card};
    }}
    QRadioButton::indicator:checked:disabled {{
        background: {p.border};
        border: 1px solid {p.border};
    }}
    QRadioButton:disabled {{ color: {p.muted}; }}

    QSpinBox {{ padding-right: 2px; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 20px;
        border: none;
        background: transparent;
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; margin-top: 2px; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 2px; }}
    QSpinBox::up-arrow {{ image: url({g["up"]}); width: 14px; height: 14px; }}
    QSpinBox::down-arrow {{ image: url({g["down"]}); width: 14px; height: 14px; }}
    QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ opacity: 0.4; }}

    /* --- tabs ------------------------------------------------------- */
    QTabWidget::pane {{ border: none; background: {p.window}; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.muted};
        border: none;
        border-radius: 7px;
        padding: 7px 18px;
        margin: 6px 3px;
        font-weight: 600;
    }}
    QTabBar::tab:hover {{ color: {p.text}; }}
    QTabBar::tab:selected {{ background: {p.card}; color: {p.text}; }}

    /* --- table ------------------------------------------------------ */
    QTableWidget {{
        background: {p.card};
        border: 1px solid {p.border};
        border-radius: 10px;
        gridline-color: {p.border};
        outline: none;
    }}
    QTableWidget::item {{ padding: 7px 8px; border: none; }}
    QTableWidget::item:selected {{
        background: {p.accent};
        color: {p.accent_text};
    }}
    QHeaderView::section {{
        background: {p.card};
        color: {p.muted};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 8px;
        font-weight: 600;
    }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {p.field_border}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {p.field_border}; border-radius: 5px; min-width: 30px;
    }}

    /* --- progress ---------------------------------------------------- */
    QProgressBar {{
        background: {p.field};
        border: 1px solid {p.field_border};
        border-radius: 6px;
        max-height: 10px;
        text-align: center;
        color: transparent;  /* the percentage is in the status line instead */
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 5px; }}

    QSplitter::handle {{ background: transparent; }}
    QStatusBar {{ background: {p.window}; color: {p.muted}; }}
    QStatusBar::item {{ border: none; }}
    QToolTip {{
        background: {p.card};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 5px;
    }}
    """


def apply(app: QApplication, palette: Palette | None = None) -> Palette:
    """Install the Fusion style, palette and stylesheet. Returns what was used."""
    global _chosen

    # Detect from the system appearance before overwriting the palette.
    palette = palette or active()
    app.setStyle("Fusion")
    app.setPalette(qpalette(palette))
    app.setStyleSheet(stylesheet(palette))
    _chosen = palette
    return palette


# ----------------------------------------------------------------------
# Layout helpers — used by every tab so spacing stays consistent.
# ----------------------------------------------------------------------
def card() -> tuple[QFrame, QVBoxLayout]:
    """A rounded panel. Returns the frame and its layout."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionTitle")
    return label


def form() -> QFormLayout:
    """A form whose fields actually grow, with left-aligned labels.

    AllNonFixedFieldsGrow is the important part: the macOS default pins fields
    to their size hint, which elides placeholder text into "...".
    """
    layout = QFormLayout()
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(18)
    layout.setVerticalSpacing(12)
    return layout


def label(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setFixedWidth(LABEL_WIDTH)
    return widget


def hint(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName("hint")
    widget.setWordWrap(True)
    return widget


def column(spacing: int = 18) -> tuple[QWidget, QVBoxLayout]:
    """A width-capped, centred content column.

    Stretch spacers rather than AlignHCenter: alignment would give the column
    its sizeHint width, so a tab with little content collapsed to a sliver
    while a dense one filled the cap.
    """
    outer = QWidget()
    outer_layout = QHBoxLayout(outer)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)

    inner = QWidget()
    inner.setMaximumWidth(CONTENT_WIDTH)
    inner_layout = QVBoxLayout(inner)
    inner_layout.setContentsMargins(0, 0, 0, 0)
    inner_layout.setSpacing(spacing)

    outer_layout.addStretch(1)
    outer_layout.addWidget(inner, 10)
    outer_layout.addStretch(1)
    return outer, inner_layout
