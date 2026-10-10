"""The public websites, and what an answer from one means.

Qt-free on purpose: the tab does its fetching with Qt's network manager, on the
event loop rather than a thread, and only hands the outcome to `classify`. That
keeps the judgement — what counts as up — testable without a network.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Website:
    key: str
    name: str  # the domain, as shown on the tile
    url: str
    summary: str
    # Where the site's own files live: relative to the lab folder, or starting
    # with `~` for one kept outside it. None when there is no local copy.
    source: str | None = None
    host: str = ""  # who serves it, for the reader of an error


SITES: tuple[Website, ...] = (
    Website(
        key="altmerch",
        name="altmerch.store",
        url="https://altmerch.store/",
        summary="Shopify print-on-demand store for the streetwear sub-brands. "
        "Artwork and redesign docs live in its folder.",
        # The lab's symlink to ~/Documents/Websites/altmerch.store.
        source="altmerch_store",
        host="Shopify",
    ),
    Website(
        key="bookadatewithme",
        name="bookadatewithme.com",
        url="https://bookadatewithme.com/",
        summary="One-page site with a booking form, sent through a Netlify "
        "function.",
        source="~/Documents/Websites/bookadatewithme",
        host="Netlify",
    ),
)


def source_dir(site: Website, lab_root: Path) -> Path | None:
    """The site's local folder, if it is there."""
    if site.source is None:
        return None
    path = (
        Path(site.source).expanduser()
        if site.source.startswith("~")
        else lab_root / site.source
    )
    return path if path.is_dir() else None


@dataclass(frozen=True)
class SiteStatus:
    """One check's outcome, in the tile's terms."""

    label: str
    style: str  # stateOk | stateWarn | stateBad
    detail: str

    @property
    def up(self) -> bool:
        return self.style == "stateOk"


CHECKING = SiteStatus("Checking…", "stateWarn", "Asking the site whether it answers.")


def classify(
    site: Website,
    status: int | None,
    error: str | None,
    seconds: float,
) -> SiteStatus:
    """What a finished request says about the site.

    A 4xx is reported as the site being *down*, not as a quirk of the check:
    a host that answers 404 at the front door is serving nobody. That is
    exactly what bookadatewithme.com did when this tab was written — Netlify
    answering for the domain with no site deployed behind it.
    """
    if status is None:
        return SiteStatus(
            "Unreachable",
            "stateBad",
            f"No answer from {site.url}: {error or 'the request failed'}.",
        )
    elapsed = f"{seconds:.1f}s"
    if 200 <= status < 400:
        return SiteStatus("Online", "stateOk", f"HTTP {status} in {elapsed}.")
    host = f"{site.host} answers" if site.host else "The host answers"
    return SiteStatus(
        f"Error {status}",
        "stateBad",
        f"{host} for {site.name}, but with HTTP {status} — "
        + ("there is no page at this address." if status == 404 else "the site is not serving.")
        + f" ({elapsed})",
    )
