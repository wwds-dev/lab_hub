"""The Websites and Dashboards tabs: tiles that open something in the browser.

They are built like the Apps tab on purpose — the same tile, the same grid
that drops a column at the same width, a state on every tile that is re-read
rather than remembered, Re-check, and a poll that runs only while the tab is on
screen. What differs is what a tile's state *means*:

* a website's is whether it answers right now, checked over the network;
* a dashboard's is whether there is anything to open — a link always is, a
  local file only while it is still on disk.

Neither is ever fetched on the UI thread. The site checks go through Qt's
network manager, which works on the event loop, so there is no thread to stop
when the app quits — the trap SONAR's docs describe at length.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lab_hub import config, dashboards, launcher, sites

from . import theme
from .apps_tab import GRID_MAX_WIDTH, POLL_MS, SUMMARY_HEIGHT, arrange_tiles, columns_for
from .widgets import scroll_column

# How long a site check may take before it counts as no answer.
SITE_TIMEOUT_MS = 10_000
# Sites are checked over the network, so far less often than the Apps tab
# re-reads its process table — and again on showing the tab, if the last check
# is older than this.
SITE_POLL_MS = 5 * 60_000
SITE_STALE_SECONDS = 60.0


def short_path(path: str) -> str:
    """A path short enough to wrap inside a tile.

    A label cannot break inside a word, and a path is one long word: the
    Antfarm workstation's sits five generated folders deep, and at full length
    it set the minimum width of the whole tab. Home becomes `~`, and anything
    deeper than four folders keeps its first two and its file name. The full
    path is the tooltip, and Show in Finder goes straight to it.
    """
    home = str(Path.home())
    text = "~" + path[len(home):] if path.startswith(home + "/") else path
    parts = text.split("/")
    if len(parts) > 5:
        text = "/".join(parts[:3] + ["…", parts[-1]])
    return text


class LinkCard(QWidget):
    """Name, what it is, a state, where it lives, and an Open button."""

    open_requested = Signal()
    reveal_requested = Signal()

    def __init__(
        self,
        name: str,
        summary: str,
        open_label: str,
        reveal_label: str = "Show in Finder",
        parent=None,
    ) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame, layout = theme.card()
        outer.addWidget(frame)

        header = QHBoxLayout()
        header.setSpacing(12)
        self.name = QLabel(name)
        self.name.setObjectName("appName")
        self.state = QLabel()
        self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.name)
        header.addStretch(1)
        header.addWidget(self.state)

        # What kind of thing this is, on a line of its own. Beside the title,
        # where an app tile keeps its version, it made a header row that cannot
        # wrap — and a dashboard title is long enough that three of those rows
        # set the tab's minimum width wider than its column.
        self.meta = QLabel()
        self.meta.setObjectName("hint")

        self.summary = theme.hint(summary)
        self.summary.setMinimumHeight(SUMMARY_HEIGHT)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.detail = QLabel()
        self.detail.setObjectName("hint")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.open_button = QPushButton(open_label)
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_requested)
        self.reveal_button = QPushButton(reveal_label)
        self.reveal_button.clicked.connect(self.reveal_requested)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.open_button, 1)
        buttons.addWidget(self.reveal_button)

        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addLayout(header)
        heading.addWidget(self.meta)
        layout.addLayout(heading)
        layout.addWidget(self.summary)
        layout.addWidget(self.detail)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def set_state(self, label: str, style: str, tooltip: str = "") -> None:
        self.state.setText(label)
        self.state.setToolTip(tooltip)
        if self.state.objectName() != style:
            # A changed objectName only takes effect once the style is re-applied.
            self.state.setObjectName(style)
            self.state.style().unpolish(self.state)
            self.state.style().polish(self.state)


class LinksTab(QWidget):
    """A page of link tiles with Re-check and an on-screen-only poll."""

    opened = Signal(str)  # a status-bar line
    failed = Signal(str)

    def __init__(
        self,
        settings: config.Settings,
        title: str,
        intro: str,
        poll_ms: int = POLL_MS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.cards: list[LinkCard] = []

        area, column = scroll_column(max_width=GRID_MAX_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        column.addWidget(theme.section_title(title))
        self.intro = theme.hint(intro)
        column.addWidget(self.intro)
        # Says why there are no tiles, when there are none.
        self.notice = theme.hint("")
        self.notice.hide()
        column.addWidget(self.notice)

        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        column.addLayout(self.grid)
        self._columns = 0

        refresh = QPushButton("Re-check")
        refresh.clicked.connect(self.recheck)
        self.recheck_button = refresh
        self.buttons = QHBoxLayout()
        self.buttons.addWidget(refresh)
        self.buttons.addStretch(1)
        column.addLayout(self.buttons)
        column.addStretch(1)

        self._poll = QTimer(self)
        self._poll.setInterval(poll_ms)
        self._poll.timeout.connect(self.refresh)

    # ------------------------------------------------------------------
    def lab_root(self) -> Path:
        return self.settings.resolved_lab_root()

    def set_cards(self, cards: list[LinkCard]) -> None:
        """Replace every tile — the Dashboards tab re-reads its catalog."""
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = cards
        self._columns = 0
        self._arrange(columns_for(self.width(), len(cards)))

    def _arrange(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        arrange_tiles([(self.grid, self.cards)], columns)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._arrange(columns_for(self.width(), len(self.cards)))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh()
        self._poll.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._poll.stop()

    def apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        self.recheck()

    def show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def open_address(self, name: str, address: str) -> None:
        try:
            launcher.open_url(address)
        except launcher.LaunchError as error:
            QMessageBox.warning(self, f"Could not open {name}", str(error))
            return
        self.opened.emit(f"Opened {name}")

    # Subclasses fill these in.
    def refresh(self) -> None:
        raise NotImplementedError

    def recheck(self) -> None:
        self.refresh()


# ----------------------------------------------------------------------
# Websites
# ----------------------------------------------------------------------
class SiteChecker(QObject):
    """Asks each site whether it answers, without blocking anything.

    A HEAD request, so a page is never downloaded to learn its status —
    bookadatewithme.com's front page is 1.7 MB. Redirects are followed, as a
    browser would; a site that answers 405 to HEAD is still up.
    """

    checked = Signal(str, object)  # site key, sites.SiteStatus

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._started: dict[QNetworkReply, tuple[sites.Website, float]] = {}

    def check(self, site: sites.Website) -> None:
        request = QNetworkRequest(QUrl(site.url))
        request.setTransferTimeout(SITE_TIMEOUT_MS)
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork,
        )
        reply = self._manager.head(request)
        self._started[reply] = (site, time.monotonic())
        reply.finished.connect(lambda r=reply: self._finished(r))

    def _finished(self, reply: QNetworkReply) -> None:
        site, began = self._started.pop(reply, (None, 0.0))
        reply.deleteLater()
        if site is None:
            return
        code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(code) if code is not None else None
        if status in (405, 501):
            # Up, and particular about methods.
            status = 200
        error = None if status is not None else reply.errorString()
        self.checked.emit(
            site.key, sites.classify(site, status, error, time.monotonic() - began)
        )


class SitesTab(LinksTab):
    """altmerch.store and bookadatewithme.com: are they up, and open them."""

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(
            settings,
            title="Websites",
            intro=(
                "The public sites. Each tile asks its site whether it answers "
                "when the tab is opened, every five minutes while it stays "
                "open, and on Re-check."
            ),
            poll_ms=SITE_POLL_MS,
            parent=parent,
        )
        self.recheck_button.setToolTip("Ask every site again now")
        self.checker = SiteChecker(self)
        self.checker.checked.connect(self._on_checked)
        self.statuses: dict[str, sites.SiteStatus] = {}
        self._checked_at: float | None = None

        self.by_key: dict[str, LinkCard] = {}
        cards = []
        for site in sites.SITES:
            card = LinkCard(site.name, site.summary, "Open site", "Show files")
            card.meta.setText(site.host)
            card.open_requested.connect(lambda s=site: self.open_address(s.name, s.url))
            card.reveal_requested.connect(lambda s=site: self._reveal(s))
            card.set_state("Not checked", "hint")
            self.by_key[site.key] = card
            cards.append(card)
        self.set_cards(cards)
        self._show_sources()

    def _show_sources(self) -> None:
        root = self.lab_root()
        for site in sites.SITES:
            card = self.by_key[site.key]
            folder = sites.source_dir(site, root)
            card.detail.setText(
                f"{site.url}\n{short_path(str(folder))}" if folder else
                f"{site.url}\nNo local files found"
                + (f" at {site.source}" if site.source else "")
            )
            card.detail.setToolTip(str(folder) if folder else "")
            card.reveal_button.setEnabled(folder is not None)
            card.reveal_button.setToolTip(
                f"Show {folder} in Finder" if folder else "No local folder for this site"
            )

    def _reveal(self, site: sites.Website) -> None:
        folder = sites.source_dir(site, self.lab_root())
        if folder is not None:
            launcher.reveal(folder)

    def check_all(self) -> None:
        self._checked_at = time.monotonic()
        for site in sites.SITES:
            self.statuses[site.key] = sites.CHECKING
            self.by_key[site.key].set_state(
                sites.CHECKING.label, sites.CHECKING.style, sites.CHECKING.detail
            )
            self.checker.check(site)

    def _on_checked(self, key: str, status: sites.SiteStatus) -> None:
        self.statuses[key] = status
        card = self.by_key.get(key)
        if card is not None:
            card.set_state(status.label, status.style, status.detail)

    def refresh(self) -> None:
        """What showing the tab and the poll do: look, unless just looked."""
        self._show_sources()
        stale = (
            self._checked_at is None
            or time.monotonic() - self._checked_at > SITE_STALE_SECONDS
        )
        if stale:
            self.check_all()

    def recheck(self) -> None:
        self._show_sources()
        self.check_all()


# ----------------------------------------------------------------------
# Dashboards
# ----------------------------------------------------------------------
class DashboardsTab(LinksTab):
    """Every entry in the lab's dashboard catalog."""

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(
            settings,
            title="Dashboards",
            intro=(
                "Read from the lab's dashboard catalog — the same list as the "
                "Lab Project Monitor's Dashboards section. Add one there and it "
                "appears here."
            ),
            parent=parent,
        )
        self.recheck_button.setToolTip("Read the catalog again")
        self.entries: tuple[dashboards.Dashboard, ...] = ()
        self._catalog_stamp: tuple[str, int] | None = None

        edit = QPushButton("Show catalog")
        edit.setToolTip("Show dashboard_catalog.json in Finder")
        edit.clicked.connect(self._reveal_catalog)
        self.buttons.insertWidget(1, edit)
        self.catalog_button = edit

        self.reload()

    def _stamp(self) -> tuple[str, int] | None:
        path = dashboards.catalog_path(self.lab_root())
        try:
            return str(path), path.stat().st_mtime_ns
        except OSError:
            return None

    def reload(self) -> None:
        """Read the catalog and rebuild the tiles from it."""
        self._catalog_stamp = self._stamp()
        try:
            entries = dashboards.load(self.lab_root())
        except dashboards.CatalogError as error:
            self.entries = ()
            self.set_cards([])
            self.show_notice(str(error))
            self.catalog_button.setEnabled(False)
            return
        self.catalog_button.setEnabled(True)
        self.show_notice("" if entries else "The catalog lists no dashboards.")
        self.entries = entries
        cards = []
        for entry in entries:
            card = LinkCard(entry.title, entry.description, "Open")
            card.meta.setText(" · ".join(part for part in (entry.source, entry.kind) if part))
            card.open_requested.connect(lambda e=entry: self._open(e))
            card.reveal_requested.connect(lambda e=entry: self._reveal(e))
            cards.append(card)
        self.set_cards(cards)
        self._show_availability()

    def _show_availability(self) -> None:
        for entry, card in zip(self.entries, self.cards):
            available = entry.available()
            if entry.url:
                card.set_state("Link", "stateOk", entry.url)
                card.detail.setText(entry.url)
            elif available:
                card.set_state("Local file", "stateOk", entry.path or "")
                card.detail.setText(short_path(entry.path or ""))
            else:
                card.set_state(
                    "File missing", "stateBad",
                    "The catalog lists a file that is no longer on this Mac.",
                )
                card.detail.setText(
                    short_path(entry.path) if entry.path else "No path in the catalog"
                )
            card.detail.setToolTip(entry.url or entry.path or "")
            card.open_button.setEnabled(available)
            # A link has nothing on disk to show.
            card.reveal_button.setVisible(entry.local)
            card.reveal_button.setEnabled(available)

    def _open(self, entry: dashboards.Dashboard) -> None:
        if not entry.available():
            self._show_availability()
            return
        self.open_address(entry.title, dashboards.target(entry))

    def _reveal(self, entry: dashboards.Dashboard) -> None:
        if entry.path and Path(entry.path).is_file():
            launcher.reveal(Path(entry.path))

    def _reveal_catalog(self) -> None:
        path = dashboards.catalog_path(self.lab_root())
        if path.is_file():
            launcher.reveal(path)

    def refresh(self) -> None:
        """Rebuild if the catalog changed; otherwise re-check the files."""
        if self._stamp() != self._catalog_stamp:
            self.reload()
            return
        self._show_availability()

    def recheck(self) -> None:
        self.reload()
