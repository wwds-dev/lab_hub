"""The formats Calibre can read and write.

The lists come from Calibre's own plugin registry — checked with::

    calibre-debug -c "from calibre.customize.ui import \\
        available_input_formats, available_output_formats; \\
        print(sorted(available_input_formats())); \\
        print(sorted(available_output_formats()))"

They are pinned here rather than queried at runtime because importing Calibre's
Python packages means depending on its interpreter; the app only ever shells
out to the ``ebook-convert`` binary. :func:`missing_from_calibre` re-checks the
pinned lists against a live Calibre when one is importable, so drift shows up
in the test suite instead of in a user's face.

Vendored copy — developed and tested in
active/convert_epub/ebook_converter/. Keep the two in step.
"""

from dataclasses import dataclass, field

# Every extension Calibre accepts as input. Comic and archive formats are
# included because Calibre genuinely reads them, even though the results are
# only as good as the source.
INPUT_EXTENSIONS: frozenset[str] = frozenset(
    """
    azw azw3 azw4 cb7 cbc cbr cbz chm djv djvu docm docx epub fb2 fbz htm html
    htmlz kepub lit lrf markdown md mobi odt opf pdb pdf pml pmlz pobi prc rar
    rb rtf shtm shtml snb tcr text textile txt txtz updb xhtm xhtml zip
    """.split()
)

# Input formats that carry no reliable structure, so conversions out of them
# tend to need manual cleanup. Surfaced as a warning, never as a block.
LOSSY_INPUTS: frozenset[str] = frozenset({"pdf", "djv", "djvu", "cbz", "cbr", "cb7", "cbc"})


@dataclass(frozen=True)
class OutputFormat:
    """A target Calibre can write.

    ``ext`` is what Calibre must see on the output path to pick the right
    plugin. ``final_suffix`` is what the finished file is named — they differ
    only for KEPUB, which Calibre writes as ``.kepub`` but Kobo devices only
    recognise as ``.kepub.epub``.
    """

    ext: str
    label: str
    note: str = ""
    _final_suffix: str | None = field(default=None, repr=False)

    @property
    def final_suffix(self) -> str:
        return self._final_suffix or f".{self.ext}"

    @property
    def convert_suffix(self) -> str:
        return f".{self.ext}"

    @property
    def renames_output(self) -> bool:
        return self.final_suffix != self.convert_suffix


# Ordered for the picker: the formats people actually ask for first, then the
# long tail alphabetically. 'oeb' is deliberately absent — it writes a folder
# of HTML rather than a file, which does not fit the one-file-in/one-file-out
# model the rest of the app is built on.
OUTPUT_FORMATS: tuple[OutputFormat, ...] = (
    OutputFormat("epub", "EPUB", "Standard ebook format — the safest default."),
    OutputFormat("pdf", "PDF", "Fixed page layout. Good for printing, poor for reflowing on e-readers."),
    OutputFormat("azw3", "AZW3", "Modern Kindle format."),
    OutputFormat("mobi", "MOBI", "Legacy Kindle format. Prefer AZW3 for newer devices."),
    OutputFormat("docx", "DOCX", "Microsoft Word."),
    OutputFormat("txt", "TXT", "Plain text — drops all formatting and images."),
    OutputFormat("rtf", "RTF", "Rich Text Format."),
    OutputFormat("fb2", "FB2", "FictionBook, common in Eastern European libraries."),
    OutputFormat("htmlz", "HTMLZ", "Zipped HTML."),
    OutputFormat("kepub", "KEPUB (Kobo)", "EPUB with Kobo extensions.", ".kepub.epub"),
    OutputFormat("lit", "LIT", "Microsoft Reader (discontinued)."),
    OutputFormat("lrf", "LRF", "Sony Reader (discontinued)."),
    OutputFormat("pdb", "PDB", "Palm database."),
    OutputFormat("pmlz", "PMLZ", "eReader / Palm markup."),
    OutputFormat("rb", "RB", "Rocket eBook."),
    OutputFormat("snb", "SNB", "Shanda Bambook."),
    OutputFormat("tcr", "TCR", "Psion Series 3."),
    OutputFormat("txtz", "TXTZ", "Zipped plain text."),
    OutputFormat("zip", "ZIP (HTML)", "Zipped HTML pages."),
)

OUTPUT_BY_EXT: dict[str, OutputFormat] = {fmt.ext: fmt for fmt in OUTPUT_FORMATS}

DEFAULT_OUTPUT_EXT = "epub"


def is_convertible(ext: str) -> bool:
    """Whether Calibre can read this extension (leading dot optional)."""
    return ext.lower().lstrip(".") in INPUT_EXTENSIONS


def is_lossy_input(ext: str) -> bool:
    return ext.lower().lstrip(".") in LOSSY_INPUTS


def file_dialog_filter() -> str:
    """A Qt name filter listing every readable extension."""
    patterns = " ".join(f"*.{ext}" for ext in sorted(INPUT_EXTENSIONS))
    return f"Documents & ebooks ({patterns});;All files (*)"


def missing_from_calibre() -> tuple[set[str], set[str]] | None:
    """Compare the pinned lists against the installed Calibre.

    Returns ``(missing_inputs, missing_outputs)`` — formats Calibre supports
    that are not pinned here — or ``None`` when Calibre's Python packages are
    not importable, which is the normal case outside its own interpreter.
    """
    try:
        from calibre.customize.ui import (  # type: ignore[import-not-found]
            available_input_formats,
            available_output_formats,
        )
    except Exception:
        return None

    live_in = {fmt.lower() for fmt in available_input_formats()}
    live_out = {fmt.lower() for fmt in available_output_formats()}
    # 'recipe'/'downloaded_recipe' are news-fetch pseudo-formats, not files a
    # user can drop; 'oeb' is excluded above by design.
    live_in -= {"recipe", "downloaded_recipe"}
    live_out -= {"oeb"}
    return live_in - INPUT_EXTENSIONS, live_out - set(OUTPUT_BY_EXT)
