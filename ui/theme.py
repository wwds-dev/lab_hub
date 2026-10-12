"""Visual theme: two palettes, one stylesheet, and the layout scale.

Two looks, picked in Settings (System / Light / Dark, System by default):

* **Graphite** (dark) — near-black window, a darker sidebar, borderless cards,
  and a single mint accent. Status reads as a small tinted pill.
* **Paper** (light) — warm off-white, hairline cards, and no accent colour at
  all: the primary button is a black pill, everything else is outlined, and
  status reads as a small coloured dot.

Everything visual lives here — colours, radii, the spacing and type scale — so a
tab never carries its own number for any of them.

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

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# ----------------------------------------------------------------------
# The scale. Spacing steps and type sizes are defined here and nowhere else.
# ----------------------------------------------------------------------
SPACE_XS = 4
SPACE_S = 8
SPACE_M = 12
SPACE_L = 16
SPACE_XL = 24

# Two text sizes plus a title. Section headings are the small size, uppercase.
FONT_SMALL = 12
FONT_BODY = 13
FONT_TITLE = 17

# Width of the readable content column. Without this the form sprawls across a
# 2000px display with the fields marooned in the middle.
CONTENT_WIDTH = 760
LABEL_WIDTH = 168
SIDEBAR_WIDTH = 212

# Settings values for the appearance switch. "system" follows macOS.
MODES = ("system", "light", "dark")
DEFAULT_MODE = "system"


@dataclass(frozen=True)
class Palette:
    name: str
    dark: bool
    window: str
    sidebar: str
    sidebar_edge: str  # the line between sidebar and content; "none" for none
    card: str
    card_border: str  # a full border declaration, or "none"
    radius: int
    border: str  # separators, table grid, menus
    text: str
    muted: str
    faint: str
    field: str
    field_border: str
    accent: str  # focus rings, selection, checked controls
    accent_text: str
    primary: str  # the one filled button per view
    primary_text: str
    nav_hover: str
    nav_selected: str
    ok: str
    warn: str
    bad: str
    idle: str
    status_style: str  # "pill" or "dot"


GRAPHITE = Palette(
    name="Graphite",
    dark=True,
    window="#101012",
    sidebar="#0B0B0D",
    sidebar_edge="none",
    card="#18181B",
    card_border="none",
    radius=14,
    border="#26262B",
    text="#ECECEF",
    muted="#8B8B94",
    faint="#64646C",
    field="#202024",
    field_border="#2E2E34",
    accent="#5EE0B0",
    accent_text="#06231A",
    primary="#5EE0B0",
    primary_text="#06231A",
    nav_hover="#141417",
    nav_selected="#1C1C20",
    ok="#5EE0B0",
    warn="#E8B04A",
    bad="#F07A6E",
    idle="#8B8B94",
    status_style="pill",
)

PAPER = Palette(
    name="Paper",
    dark=False,
    window="#F7F5F0",
    sidebar="#F1EEE7",
    sidebar_edge="1px solid #E6E2D8",
    card="#FBFAF7",
    card_border="1px solid #E6E2D8",
    radius=10,
    border="#E6E2D8",
    text="#1C1B19",
    muted="#6F6A5F",
    faint="#8A857A",
    field="#FFFFFF",
    field_border="#DCD7CB",
    # No accent colour: what would be accented is ink.
    accent="#1C1B19",
    accent_text="#F7F5F0",
    primary="#1C1B19",
    primary_text="#F7F5F0",
    nav_hover="#EAE6DD",
    nav_selected="#E4DFD4",
    ok="#3F8F5B",
    warn="#B7791F",
    bad="#B5473A",
    idle="#C9C4B8",
    status_style="dot",
)

# The old names, kept for anything that still reaches for them.
DARK = GRAPHITE
LIGHT = PAPER


_chosen: Palette | None = None
_mode: str = DEFAULT_MODE
_system_fallback: Palette | None = None
_watching_system = False
_applying = False


def active() -> Palette:
    """The palette in use."""
    if _chosen is not None:
        return _chosen
    return _system_palette(QApplication.instance())


def mode() -> str:
    """The appearance setting last applied: system, light or dark."""
    return _mode


def normalise_mode(value: str | None) -> str:
    value = (value or "").strip().lower()
    return value if value in MODES else DEFAULT_MODE


def _system_palette(app) -> Palette:
    """What macOS is set to.

    Qt's colour-scheme hint answers on a real desktop. Where it cannot tell
    (the offscreen platform, an old Qt), fall back to the lightness of the
    palette the app started with — read once, before our own palette replaced
    it, or it would only ever report itself back.
    """
    global _system_fallback
    if app is None:
        return GRAPHITE
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", lambda: Qt.ColorScheme.Unknown)()
    if scheme == Qt.ColorScheme.Dark:
        return GRAPHITE
    if scheme == Qt.ColorScheme.Light:
        return PAPER
    if _system_fallback is None:
        window = app.palette().color(QPalette.ColorRole.Window)
        _system_fallback = GRAPHITE if window.lightness() < 128 else PAPER
    return _system_fallback


def palette_for(value: str | None, app=None) -> Palette:
    """The palette an appearance setting stands for."""
    value = normalise_mode(value)
    if value == "dark":
        return GRAPHITE
    if value == "light":
        return PAPER
    return _system_palette(app or QApplication.instance())


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
    pal.setColor(roles.PlaceholderText, QColor(p.faint))
    # Anchor colour comes from the palette, not from any document stylesheet.
    # Paper has no accent, so its links are ink, underlined by Qt.
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
        pal.setColor(disabled, role, QColor(p.faint))
    return pal


def _rgba(colour: str, alpha: float) -> str:
    c = QColor(colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(alpha * 255)})"


# ----------------------------------------------------------------------
# Glyphs.
#
# Styling ::indicator or ::drop-down hands drawing to the stylesheet, which
# then draws no checkmark and no arrow unless given an image. Fusion's own
# drawing isn't usable either: it derives outlines from the Window colour,
# which is near-black here, so an unchecked box comes out invisible. So the
# glyphs are painted at runtime and referenced by path — no image files to
# ship, and they follow whatever palette is in use (the colour is part of the
# file name, so switching theme paints a fresh set rather than reusing one).
# The sidebar's icons are painted the same way.
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


def _pen(colour: str, width: float) -> QPen:
    pen = QPen(QColor(colour), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _check(colour: str):
    def draw(painter: QPainter, size: int) -> None:
        painter.setPen(_pen(colour, max(1.6, size * 0.135)))
        path = QPainterPath()
        path.moveTo(size * 0.24, size * 0.52)
        path.lineTo(size * 0.43, size * 0.71)
        path.lineTo(size * 0.77, size * 0.30)
        painter.drawPath(path)

    return draw


def _chevron(colour: str, down: bool = True):
    def draw(painter: QPainter, size: int) -> None:
        painter.setPen(_pen(colour, max(1.4, size * 0.13)))
        top, bottom = (size * 0.38, size * 0.62) if down else (size * 0.62, size * 0.38)
        path = QPainterPath()
        path.moveTo(QPointF(size * 0.26, top))
        path.lineTo(QPointF(size * 0.50, bottom))
        path.lineTo(QPointF(size * 0.74, top))
        painter.drawPath(path)

    return draw


def _dot(colour: str):
    def draw(painter: QPainter, size: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colour))
        d = size * 0.6
        painter.drawEllipse(QRectF((size - d) / 2, (size - d) / 2, d, d))

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
        "dot_ok": _glyph("dot", p.ok, _dot(p.ok), base=10),
        "dot_warn": _glyph("dot", p.warn, _dot(p.warn), base=10),
        "dot_bad": _glyph("dot", p.bad, _dot(p.bad), base=10),
        "dot_idle": _glyph("dot", p.idle, _dot(p.idle), base=10),
    }


# Sidebar icons: a handful of plain strokes, one per top-level page.
def _nav_drawing(name: str, colour: str):
    def draw(painter: QPainter, size: int) -> None:
        s = size
        painter.setPen(_pen(colour, max(1.3, s * 0.085)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if name == "apps":  # four tiles
            g = s * 0.30
            for x in (s * 0.17, s * 0.53):
                for y in (s * 0.17, s * 0.53):
                    painter.drawRoundedRect(QRectF(x, y, g, g), s * 0.07, s * 0.07)
        elif name == "web":  # a globe
            r = QRectF(s * 0.15, s * 0.15, s * 0.70, s * 0.70)
            painter.drawEllipse(r)
            painter.drawEllipse(QRectF(s * 0.36, s * 0.15, s * 0.28, s * 0.70))
            painter.drawLine(QPointF(s * 0.15, s * 0.5), QPointF(s * 0.85, s * 0.5))
        elif name == "dashboards":  # three bars
            for i, h in enumerate((0.35, 0.6, 0.45)):
                x = s * (0.22 + i * 0.22)
                painter.drawLine(QPointF(x, s * 0.82), QPointF(x, s * (0.82 - h)))
        elif name == "sync":  # two arcs, chasing
            r = QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64)
            painter.drawArc(r, 30 * 16, 150 * 16)
            painter.drawArc(r, 210 * 16, 150 * 16)
            painter.drawLine(QPointF(s * 0.78, s * 0.20), QPointF(s * 0.78, s * 0.36))
            painter.drawLine(QPointF(s * 0.22, s * 0.80), QPointF(s * 0.22, s * 0.64))
        elif name == "tools":  # sliders
            for i, knob in enumerate((0.35, 0.65, 0.45)):
                y = s * (0.25 + i * 0.25)
                painter.drawLine(QPointF(s * 0.16, y), QPointF(s * 0.84, y))
                painter.setBrush(QColor(colour))
                painter.drawEllipse(QPointF(s * knob, y), s * 0.07, s * 0.07)
                painter.setBrush(Qt.BrushStyle.NoBrush)
        elif name == "settings":  # a dial
            painter.drawEllipse(QRectF(s * 0.2, s * 0.2, s * 0.6, s * 0.6))
            painter.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.1, s * 0.1)
        elif name == "refresh":
            r = QRectF(s * 0.2, s * 0.2, s * 0.6, s * 0.6)
            painter.drawArc(r, 60 * 16, 280 * 16)
            painter.drawLine(QPointF(s * 0.66, s * 0.12), QPointF(s * 0.68, s * 0.28))
            painter.drawLine(QPointF(s * 0.68, s * 0.28), QPointF(s * 0.52, s * 0.30))

    return draw


NAV_GLYPHS = ("apps", "web", "dashboards", "sync", "tools", "settings", "refresh")


def nav_icon(name: str, p: Palette | None = None) -> QIcon:
    """A sidebar icon: muted at rest, full text colour when its page is open."""
    p = p or active()
    icon = QIcon()
    for colour, state in ((p.muted, QIcon.State.Off), (p.text, QIcon.State.On)):
        image = _paint(36, _nav_drawing(name, colour))
        image.setDevicePixelRatio(2.0)
        # Every mode, not only Normal: a checked button can be drawn in Active
        # or Selected mode, and Qt's generated pixmap for a missing mode is
        # tinted with the palette's highlight — invisible on the dark sidebar.
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addPixmap(QPixmap.fromImage(image), mode, state)
    return icon


def _status_rules(p: Palette, g: dict[str, str]) -> str:
    """The one status marker on a tile: a tinted pill (Graphite) or a dot (Paper).

    Only labels flagged `status=true` get it — the same object names also
    colour quieter text (a stale version, a running background service), and a
    pill on each of those would make three status markers on one tile.
    """
    kinds = (("stateOk", p.ok, "dot_ok"), ("stateWarn", p.warn, "dot_warn"),
             ("stateBad", p.bad, "dot_bad"), ("hint", p.idle, "dot_idle"))
    rules = []
    for name, colour, dot in kinds:
        selector = f'QLabel#{name}[status="true"]'
        if p.status_style == "pill":
            rules.append(f"""
    {selector} {{
        color: {colour if name != "hint" else p.muted};
        background: {_rgba(colour, 0.14)};
        border: 1px solid {_rgba(colour, 0.0)};
        border-radius: 9px;
        padding: 2px 10px;
        font-size: {FONT_SMALL}px;
        font-weight: 600;
    }}""")
        else:
            rules.append(f"""
    {selector} {{
        color: {p.muted};
        background-image: url({g[dot]});
        background-repeat: no-repeat;
        background-position: left center;
        padding-left: 14px;
        font-size: {FONT_SMALL}px;
        font-weight: 500;
    }}""")
    return "".join(rules)


def stylesheet(p: Palette) -> str:
    g = glyphs(p)
    r = p.radius
    # Buttons: one filled primary per view; a tile's main action is quieter;
    # everything else recedes. Paper's are pills; Graphite's are rounded.
    pill = 16 if not p.dark else 8
    tile_primary_bg = _rgba(p.accent, 0.14) if p.dark else "transparent"
    tile_primary_border = "none" if p.dark else f"1px solid {p.text}"
    tile_primary_text = p.accent if p.dark else p.text
    secondary_bg = p.border if p.dark else "transparent"
    secondary_border = "none" if p.dark else f"1px solid {p.field_border}"
    return f"""
    /* Plain containers stay transparent. Painting every QWidget with the
       window colour drew a dark slab behind each multi-widget form row. */
    QWidget {{
        background: transparent;
        color: {p.text};
        font-size: {FONT_BODY}px;
    }}
    QMainWindow, QDialog, QMessageBox {{ background: {p.window}; }}
    QMainWindow > QWidget {{ background: {p.window}; }}

    /* --- sidebar ---------------------------------------------------- */
    QFrame#sidebar {{
        background: {p.sidebar};
        border: none;
        border-right: {p.sidebar_edge};
    }}
    QLabel#sidebarTitle {{
        font-size: {FONT_TITLE}px;
        font-weight: 700;
        padding: 0 {SPACE_S}px;
    }}
    QLabel#sidebarVersion {{
        color: {p.faint};
        font-size: {FONT_SMALL}px;
        padding: 0 {SPACE_S}px;
    }}
    QPushButton#navItem, QPushButton#navChild {{
        background: transparent;
        border: none;
        border-radius: 8px;
        color: {p.muted};
        text-align: left;
        padding: 6px {SPACE_S}px;
        min-height: 20px;
        font-weight: 500;
    }}
    QPushButton#navChild {{
        padding-left: 38px;
        font-size: {FONT_SMALL}px;
        min-height: 16px;
    }}
    QPushButton#navItem:hover, QPushButton#navChild:hover {{
        background: {p.nav_hover};
        color: {p.text};
    }}
    QPushButton#navItem:checked, QPushButton#navChild:checked {{
        background: {p.nav_selected};
        color: {p.text};
        font-weight: 600;
    }}
    QPushButton#navItem[open="true"] {{ color: {p.text}; }}

    /* --- cards ------------------------------------------------------ */
    QFrame#card {{
        background: {p.card};
        border: {p.card_border};
        border-radius: {r}px;
    }}
    QFrame#card QLabel {{ background: transparent; }}

    QLabel#sectionTitle {{
        color: {p.faint};
        font-size: {FONT_SMALL}px;
        font-weight: 600;
        padding: 0 2px 2px 2px;
    }}
    QLabel#hint {{ color: {p.muted}; font-size: {FONT_SMALL}px; }}
    QLabel#emptyState {{
        color: {p.faint};
        font-size: {FONT_BODY}px;
        padding: {SPACE_XL}px 0;
    }}
    QLabel#appName {{ font-size: {FONT_BODY}px; font-weight: 700; }}
    QLabel#stateOk {{ color: {p.ok}; font-size: {FONT_SMALL}px; font-weight: 600; }}
    QLabel#stateWarn {{ color: {p.warn}; font-size: {FONT_SMALL}px; font-weight: 600; }}
    QLabel#stateBad {{ color: {p.bad}; font-size: {FONT_SMALL}px; font-weight: 600; }}
    {_status_rules(p, g)}

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
        color: {p.faint};
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
        font-size: {FONT_SMALL}px;
        padding: 10px;
    }}

    /* --- buttons ---------------------------------------------------- */
    /* Secondary: present, but quiet. */
    QPushButton {{
        background: {secondary_bg};
        border: {secondary_border};
        border-radius: {pill}px;
        color: {p.text};
        padding: 7px {SPACE_L}px;
        min-height: 18px;
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {p.nav_hover if not p.dark else p.field_border}; }}
    QPushButton:pressed {{ background: {p.nav_selected if not p.dark else p.field_border}; }}
    QPushButton:disabled {{ color: {p.faint}; }}

    /* Primary: the one filled button on a view. */
    QPushButton#primary {{
        background: {p.primary};
        border: 1px solid {p.primary};
        color: {p.primary_text};
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {_rgba(p.primary, 0.86)}; }}
    QPushButton#primary:disabled {{
        background: {p.border};
        border-color: {p.border};
        color: {p.faint};
    }}

    /* On a tile, Launch / Open is the main action of that tile, not of the
       view — a grid of filled buttons would be a wall of primaries. */
    AppCard QPushButton#primary, LinkCard QPushButton#primary {{
        background: {tile_primary_bg};
        border: {tile_primary_border};
        color: {tile_primary_text};
    }}
    AppCard QPushButton#primary:hover, LinkCard QPushButton#primary:hover {{
        background: {_rgba(p.accent, 0.24) if p.dark else p.nav_hover};
    }}
    AppCard QPushButton#primary:disabled, LinkCard QPushButton#primary:disabled {{
        background: transparent;
        border: {"none" if p.dark else f"1px solid {p.border}"};
        color: {p.faint};
    }}
    /* A tile's other actions are text until hovered. */
    AppCard QPushButton, LinkCard QPushButton {{
        background: transparent;
        border: none;
        color: {p.muted};
        padding: 7px {SPACE_M}px;
    }}
    AppCard QPushButton:hover, LinkCard QPushButton:hover {{
        color: {p.text};
        background: {p.nav_hover if not p.dark else p.border};
    }}

    /* A segmented control (the appearance switch). */
    QPushButton#segment {{
        background: transparent;
        border: 1px solid {p.field_border};
        border-radius: 0;
        color: {p.muted};
        padding: 6px {SPACE_L}px;
    }}
    QPushButton#segment[edge="first"] {{
        border-top-left-radius: {pill}px; border-bottom-left-radius: {pill}px;
    }}
    QPushButton#segment[edge="last"] {{
        border-top-right-radius: {pill}px; border-bottom-right-radius: {pill}px;
    }}
    QPushButton#segment:checked {{
        background: {p.primary};
        border-color: {p.primary};
        color: {p.primary_text};
        font-weight: 600;
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
       same "fill means on" language, without needing a dot asset. The border
       stays 1px in every state: Qt lays the radius out against the border
       box, so a thicker border visibly squares the circle off. */
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
    QRadioButton:disabled {{ color: {p.faint}; }}

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

    /* --- tabs inside a page (Narrator, Prepare Images) --------------- */
    QTabWidget::pane {{ border: none; background: transparent; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.muted};
        border: none;
        border-radius: 7px;
        padding: 6px {SPACE_L}px;
        margin: {SPACE_XS}px 2px;
        font-weight: 600;
    }}
    QTabBar::tab:hover {{ color: {p.text}; }}
    QTabBar::tab:selected {{ background: {p.nav_selected}; color: {p.text}; }}

    /* --- table ------------------------------------------------------ */
    QTableWidget {{
        background: {p.card};
        border: {p.card_border};
        border-radius: {r}px;
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
    QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
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
    QStatusBar {{ background: {p.window}; color: {p.muted}; font-size: {FONT_SMALL}px; }}
    QStatusBar::item {{ border: none; }}
    QToolTip {{
        background: {p.card};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 5px;
    }}
    """


def apply(app: QApplication, palette: Palette | None = None, mode: str | None = None) -> Palette:
    """Install the Fusion style, palette and stylesheet. Returns what was used.

    Safe to call again at any time — that is how the Settings switch changes
    the look live. Give `mode` (system / light / dark) to follow a setting;
    a `palette` given directly wins over it.
    """
    global _chosen, _mode, _applying
    if mode is not None:
        _mode = normalise_mode(mode)

    _applying = True
    try:
        hints = app.styleHints()
        # Read the system's answer before forcing anything: a forced scheme is
        # what colorScheme() reports back afterwards.
        if _mode == "system" and hasattr(hints, "unsetColorScheme"):
            hints.unsetColorScheme()
        chosen = palette or palette_for(_mode, app)
        # The title bar and other native chrome follow the forced scheme.
        if _mode != "system" and hasattr(hints, "setColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Dark if chosen.dark else Qt.ColorScheme.Light)

        # Set first: the palette change below repaints the sidebar icons, and
        # they ask active() for their colours. Set after, they were painted in
        # the outgoing theme — dark ink on the dark sidebar, so the selected
        # entry's icon vanished.
        _chosen = chosen
        app.setStyle("Fusion")
        app.setPalette(qpalette(chosen))
        app.setStyleSheet(stylesheet(chosen))
    finally:
        _applying = False
    _follow_system(app)
    return chosen


def _follow_system(app: QApplication) -> None:
    """Re-theme when macOS switches appearance, while the setting is System."""
    global _watching_system
    if _watching_system:
        return
    signal = getattr(app.styleHints(), "colorSchemeChanged", None)
    if signal is None:
        return

    def changed(*_args) -> None:
        if _mode == "system" and not _applying:
            apply(app)

    signal.connect(changed)
    _watching_system = True


# ----------------------------------------------------------------------
# Layout helpers — used by every tab so spacing stays consistent.
# ----------------------------------------------------------------------
def card() -> tuple[QFrame, QVBoxLayout]:
    """A rounded panel. Returns the frame and its layout."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(SPACE_L + SPACE_XS, SPACE_L, SPACE_L + SPACE_XS, SPACE_L)
    layout.setSpacing(SPACE_M)
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
    layout.setHorizontalSpacing(SPACE_L)
    layout.setVerticalSpacing(SPACE_M)
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


def empty_state(text: str) -> QLabel:
    """What an empty page says instead of showing nothing."""
    widget = QLabel(text)
    widget.setObjectName("emptyState")
    widget.setWordWrap(True)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return widget


def mark_status(widget: QLabel) -> QLabel:
    """Flag a label as a tile's one status marker (pill or dot)."""
    widget.setProperty("status", True)
    return widget


def column(spacing: int = SPACE_L, max_width: int | None = None) -> tuple[QWidget, QVBoxLayout]:
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
    inner.setMaximumWidth(max_width or CONTENT_WIDTH)
    inner_layout = QVBoxLayout(inner)
    inner_layout.setContentsMargins(0, 0, 0, 0)
    inner_layout.setSpacing(spacing)

    outer_layout.addStretch(1)
    outer_layout.addWidget(inner, 10)
    outer_layout.addStretch(1)
    return outer, inner_layout
