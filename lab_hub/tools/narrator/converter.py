import os
import re
import sys
import json
import time
import random
import shutil
import argparse
import subprocess
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
import pypdf
from ebooklib import epub
from bs4 import BeautifulSoup
from openai import OpenAI, AuthenticationError
import tiktoken


# ------------------------------------------------------
# CONFIG
# ------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
BOOKS_DIR = BASE_DIR / "books"
# The UI supplies an output folder. Keep the CLI fallback portable.
OUTPUT_ROOT = Path.cwd() / "Narrator Output"

TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = "alloy"
TTS_INSTRUCTIONS = None

RETRIES = 2
MAX_WORKERS = 4
MANIFEST_SAVE_EVERY = 5
MAX_INPUT_TOKENS_PER_CHUNK = 1500

MANIFEST_FILENAME = "manifest.json"
LOCK_FILENAME = "narrator.lock"
TEMP_DIRNAME = "temp_audio"
CONVERTED_EPUB_SUFFIX = ".converted.epub"
FFMPEG_CONCAT_FILENAME = "ffmpeg_concat.txt"
CHAPTER_METADATA_FILENAME = "chapters.ffmeta"
# A chunk streams into "<name>.part" and takes its final name only once it is
# complete, so a run stopped mid-stream leaves nothing a resume can mistake
# for a finished chunk.
CHUNK_PARTIAL_SUFFIX = ".part"
# Manifest format 2 records that chunks reach their final name only when
# complete. A manifest without it was written by a version that streamed
# straight into the final name, so a chunk it never recorded as done may be
# the one a stop cut short.
MANIFEST_FORMAT = 2

# What the converter reads. MOBI and AZW3 are turned into EPUB by Calibre
# first, so they also need ebook-convert on the machine.
CALIBRE_SUFFIXES = (".mobi", ".azw3")
SUPPORTED_SUFFIXES = (".epub", ".pdf", ".txt") + CALIBRE_SUFFIXES

# Output formats. MP3 is a lossless stream copy of the chunks and plays
# anywhere; M4B re-encodes to AAC and carries chapter marks, which is what
# Apple Books and most audiobook players navigate by.
FORMAT_MP3 = "mp3"
FORMAT_M4B = "m4b"
AUDIO_FORMATS = (FORMAT_MP3, FORMAT_M4B)
DEFAULT_FORMAT = FORMAT_MP3

# What a resume does when the manifest no longer matches the run — different
# text, chunk size or voice. Either way the cached audio is unusable, so
# neither choice saves the money already spent; they differ in who decides.
# REBUILD clears the stale chunks and carries on, which is what a GUI with no
# force-rebuild control needs. REFUSE stops and asks for --force-rebuild,
# which suits a CLI where the operator is present.
REBUILD_ON_CHANGE = "rebuild"
REFUSE_ON_CHANGE = "refuse"
ON_SETTINGS_CHANGE = REBUILD_ON_CHANGE


class SettingsChanged(RuntimeError):
    """A resume met a manifest from a run with different text or settings."""


class BookLocked(RuntimeError):
    """Another running conversion holds the book's folder."""


USD_PER_1M_INPUT_TOKENS = 0.60
USD_PER_1M_OUTPUT_AUDIO_TOKENS = 12.00
# Aligned with services/per_unit_pricing.DEFAULT_EUR_PER_USD — the two
# fallbacks had drifted (0.855 here vs 0.92 there), so the same conversion
# priced differently depending on which module estimated it. This module
# stays import-side-effect-free (it runs as a bundled subprocess), so it
# keeps a constant rather than importing the live rate; callers that know
# the live rate pass it in.
EUR_PER_USD_FALLBACK = 0.92

# Lazy OpenAI client: importing this module must have NO side effects so it can
# be bundled into the host app (and PyInstaller) without needing a key at import time.
_ENV_PATH = BASE_DIR / ".env"
client = None


def get_client():
    """Create the OpenAI client on first use. Reads OPENAI_API_KEY from the host
    app's environment, falling back to a .env in the cwd, then to one beside this module."""
    global client
    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            load_dotenv(override=False)  # e.g. the project root .env
        if not os.getenv("OPENAI_API_KEY") and _ENV_PATH.exists():
            load_dotenv(dotenv_path=_ENV_PATH, override=False)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not found. Set it in the app's environment or in a "
                f".env file (cwd or {_ENV_PATH})."
            )
        client = OpenAI(api_key=api_key)
    return client


# ------------------------------------------------------
# UTILITIES
# ------------------------------------------------------

