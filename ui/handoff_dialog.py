"""The confirmation before Ask Claude opens anything (spec claude-handoff §9).

One block per repo: a tick box, the folder, the rows in the window's own words,
what else runs there. A repo where Claude Code already runs starts unticked and
offers Copy prompt instead. Every name, path and reason is plain text: they
come from git, apps.toml and lsof.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lab_hub import handoff

from .progress_window import _label, _plain_tip

WIDTH = 600
FOLDER_W = 320  # pixels for the folder beside the name
COST = ("Each ticked repo opens its own Claude Code session on your plan. A session costs "
        "whatever it uses until you close it; Lab Hub sets no cap.")


def _elided(text: str, widget: QWidget, width: int = FOLDER_W) -> str:
    """A long folder cut in the middle, so both ends stay readable."""
    return widget.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, width)


class Block(QFrame):
    """One repo."""

    def __init__(self, h: handoff.Handoff, ctx: handoff.Context, text: str,
                 dialog: "HandoffDialog") -> None:
        super().__init__()
        self.setObjectName("card")
        self.handoff, self.text = h, text
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(4)
        head = QHBoxLayout()
        # The name is a label, not the box's text: a box would read "&" in a
        # repo's name as a shortcut, and a label can be bold (review P3-3).
        self.tick = QCheckBox()
        self.tick.setAccessibleName(h.repo)
        self.tick.setChecked(not ctx.claude)
        self.tick.toggled.connect(dialog.recount)
        head.addWidget(self.tick)
        self.name = _label(h.repo, "appName")
        head.addWidget(self.name)
        self.folder = _label(_elided(str(h.path), self), "hint")
        self.folder.setToolTip(_plain_tip(str(h.path)))
        head.addWidget(self.folder, 1)
        self.copy_button = None
        if ctx.claude:
            self.copy_button = QPushButton("Copy prompt")
            self.copy_button.setAutoDefault(False)
            self.copy_button.clicked.connect(lambda _=False: dialog.copy(self))
            head.addWidget(self.copy_button)
        box.addLayout(head)
        for item in h.items:
            box.addWidget(_label(item.line, "", wrap=True))
            if item.command:
                box.addWidget(_label(f"Command Lab Hub shows: {item.command}", "hint",
                                     wrap=True))
        for folder in h.extra_dirs:  # the access this grants, said up front (security P2-1)
            box.addWidget(_label(f"Also gives the session access to: {folder}", "stateWarn",
                                 wrap=True))
        if ctx.claude:
            box.addWidget(_label("Claude Code is already running here: "
                                 + "; ".join(ctx.claude) + ". Copy prompt and paste it "
                                 "there, or tick to open another session.",
                                 "stateWarn", wrap=True))
        if ctx.others:
            box.addWidget(_label("Also running here: " + "; ".join(ctx.others), "hint",
                                 wrap=True))
        if not ctx.known:
            box.addWidget(_label("Lab Hub could not tell what else runs here; the session "
                                 "is told to check.", "hint", wrap=True))


class HandoffDialog(QDialog):
    """Returns the ticked hand-offs from `chosen()` after Accepted."""

    def __init__(self, items: list[tuple[handoff.Handoff, handoff.Context, str]],
                 unplaced: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ask Claude")
        self.setModal(True)
        self.copied: handoff.Handoff | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Open a Claude Code session for each ticked repo",
                                "pageTitle", wrap=True))
        body = QWidget()
        blocks = QVBoxLayout(body)
        blocks.setContentsMargins(0, 0, 0, 0)
        self.blocks = [Block(h, ctx, text, self) for h, ctx, text in items]
        for block in self.blocks:
            blocks.addWidget(block)
        for name in unplaced:
            blocks.addWidget(_label(f"{name}: no folder, not sent.", "hint", wrap=True))
        blocks.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        layout.addWidget(_label(COST, "hint", wrap=True))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.open_button = QPushButton()
        self.open_button.setObjectName("primary")
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)
        self.recount()
        screen = QApplication.primaryScreen()
        tall = int(screen.availableGeometry().height() * 0.8) if screen else 700
        self.resize(WIDTH, min(tall, 200 + 110 * max(1, len(self.blocks))))

    def chosen(self) -> list[handoff.Handoff]:
        return [b.handoff for b in self.blocks if b.tick.isChecked()]

    def recount(self) -> None:
        n = len(self.chosen())
        self.open_button.setText(f"Open {n} session{'' if n == 1 else 's'}")
        self.open_button.setEnabled(n > 0)

    def copy(self, block: Block) -> None:
        """Copy that repo's prompt for the session already open there; open nothing."""
        QApplication.clipboard().setText(block.text)
        self.copied = block.handoff
        for b in self.blocks:
            b.tick.setChecked(False)
        self.reject()