def print_progress(current: int, total: int, prefix: str = ""):
    bar_len = 30
    ratio = current / total if total else 1
    filled = int(ratio * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    percent = ratio * 100
    print(f"\r{prefix}[{bar}] {percent:5.1f}% ({current}/{total})", end="", flush=True)
    if current >= total:
        print()


def clean_name(raw: str) -> str:
    raw = os.path.basename(raw)
    raw = raw.rsplit(".", 1)[0]
    raw = re.sub(r"\[[^\]]*\]", "", raw).strip()
    raw = re.sub(r"[^A-Za-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw)
    return raw.strip("_") or "Book"


def light_normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]

    cleaned = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


def json_dump(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------
# EXTERNAL TOOLS
# ------------------------------------------------------
# Inside the frozen .app the converter is a child of the app itself, and so
# inherits two things Terminal never hands it. Finder's PATH, not the shell's:
# Homebrew is missing from it, so a tool that works in Terminal is invisible to
# `shutil.which`. And PyInstaller's dynamic-linker variables, which point at
# the bundle's own copies of system libraries; ffmpeg or Calibre loading those
# instead of its own crashes. PyInstaller stashes the launch-time values as
# `<VAR>_ORIG`, so they can be put back. The same logic lives in
# lab_hub/tools/convert/calibre.py; it is repeated here because this file is
# vendored into Imprint and imports nothing from `lab_hub.*`.

EXTRA_PATH_ENTRIES = ("/opt/homebrew/bin", "/usr/local/bin")
LINKER_VARS = ("DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LD_LIBRARY_PATH")
# Calibre's own installer ships an app bundle, not a PATH entry.
EBOOK_CONVERT_IN_APP = "Applications/calibre.app/Contents/MacOS/ebook-convert"


def subprocess_env() -> dict[str, str]:
    """The environment a tool from outside the bundle should run in."""
    env = os.environ.copy()
    for var in LINKER_VARS:
        original = env.pop(f"{var}_ORIG", None)
        if original:
            env[var] = original
        elif getattr(sys, "frozen", False):
            env.pop(var, None)
    entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    entries += [extra for extra in EXTRA_PATH_ENTRIES if extra not in entries]
    env["PATH"] = os.pathsep.join(entries)
    return env


def find_tool(name: str, *fallbacks: Path) -> str | None:
    """`name` on the PATH a subprocess will see, else the first runnable fallback."""
    found = shutil.which(name, path=subprocess_env()["PATH"])
    if found:
        return found
    for candidate in fallbacks:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def run_checked(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    """Run one of the external tools, raising a readable error when it fails."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=subprocess_env())
    except OSError as e:
        raise RuntimeError(f"{what} could not be started: {e}") from e
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed (exit code {result.returncode}).\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
    return result


def ensure_ffmpeg_available() -> str:
    ffmpeg_path = find_tool("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    raise RuntimeError(
        "ffmpeg was not found on your PATH.\n"
        "Install ffmpeg and make sure the `ffmpeg` command works in your terminal."
    )


def ensure_ffprobe_available() -> str:
    ffprobe_path = find_tool("ffprobe")
    if ffprobe_path:
        return ffprobe_path
    raise RuntimeError(
        "ffprobe was not found on your PATH.\n"
        "It normally ships with ffmpeg."
    )


def ensure_ebook_convert_available() -> str:
    cmd = find_tool(
        "ebook-convert",
        Path("/") / EBOOK_CONVERT_IN_APP,
        Path.home() / EBOOK_CONVERT_IN_APP,
    )
    if cmd:
        return cmd
    raise RuntimeError(
        "ebook-convert was not found.\n"
        "Install Calibre and make sure ebook-convert is callable from your terminal.\n"
        "On macOS it is often here:\n"
        "/Applications/calibre.app/Contents/MacOS/ebook-convert"
    )


def wipe_book_state(book_out_dir: Path):
    temp_dir = book_out_dir / TEMP_DIRNAME
    manifest_path = book_out_dir / MANIFEST_FILENAME

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    if manifest_path.exists():
        manifest_path.unlink()


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists; it belongs to another user
    return True


class BookLock:
    """One conversion per book folder at a time.

    Two runs on the same book share `manifest.json` and the chunk names, so
    each can publish or delete the other's work. The Narrator tab runs one
    worker, but the CLI and the tab, or two tabs, on the same book would race.
    The lock file beside the manifest names the pid of the run that owns the
    folder. It is created with O_EXCL, so of two runs starting together only
    one wins; a lock whose pid is no longer running was left by a kill or a
    crash and is taken over. Released on the way out, whatever the way.
    """

    def __init__(self, book_out_dir: Path):
        self.path = book_out_dir / LOCK_FILENAME

    def __enter__(self):
        for _attempt in range(3):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                try:
                    holder = self._holder()
                except FileNotFoundError:
                    continue  # released between our two looks
                if holder is None or pid_is_alive(holder):
                    raise BookLocked(self._refusal(holder))
                self.path.unlink(missing_ok=True)  # stale: its process is gone
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            # Two runs that both found a stale lock can unlink each other's
            # fresh one; whoever's pid is in the file now owns the folder.
            if self._holder() == os.getpid():
                return self
            raise BookLocked(self._refusal(self._holder()))
        raise BookLocked(self._refusal(None))

    def __exit__(self, *_exc):
        self.path.unlink(missing_ok=True)

    def _holder(self) -> int | None:
        """The pid in the lock file, or None when it holds no pid."""
        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def _refusal(self, holder: int | None) -> str:
        who = f" (pid {holder})" if holder else ""
        return (
            f"Another conversion of {self.path.parent.name} is running{who}.\n"
            "Wait for it to finish, or stop it, then run again. If none is running, "
            f"delete {self.path} and run again."
        )


def matches_force_target(fp: Path, book_name: str, force_target: str | None) -> bool:
    if not force_target:
        return False

    candidates = {
        fp.name.lower(),
        fp.stem.lower(),
        book_name.lower(),
    }
    return force_target.lower() in candidates


# ------------------------------------------------------
# TEXT EXTRACTION
# ------------------------------------------------------

def extract_pdf(path: Path) -> str:
    reader = pypdf.PdfReader(str(path))
    text = ""
    for page in reader.pages:
        text += (page.extract_text() or "") + "\n"
    return text


def extract_epub_chapters(path: Path) -> list[tuple[str, str]]:
    """(title, text) per section, in reading order.

    Walks the **spine**, not `get_items()`. The manifest order `get_items()`
    returns is not the reading order, so a book whose files are not named in
    reading order was narrated with its chapters shuffled — and nothing said
    so, because the audio was fine, just in the wrong sequence.
    """
    book = epub.read_epub(str(path))
    sections: list[tuple[str, str]] = []
    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav):
            soup = BeautifulSoup(item.get_body_content(), "html.parser")
            heading = soup.find(["h1", "h2", "h3"])
            title = heading.get_text(" ", strip=True) if heading else ""
            for tag in soup(["script", "style", "header", "footer", "noscript"]):
                tag.extract()
            content = soup.get_text(separator="\n", strip=True)
            if content:
                sections.append((title or f"Section {len(sections) + 1}", content))
    return sections


def convert_mobi_to_epub(mobi_path: Path, work_dir: Path) -> Path:
    """Calibre's EPUB of `mobi_path`, written into `work_dir`.

    The caller hands over the run's temp dir, so the file goes when the chunks
    go: written beside the audiobook it stayed there for good.
    """
    ebook_convert = ensure_ebook_convert_available()
    work_dir.mkdir(parents=True, exist_ok=True)
    converted = work_dir / f"{mobi_path.stem}{CONVERTED_EPUB_SUFFIX}"

    print(f"  Converting {mobi_path.suffix.lstrip('.').upper()} -> EPUB with Calibre: "
          f"{mobi_path.name}")
    run_checked([ebook_convert, str(mobi_path), str(converted)], "ebook-convert")
    if not converted.exists():
        raise RuntimeError("ebook-convert reported success but wrote no file.")
    return converted


def load_chapters(path: Path, work_dir: Path | None = None) -> list[tuple[str, str]]:
    """(title, text) per section of the book, in reading order.

    Only EPUB, and what Calibre turns into EPUB, has sections. Everything else
    is one chapter named after the book.
    """
    suffix = path.suffix.lower()

    if suffix == ".epub":
        return extract_epub_chapters(path)
    if suffix in CALIBRE_SUFFIXES:
        if work_dir is None:
            raise ValueError(f"work_dir is required for {suffix} conversion")
        return extract_epub_chapters(convert_mobi_to_epub(path, work_dir))
    if suffix == ".pdf":
        return [(clean_name(path.name), extract_pdf(path))]
    if suffix == ".txt":
        return [(clean_name(path.name), path.read_text(encoding="utf-8", errors="ignore"))]

    raise ValueError(f"Unsupported file type: {path}")


def load_text(path: Path, work_dir: Path | None = None) -> str:
    return "\n\n".join(text for _, text in load_chapters(path, work_dir))


# ------------------------------------------------------
# TOKEN / COST HELPERS
# ------------------------------------------------------

def get_token_encoder():
    try:
        return tiktoken.encoding_for_model("gpt-4o-mini")
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def count_text_tokens(text: str) -> int:
    enc = get_token_encoder()
    return len(enc.encode(text))


def estimate_audio_tokens_from_seconds(seconds: float) -> int:
    return int(round(seconds * 20))


def estimate_costs_usd(text_tokens: int, audio_tokens: int) -> dict:
    input_cost = (text_tokens / 1_000_000) * USD_PER_1M_INPUT_TOKENS
    output_cost = (audio_tokens / 1_000_000) * USD_PER_1M_OUTPUT_AUDIO_TOKENS
    total = input_cost + output_cost
    return {
        "input_usd": input_cost,
        "output_usd": output_cost,
        "total_usd": total,
    }


def usd_to_eur(usd_amount: float, eur_per_usd: float = EUR_PER_USD_FALLBACK) -> float:
    return usd_amount * eur_per_usd


def estimate_audio_seconds_from_text(text: str, words_per_minute: float = 150.0) -> float:
    words = len(text.split())
    minutes = words / words_per_minute if words_per_minute else 0
    return minutes * 60.0


def get_audio_duration_seconds(audio_path: Path) -> float:
    result = run_checked([
        ensure_ffprobe_available(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ], "ffprobe")
    return float(result.stdout.strip())


def print_cost_estimate(label: str, text_tokens: int, audio_seconds: float):
    audio_tokens = estimate_audio_tokens_from_seconds(audio_seconds)
    costs = estimate_costs_usd(text_tokens, audio_tokens)

    total_eur = usd_to_eur(costs["total_usd"])
    input_eur = usd_to_eur(costs["input_usd"])
    output_eur = usd_to_eur(costs["output_usd"])

    print(f"  {label}")
    print(f"    Text tokens: ~{text_tokens:,}")
    print(f"    Audio duration: ~{audio_seconds/60:.1f} min")
    print("    Cost estimate:")
    print(f"      Input:  ${costs['input_usd']:.4f} / €{input_eur:.4f}")
    print(f"      Output: ${costs['output_usd']:.4f} / €{output_eur:.4f}")
    print(f"      Total:  ${costs['total_usd']:.4f} / €{total_eur:.4f}")


# ------------------------------------------------------
# TOKEN-SAFE CHUNKING
# ------------------------------------------------------

def chunk_text(text: str, max_tokens: int = MAX_INPUT_TOKENS_PER_CHUNK) -> list[str]:
    enc = get_token_encoder()
    words = text.split()

    chunks = []
    current_words = []
    current_text = ""

    for word in words:
        candidate_text = f"{current_text} {word}".strip()
        token_count = len(enc.encode(candidate_text))

        if token_count <= max_tokens:
            current_words.append(word)
            current_text = candidate_text
        else:
            if current_words:
                chunks.append(" ".join(current_words))
                current_words = [word]
                current_text = word
            else:
                chunks.append(word)
                current_words = []
                current_text = ""

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


# ------------------------------------------------------
# MANIFEST
# ------------------------------------------------------

def build_manifest(book_name: str, source_file: Path, chunks: list[str]) -> dict:
    return {
        "book_name": book_name,
        "source_file": str(source_file),
        "text_sha256": hashlib.sha256("\0".join(chunks).encode()).hexdigest(),
        "tts_model": TTS_MODEL,
        "tts_voice": TTS_VOICE,
        "tts_instructions": TTS_INSTRUCTIONS,
        "max_input_tokens_per_chunk": MAX_INPUT_TOKENS_PER_CHUNK,
        "total_chunks": len(chunks),
        "format": MANIFEST_FORMAT,
        "chunks": [
            {
                "index": i,
                "filename": f"chunk_{i}.mp3",
                "status": "pending",
                "text_word_count": len(chunk.split()),
            }
            for i, chunk in enumerate(chunks)
        ],
    }


def load_or_create_manifest(
    manifest_path: Path,
    book_name: str,
    source_file: Path,
    chunks: list[str],
    temp_dir: Path | None = None,
) -> dict:
    expected = build_manifest(book_name, source_file, chunks)

    if not manifest_path.exists():
        json_dump(manifest_path, expected)
        return expected

    existing = json_load(manifest_path)

    compatible = (
        existing.get("book_name") == expected["book_name"]
        and existing.get("source_file") == expected["source_file"]
        and existing.get("text_sha256") == expected["text_sha256"]
        and existing.get("tts_model") == expected["tts_model"]
        and existing.get("tts_voice") == expected["tts_voice"]
        and existing.get("tts_instructions") == expected["tts_instructions"]
        and existing.get("max_input_tokens_per_chunk") == expected["max_input_tokens_per_chunk"]
        and existing.get("total_chunks") == expected["total_chunks"]
    )

    if not compatible:
        if ON_SETTINGS_CHANGE == REFUSE_ON_CHANGE:
            raise SettingsChanged(
                "Source text or settings changed since this run began. The "
                "audio generated so far cannot be reused safely. Run again with "
                f'--force-rebuild "{book_name}" to start over.'
            )
        print("  ⚠️ Existing manifest does not match current run.")
        print("  Rebuilding manifest from scratch.")
        # The cached chunk files were made under the OLD chunking/voice.
        # sync_manifest_with_files trusts file existence alone, so leaving
        # them here would stitch mispositioned, possibly different-voice
        # audio into a "completed" book. Stale caches are wiped with the
        # manifest they belonged to.
        if temp_dir is not None and temp_dir.exists():
            stale = sorted(temp_dir.glob("chunk_*.mp3")) + sorted(
                temp_dir.glob("chunk_*.mp3" + CHUNK_PARTIAL_SUFFIX))
            for chunk_file in stale:
                chunk_file.unlink()
            if stale:
                print(f"  Cleared {len(stale)} stale chunk file(s) from the "
                      "previous settings.")
        json_dump(manifest_path, expected)
        return expected

    return existing


def sync_manifest_with_files(manifest: dict, temp_dir: Path) -> dict:
    """Make the manifest agree with the chunk files on disk.

    A chunk under its final name is complete, because it only gets that name
    once its stream has finished. Two exceptions: a partial left by a stop is
    swept, and a manifest from before partial files existed is trusted only
    where it recorded the chunk as done, since a chunk it never recorded may
    be the one a stop cut short.
    """
    for partial in temp_dir.glob("chunk_*.mp3" + CHUNK_PARTIAL_SUFFIX):
        partial.unlink(missing_ok=True)

    legacy = manifest.get("format", 1) < MANIFEST_FORMAT
    for entry in manifest["chunks"]:
        chunk_file = temp_dir / entry["filename"]
        present = chunk_file.exists() and chunk_file.stat().st_size > 0
        if present and legacy and entry["status"] != "done":
            chunk_file.unlink()
            present = False
        entry["status"] = "done" if present else "pending"

    manifest["format"] = MANIFEST_FORMAT
    return manifest


# ------------------------------------------------------
# TTS WITH RETRIES
# ------------------------------------------------------

def generate_tts_chunk(text: str, temp_path: Path, retries: int = RETRIES) -> bool:
    partial_path = temp_path.with_name(temp_path.name + CHUNK_PARTIAL_SUFFIX)
    for attempt in range(1, retries + 1):
        try:
            kwargs = {
                "model": TTS_MODEL,
                "voice": TTS_VOICE,
                "input": text,
            }
            if TTS_INSTRUCTIONS:
                kwargs["instructions"] = TTS_INSTRUCTIONS

            with get_client().audio.speech.with_streaming_response.create(**kwargs) as response:
                response.stream_to_file(str(partial_path))
            os.replace(partial_path, temp_path)
            return True

        except AuthenticationError as e:
            partial_path.unlink(missing_ok=True)
            print(f"\n❌ Authentication failed: {e}")
            print("   Check your OPENAI_API_KEY in .env")
            return False

        except Exception as e:
            partial_path.unlink(missing_ok=True)
            err_str = str(e)
            if any(marker in err_str for marker in (
                    "insufficient_quota", "exceeded your current quota", "Billing hard limit")):
                print("\n❌ insufficient_quota: Your OpenAI account has run out of credit.")
                print("   Top up your account at platform.openai.com/settings/billing")
                print("   Then run again — progress will resume automatically.")
                return False

            print(f"\n⚠️ Error generating chunk (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                wait = 2 + random.random() * 2
                print(f"   Waiting {wait:.1f}s before retry...")
                time.sleep(wait)

    print("\n❌ All retries failed for this chunk.")
    return False


# ------------------------------------------------------
# FFMPEG MERGE
# ------------------------------------------------------

def ffmpeg_escape_concat_path(path: Path) -> str:
    return str(path.resolve()).replace("'", r"'\''")


def ffmetadata_escape(value: str) -> str:
    """Escape a chapter title for an ffmetadata file.

    One line, because the parser ends a value at any line break, with the
    characters ffmetadata gives meaning to escaped.
    """
    value = " ".join(value.split())
    for source, target in (("\\", "\\\\"), ("=", "\\="), (";", "\\;"), ("#", "\\#")):
        value = value.replace(source, target)
    return value


def merge_chunks_with_ffmpeg(
    temp_dir: Path,
    output_path: Path,
    total_chunks: int,
    chapter_starts: list[tuple[str, int]] | None = None,
    audio_format: str = DEFAULT_FORMAT,
):
    """Stitch the finished chunks into one file.

    MP3 is a stream copy: the chunks are already MP3, so nothing is re-encoded
    and the merge is fast and lossless. M4B re-encodes to AAC because the
    container needs it, and carries chapter marks built from the measured
    duration of each chunk — which is why it costs a probe per chunk and MP3
    does not.
    """
    ffmpeg = ensure_ffmpeg_available()

    concat_file = temp_dir / FFMPEG_CONCAT_FILENAME
    chunk_paths = []
    for i in range(total_chunks):
        chunk_path = temp_dir / f"chunk_{i}.mp3"
        if not chunk_path.exists() or chunk_path.stat().st_size == 0:
            raise RuntimeError(f"Missing or empty chunk during merge: {chunk_path.name}")
        chunk_paths.append(chunk_path)

    concat_file.write_text(
        "".join(f"file '{ffmpeg_escape_concat_path(path)}'\n" for path in chunk_paths),
        encoding="utf-8",
    )

    temp_output = output_path.with_suffix(f".tmp.{audio_format}")
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]
    if audio_format == FORMAT_MP3:
        cmd += ["-c", "copy"]
    elif audio_format == FORMAT_M4B:
        metadata_file = write_chapter_metadata(
            temp_dir, output_path.stem, chunk_paths, chapter_starts or [])
        cmd += ["-i", str(metadata_file), "-map", "0:a:0", "-map_metadata", "1",
                "-map_chapters", "1", "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+faststart"]
    else:
        raise ValueError(f"Unsupported audio format: {audio_format!r}")
    cmd.append(str(temp_output))

    run_checked(cmd, f"ffmpeg {audio_format.upper()} merge")
    temp_output.replace(output_path)


def write_chapter_metadata(
    temp_dir: Path,
    title: str,
    chunk_paths: list[Path],
    chapter_starts: list[tuple[str, int]],
) -> Path:
    """An ffmetadata file placing each chapter at its measured offset.

    Every chunk is probed once. The probes run in parallel because a long book
    has hundreds of chunks and each probe is a process.
    """
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        durations_ms = [round(seconds * 1000) for seconds in
                        executor.map(get_audio_duration_seconds, chunk_paths)]
    offsets = [0]
    for duration in durations_ms:
        offsets.append(offsets[-1] + duration)

    # A chapter ends where the next begins; the last one ends with the book.
    ends = [start for _, start in chapter_starts[1:]] + [len(chunk_paths)]
    metadata = [";FFMETADATA1", f"title={ffmetadata_escape(title)}"]
    for (chapter_title, first_chunk), end_chunk in zip(chapter_starts, ends):
        metadata += [
            "[CHAPTER]", "TIMEBASE=1/1000",
            f"START={offsets[first_chunk]}", f"END={offsets[end_chunk]}",
            f"title={ffmetadata_escape(chapter_title)}",
        ]

    metadata_file = temp_dir / CHAPTER_METADATA_FILENAME
    metadata_file.write_text("\n".join(metadata) + "\n", encoding="utf-8")
    return metadata_file


# ------------------------------------------------------
# TEXT -> AUDIO
# ------------------------------------------------------

def text_to_audio(
    chapters: list[tuple[str, str]],
    source_file: Path,
    book_name: str,
    output_path: Path,
    temp_dir: Path,
    manifest_path: Path,
    audio_format: str = DEFAULT_FORMAT,
) -> bool:
    print("  Preparing text chunks...")
    # A chapter mark needs its chapter to start on a chunk boundary, so M4B
    # chunks chapter by chapter. MP3 carries no marks, so it chunks the whole
    # book in one pass: those are the boundaries earlier versions drew, which
    # keeps a run paused under one of them resumable, and it saves the short
    # chunk (one TTS request) every section would otherwise end on.
    if audio_format != FORMAT_M4B:
        chapters = [(book_name, "\n\n".join(text for _, text in chapters))]
    chunks: list[str] = []
    chapter_starts: list[tuple[str, int]] = []
    for title, chapter_text in chapters:
        chapter_chunks = chunk_text(chapter_text, MAX_INPUT_TOKENS_PER_CHUNK)
        if chapter_chunks:
            chapter_starts.append((title, len(chunks)))
            chunks.extend(chapter_chunks)
    total_chunks = len(chunks)
    print(f"  Total chunks needed: {total_chunks}")

    if total_chunks == 0:
        print("  ❌ No usable text found.")
        return False

    temp_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_or_create_manifest(
        manifest_path, book_name, source_file, chunks, temp_dir=temp_dir)
    manifest = sync_manifest_with_files(manifest, temp_dir)
    json_dump(manifest_path, manifest)

    completed_before = sum(1 for c in manifest["chunks"] if c["status"] == "done")
    print(f"  Found {completed_before}/{total_chunks} completed chunks.")

    pending_jobs = []
    for i, chunk in enumerate(chunks):
        entry = manifest["chunks"][i]
        temp_path = temp_dir / entry["filename"]

        if entry["status"] == "done" and temp_path.exists() and temp_path.stat().st_size > 0:
            continue

        pending_jobs.append((i, chunk, temp_path))

    if not pending_jobs:
        print("  All chunks already generated. Proceeding to merge...")
    else:
        print(f"  Generating {len(pending_jobs)} missing chunks with {MAX_WORKERS} workers...")

    completed_now = completed_before
    save_counter = 0

    def worker(job):
        i, chunk, temp_path = job
        ok = generate_tts_chunk(chunk, temp_path, retries=RETRIES)
        return i, ok

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker, job) for job in pending_jobs]

        for future in as_completed(futures):
            i, ok = future.result()

            if not ok:
                manifest["chunks"][i]["status"] = "pending"
                json_dump(manifest_path, manifest)
                print("\n❌ Stopping now. Resume will continue automatically next run.")
                return False

            manifest["chunks"][i]["status"] = "done"
            completed_now += 1
            save_counter += 1

            print_progress(completed_now, total_chunks, prefix="  Progress ")

            if save_counter >= MANIFEST_SAVE_EVERY or completed_now == total_chunks:
                json_dump(manifest_path, manifest)
                save_counter = 0

    remaining = [c["index"] for c in manifest["chunks"] if c["status"] != "done"]
    if remaining:
        print(f"  ❌ Cannot merge. Incomplete chunks remain: {remaining[:10]}")
        return False

    print("  Merging chunks into final audiobook with ffmpeg...")
    merge_chunks_with_ffmpeg(temp_dir, output_path, total_chunks,
                             chapter_starts, audio_format)
    print(f"  Audiobook finished: {output_path}")

    return True


def cleanup_after_success(temp_dir: Path, manifest_path: Path):
    print("  Removing temp chunks and manifest...")
    for pattern in ("chunk_*.mp3", "chunk_*.mp3" + CHUNK_PARTIAL_SUFFIX):
        for f in temp_dir.glob(pattern):
            f.unlink(missing_ok=True)

    concat_file = temp_dir / FFMPEG_CONCAT_FILENAME
    concat_file.unlink(missing_ok=True)
    (temp_dir / CHAPTER_METADATA_FILENAME).unlink(missing_ok=True)
    for f in temp_dir.glob("*" + CONVERTED_EPUB_SUFFIX):
        f.unlink(missing_ok=True)

    manifest_path.unlink(missing_ok=True)

    try:
        temp_dir.rmdir()
    except OSError:
        pass


# ------------------------------------------------------
# CLI
# ------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Convert ebooks to audiobooks with OpenAI TTS.")

    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Path to one ebook file or a folder containing ebooks. If omitted, uses the default books folder."
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output root folder. If omitted, uses the default OUTPUT_ROOT."
    )

    parser.add_argument(
        "--voice",
        type=str,
        default=TTS_VOICE,
        help=f"TTS voice to use. Default: {TTS_VOICE}"
    )

    parser.add_argument(
        "--chunk-tokens",
        type=int,
        default=MAX_INPUT_TOKENS_PER_CHUNK,
        help=f"Maximum estimated input tokens per TTS chunk. Default: {MAX_INPUT_TOKENS_PER_CHUNK}"
    )

    parser.add_argument(
        "--force-rebuild",
        type=str,
        default=None,
        help="Wipe old manifest/temp data for one book. Use original filename stem or cleaned book name."
    )

    parser.add_argument(
        "--format",
        dest="audio_format",
        choices=list(AUDIO_FORMATS),
        default=DEFAULT_FORMAT,
        help=("Output container. mp3 copies the chunks losslessly and plays "
              "anywhere; m4b re-encodes to AAC and carries chapter marks. "
              f"Default: {DEFAULT_FORMAT}")
    )

    return parser.parse_args()


# ------------------------------------------------------
# MAIN
# ------------------------------------------------------

def convert(input=None, output=None, voice=None, chunk_tokens=None,
            force_rebuild=None, audio_format=None):
    """Convert one ebook file, or a folder of ebooks, into audiobook(s).

    `audio_format` is "mp3" (default: a lossless stream copy that plays
    anywhere) or "m4b" (AAC with chapter marks, which audiobook players
    navigate by).

    Importable in-process entry point used by the app's ToolRunner and GUI.
    Returns True on full success, False if it failed / paused / found nothing.
    """
    global TTS_VOICE, MAX_INPUT_TOKENS_PER_CHUNK  # allow callers to override global defaults

    input_path = Path(input).expanduser() if input else BOOKS_DIR  # use given input or default books folder
    output_root = Path(output).expanduser() if output else OUTPUT_ROOT  # use given output or default output root

    if voice:
        TTS_VOICE = voice  # override voice
    if chunk_tokens:
        MAX_INPUT_TOKENS_PER_CHUNK = chunk_tokens  # override chunk token size

    audio_format = (audio_format or DEFAULT_FORMAT).lower()
    if audio_format not in AUDIO_FORMATS:
        print(f"❌ Unknown audio format: {audio_format!r}. "
              f"Expected one of {', '.join(AUDIO_FORMATS)}.")
        return False

    # Both tools are first needed after every chunk has been generated and paid
    # for, so look for them before the first request rather than after the last.
    try:
        ensure_ffmpeg_available()
        if audio_format == FORMAT_M4B:
            ensure_ffprobe_available()
    except RuntimeError as e:
        print(f"❌ {e}")
        return False

    print(f"\n📚 Input path: {input_path}")  # show chosen input path
    print(f"🎧 Output root: {output_root}")  # show chosen output folder
    print(f"🗣️ Voice: {TTS_VOICE}")  # show chosen voice
    print(f"🧩 Chunk token limit: {MAX_INPUT_TOKENS_PER_CHUNK}")  # show chunk token limit
    print(f"📦 Format: {audio_format}")  # show chosen output format

    output_root.mkdir(parents=True, exist_ok=True)  # create output root if needed

    if not input_path.exists():
        print(f"❌ Input path not found: {input_path}")  # fail clearly if input does not exist
        return False

    if input_path.is_file():
        ebook_files = [input_path] if input_path.suffix.lower() in SUPPORTED_SUFFIXES else []  # single file mode
    else:
        ebook_files = sorted(
            f for f in input_path.iterdir()
            if f.suffix.lower() in SUPPORTED_SUFFIXES
        )  # folder mode

    if not ebook_files:
        print("❌ No books found.")
        return False

    print(f"Found {len(ebook_files)} book(s):")
    for f in ebook_files:
        print("  -", f.name)

    for fp in ebook_files:
        print("\n==============================")
        print("📖 Processing:", fp.name)
        print("==============================")

        book_name = clean_name(fp.name)
        book_out_dir = output_root / book_name
        book_out_dir.mkdir(parents=True, exist_ok=True)

        try:
            with BookLock(book_out_dir):
                output_path = book_out_dir / f"{book_name}.{audio_format}"
                temp_dir = book_out_dir / TEMP_DIRNAME
                manifest_path = book_out_dir / MANIFEST_FILENAME

                if matches_force_target(fp, book_name, force_rebuild):
                    print(f"  🧹 Force rebuild requested for: {fp.name}")
                    wipe_book_state(book_out_dir)
                    if output_path.exists():
                        output_path.unlink()

                if output_path.exists():
                    print(f"  ✅ Final audiobook already exists, skipping: {output_path}")
                    continue

                # The chunks went when that run finished, so another format means
                # narrating the book again. Say so before the money goes.
                for other_format in AUDIO_FORMATS:
                    other_output = book_out_dir / f"{book_name}.{other_format}"
                    if other_format != audio_format and other_output.exists():
                        print(f"  ⚠️ {other_output.name} already exists; making {audio_format} "
                              "narrates the whole book again.")

                print("  Extracting text...")
                try:
                    chapters = load_chapters(fp, work_dir=temp_dir)
                except Exception as e:
                    print(f"  ❌ Failed to read file: {e}")
                    continue

                chapters = [(title, light_normalize(text)) for title, text in chapters]
                text = "\n\n".join(text for _, text in chapters)

                print("  Text length:", len(text))
                if audio_format == FORMAT_M4B:
                    print(f"  Chapters detected: {len(chapters)}")

                text_tokens = count_text_tokens(text)
                est_seconds = estimate_audio_seconds_from_text(text, words_per_minute=150.0)
                print_cost_estimate("Estimated cost before conversion:", text_tokens, est_seconds)

                try:
                    success = text_to_audio(
                        chapters=chapters,
                        source_file=fp,
                        book_name=book_name,
                        output_path=output_path,
                        temp_dir=temp_dir,
                        manifest_path=manifest_path,
                        audio_format=audio_format,
                    )
                except SettingsChanged as e:
                    print(f"\n❌ {e}")
                    return False
                except Exception as e:
                    print(f"\n❌ Fatal error while processing {fp.name}: {e}")
                    print("▶️ Fix the issue and run the script again to resume.")
                    return False

                if not success:
                    print("\n⏸️ Conversion paused.")
                    print("▶️ Run the script again later to automatically resume.")
                    return False

                try:
                    final_seconds = get_audio_duration_seconds(output_path)
                    print_cost_estimate("Final estimated cost after conversion:", text_tokens, final_seconds)
                except Exception as e:
                    print(f"  ⚠️ Could not calculate final duration/cost: {e}")

                cleanup_after_success(temp_dir, manifest_path)
        except BookLocked as e:
            print(f"  ❌ {e}")
            return False

    print("\n🎉 ALL BOOKS COMPLETED SUCCESSFULLY!")
    return True


def main():
    """CLI entry point. Also runnable as: python -m lab_hub.tools.narrator.converter

    Exits non-zero on any failure so the GUI (which keys off the process exit
    code) can tell a real failure apart from a successful run.
    """
    args = parse_args()
    try:
        ok = convert(
            input=args.input,
            output=args.output,
            voice=args.voice,
            chunk_tokens=args.chunk_tokens,
            force_rebuild=args.force_rebuild,
            audio_format=args.audio_format,
        )
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
