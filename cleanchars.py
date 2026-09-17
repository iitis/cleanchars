#!/usr/bin/env python3
"""
cleanchars - replace LLM "smart" Unicode with plain ASCII in code, Markdown and TeX.

Reports by default; --fix rewrites. Standard library only, no dependencies.

    cleanchars                        report on the current directory
    cleanchars --diff notes.md        preview the change, touch nothing
    cleanchars --fix src/ docs/       rewrite in place (atomically)
    cleanchars --fix paper.tex        LaTeX spelling, picked automatically
    cleanchars -o clean.md notes.md   write a cleaned copy, leave the input alone
    cat x | cleanchars --stdin        filter mode
    cleanchars --changed --fix        only the files git reports as changed

Profiles
--------
plain   "-" for dashes, straight quotes.  Source code, Markdown, prose.
tex     LaTeX spellings: "--" en dash, "---" em dash, ` and `` for opening
        quotes, "~" for a no-break space, \\ldots{}, \\, for a thin space,
        "-" for a non-breaking hyphen (--nb-hyphen to keep it unbreakable).
        Maths symbols are reported rather than replaced, because the source
        does not say whether they sit in maths mode.
Chosen from the file extension (.tex .ltx .sty .cls .dtx .bib .tikz .pgf);
override with --profile.

Policy
------
REPLACE  typographic punctuation, exotic spaces, arrows, common maths signs,
         full-width forms  ->  ASCII
DELETE   zero-width characters, bidi controls, variation selectors, tag block
ERROR    things that cannot be recovered and must not be guessed at: U+FFFD,
         U+FFFC, invisible maths operators, mojibake, and any other Cc/Cf
         character missing from the tables
KEEP     every other legitimate Unicode character (accents, CJK, Greek).
         --strict-ascii reports those as errors; nothing is ever transliterated,
         so this is a curated cleaner, not an "ASCII-only" guarantee.

--fix applies the safe transformations even when errors remain, and reports the
errors; mojibake is the one case where the whole file is left alone.

No NFKC: it rewrites mathematical notation. No normalisation at all unless
--nfc is passed. Semantic symbols (x / != <= -> and friends) are replaced by
default for ASCII-only renderers; use --semantic=error in TeX or maths code.

Exit codes: 0 clean, 1 findings remain, 2 usage error.
This file is pure ASCII, so running cleanchars on cleanchars.py is a no-op.
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable, Iterator

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# File selection
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS = {
    # Documentation / scientific writing
    ".md", ".mdx", ".tex", ".ltx", ".sty", ".cls", ".dtx", ".bib",
    ".tikz", ".pgf", ".rst", ".txt", ".org", ".adoc", ".asciidoc", ".typ",
    # Python
    ".py", ".pyi", ".pyx",
    # JS / TS / web
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".css", ".scss", ".less", ".html", ".htm",
    # Compiled languages
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".rs", ".go", ".java",
    ".kt", ".kts", ".cs", ".swift", ".scala", ".m", ".mm", ".zig",
    # Shell / config / data
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".sql", ".graphql", ".proto", ".tf", ".hcl",
    # Build
    ".mk", ".cmake", ".gradle", ".bzl",
}

SPECIAL_FILENAMES = {
    "Makefile", "Dockerfile", "CMakeLists.txt", "Justfile", "Rakefile",
    "BUILD", "WORKSPACE", ".gitignore", ".gitattributes", ".editorconfig",
}

SKIP_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", ".tox", "node_modules", "dist", "build",
    "target", ".next", "vendor", "site-packages",
}

MAX_BYTES = 5 * 1024 * 1024

# ---------------------------------------------------------------------------
# 1. Replacements.  Explicit table, not blanket compatibility normalisation.
# ---------------------------------------------------------------------------

REPLACEMENTS: dict[str, str] = {
    # Hyphens, dashes, mathematical minus
    "\u2010": "-",       # HYPHEN
    "\u2011": "-",       # NON-BREAKING HYPHEN
    "\u2012": "-",       # FIGURE DASH
    "\u2013": "-",       # EN DASH
    "\u2014": "-",       # EM DASH  (overridable with --em-dash)
    "\u2015": "-",       # HORIZONTAL BAR
    "\u2212": "-",       # MINUS SIGN
    "\ufe58": "-",       # SMALL EM DASH
    "\ufe63": "-",       # SMALL HYPHEN-MINUS

    # Single quotation marks and apostrophes
    "\u2018": "'",       # LEFT SINGLE QUOTATION MARK
    "\u2019": "'",       # RIGHT SINGLE QUOTATION MARK
    "\u201a": "'",       # SINGLE LOW-9 QUOTATION MARK
    "\u201b": "'",       # SINGLE HIGH-REVERSED-9 QUOTATION MARK
    "\u2032": "'",       # PRIME
    "\u2035": "'",       # REVERSED PRIME
    "\u2039": "'",       # SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    "\u203a": "'",       # SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    "\u02b9": "'",       # MODIFIER LETTER PRIME
    "\u02bc": "'",       # MODIFIER LETTER APOSTROPHE

    # Double quotation marks
    "\u201c": '"',       # LEFT DOUBLE QUOTATION MARK
    "\u201d": '"',       # RIGHT DOUBLE QUOTATION MARK
    "\u201e": '"',       # DOUBLE LOW-9 QUOTATION MARK
    "\u201f": '"',       # DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    "\u2033": '"',       # DOUBLE PRIME
    "\u2036": '"',       # REVERSED DOUBLE PRIME
    "\u00ab": '"',       # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
    "\u00bb": '"',       # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
    "\u301d": '"',       # REVERSED DOUBLE PRIME QUOTATION MARK
    "\u301e": '"',       # DOUBLE PRIME QUOTATION MARK

    # Ellipsis and dot leaders
    "\u2024": ".",       # ONE DOT LEADER
    "\u2025": "..",      # TWO DOT LEADER
    "\u2026": "...",     # HORIZONTAL ELLIPSIS
    "\u203c": "!!",      # DOUBLE EXCLAMATION MARK
    "\u2047": "??",      # DOUBLE QUESTION MARK

    # Spaces
    "\u00a0": " ",       # NO-BREAK SPACE
    "\u1680": " ",       # OGHAM SPACE MARK
    "\u2000": " ", "\u2001": " ", "\u2002": " ", "\u2003": " ",
    "\u2004": " ", "\u2005": " ", "\u2006": " ", "\u2007": " ",
    "\u2008": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ",       # NARROW NO-BREAK SPACE
    "\u205f": " ",       # MEDIUM MATHEMATICAL SPACE
    "\u3000": " ",       # IDEOGRAPHIC SPACE

    # Line and paragraph separators
    "\u2028": "\n",      # LINE SEPARATOR
    "\u2029": "\n\n",    # PARAGRAPH SEPARATOR

    # Bullets and list marks
    "\u2022": "-",       # BULLET
    "\u2023": "-",       # TRIANGULAR BULLET
    "\u2043": "-",       # HYPHEN BULLET
    "\u00b7": "-",       # MIDDLE DOT
    "\u25cf": "-",       # BLACK CIRCLE
    "\u25aa": "-",       # BLACK SMALL SQUARE

    # Arrows, very common in generated comments and docs
    "\u2190": "<-",      # LEFTWARDS ARROW
    "\u2192": "->",      # RIGHTWARDS ARROW
    "\u2194": "<->",     # LEFT RIGHT ARROW
    "\u21d0": "<=",      # LEFTWARDS DOUBLE ARROW
    "\u21d2": "=>",      # RIGHTWARDS DOUBLE ARROW
    "\u21d4": "<=>",     # LEFT RIGHT DOUBLE ARROW

    # Maths signs that LLMs sprinkle into prose
    "\u00d7": "x",       # MULTIPLICATION SIGN
    "\u00f7": "/",       # DIVISION SIGN
    "\u2260": "!=",      # NOT EQUAL TO
    "\u2264": "<=",      # LESS-THAN OR EQUAL TO
    "\u2265": ">=",      # GREATER-THAN OR EQUAL TO
    "\u2248": "~=",      # ALMOST EQUAL TO

    # Symbols that break monospaced and legacy renderers
    "\u2122": "(TM)",    # TRADE MARK SIGN
    "\u00ae": "(R)",     # REGISTERED SIGN
    "\u00a9": "(C)",     # COPYRIGHT SIGN

    # CJK brackets
    "\u3010": "[",       # LEFT BLACK LENTICULAR BRACKET
    "\u3011": "]",       # RIGHT BLACK LENTICULAR BRACKET
    "\u300c": '"', "\u300d": '"',
}

# Full-width ASCII forms: U+FF01..U+FF5E map systematically onto U+0021..U+007E.
for _cp in range(0xFF01, 0xFF5F):
    REPLACEMENTS.setdefault(chr(_cp), chr(_cp - 0xFEE0))

# ---------------------------------------------------------------------------
# 2. Deletions: invisible formatting characters.
# ---------------------------------------------------------------------------

REMOVE: set[str] = {
    "\u00ad",  # SOFT HYPHEN
    "\u034f",  # COMBINING GRAPHEME JOINER
    "\u061c",  # ARABIC LETTER MARK
    "\u115f", "\u1160",  # HANGUL FILLERS
    "\u17b4", "\u17b5",  # KHMER INHERENT VOWELS
    "\u180e",  # MONGOLIAN VOWEL SEPARATOR
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\u200e",  # LEFT-TO-RIGHT MARK
    "\u200f",  # RIGHT-TO-LEFT MARK
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # bidi embed/override
    "\u2060",  # WORD JOINER
    "\u2066", "\u2067", "\u2068", "\u2069",            # bidi isolates
    "\u206a", "\u206b", "\u206c", "\u206d", "\u206e", "\u206f",  # deprecated
    "\ufeff",  # BOM / ZERO WIDTH NO-BREAK SPACE
}
REMOVE.update(chr(cp) for cp in range(0xFE00, 0xFE10))      # variation selectors
REMOVE.update(chr(cp) for cp in range(0xE0100, 0xE01F0))    # supplementary VS
REMOVE.update(chr(cp) for cp in range(0xE0000, 0xE0080))    # Unicode tag block

# Joiners that are load-bearing in some scripts and in emoji sequences.  These
# are only deleted when they sit next to Latin/ASCII text, which is where
# zero-width steganography and accidental LLM leakage actually occur.
CONTEXT_SENSITIVE = ({"\u200c", "\u200d"}
                     | {chr(cp) for cp in range(0xFE00, 0xFE10)}
                     | {chr(cp) for cp in range(0xE0100, 0xE01F0)})

# A joiner is only meaningful after a character that can actually be joined: a
# unicased letter (CJK, Arabic, Indic), a combining mark, or a symbol such as
# an emoji.  Punctuation does not qualify -- an em dash followed by a ZWJ is
# hidden data, not a ligature, and the dash's ASCII replacement must not be
# mistaken for script context either.
JOINABLE_CATEGORIES = {"Lo", "Lm", "Mn", "Mc", "Me", "So"}
CONTEXT_THRESHOLD = 0x0590  # below this there is no script needing joiners

# Symbols whose replacement changes meaning rather than encoding.  Replaced by
# default (renderers that cannot show them are the whole point of this tool),
# but --semantic=error or --semantic=keep is the right choice for TeX maths.
SEMANTIC_SYMBOLS = (
    "\u00b7\u00d7\u00f7"                    # middle dot, multiplication, division
    "\u2260\u2264\u2265\u2248"              # != <= >= ~=
    "\u2190\u2192\u2194\u21d0\u21d2\u21d4"  # arrows
    "\u2032\u2033\u2035\u2036"              # primes: derivative, feet, minutes
)

# ---------------------------------------------------------------------------
# 3. Characters we refuse to guess at.
# ---------------------------------------------------------------------------

HARD_ERRORS: dict[str, str] = {
    "\ufffd": "source data was already decoded lossily",
    "\ufffc": "underlying object or content is unknown",
    "\u2061": "invisible maths operator, meaning cannot be recovered",
    "\u2062": "invisible maths operator, meaning cannot be recovered",
    "\u2063": "invisible maths operator, meaning cannot be recovered",
    "\u2064": "invisible maths operator, meaning cannot be recovered",
}

ALLOWED_CONTROLS = {"\t", "\n", "\r"}

# ---------------------------------------------------------------------------
# LaTeX profile.  TeX has its own ASCII spellings for typography, so the plain
# mappings are actively wrong in a .tex file: "-" is a hyphen, an en dash is
# "--" and an em dash is "---"; a straight ' renders as a closing quote, so an
# opening quote must be written as ` or ``.
# ---------------------------------------------------------------------------

TEX_REPLACEMENTS: dict[str, str] = {
    # Dashes: length is spelled out in ASCII, so the distinction survives.
    "\u2010": "-",           # HYPHEN
    "\u2011": "-",           # NON-BREAKING HYPHEN (overridable, see --nb-hyphen)
    "\u2012": "--",          # FIGURE DASH
    "\u2013": "--",          # EN DASH        2019--2025, May--August
    "\u2014": "---",         # EM DASH        clause --- like this
    "\u2015": "---",         # HORIZONTAL BAR

    # Quotes: directional, and TeX spells the opening ones with backticks.
    "\u2018": "`",           # LEFT SINGLE
    "\u2019": "'",           # RIGHT SINGLE / apostrophe
    "\u201c": "``",          # LEFT DOUBLE
    "\u201d": "''",          # RIGHT DOUBLE

    # Spacing: ~ is a non-breaking space, \, is a thin space.
    "\u00a0": "~",
    "\u2009": "\\,",
    "\u202f": "\\,",

    # Commands rather than literal punctuation.
    "\u2026": "\\ldots{}",
    "\u2022": "\\textbullet{}",
    "\u2122": "\\texttrademark{}",
    "\u00ae": "\\textregistered{}",
    "\u00a9": "\\textcopyright{}",
}

# In a .tex file these have no single correct ASCII form: the right answer
# depends on maths mode, on the language package, or on both.  Report them.
TEX_ERRORS: dict[str, str] = {
    "\u2212": "minus sign: write - inside maths, $-$ in text",
}
for _ch in "\u201a\u201b\u201e\u201f\u00ab\u00bb\u2039\u203a\u301d\u301e\u300c\u300d":
    TEX_ERRORS[_ch] = ("no unambiguous LaTeX form; depends on the language "
                       "package (csquotes, babel)")

TEX_EXTENSIONS = {".tex", ".ltx", ".sty", ".cls", ".dtx", ".bib", ".tikz", ".pgf"}

# U+2011 forbids a line break at the hyphen; a plain "-" does not, so mapping
# it to "-" lets TeX split Sentinel-/2 and U-/Net across lines.
NB_HYPHEN_FORMS = {
    "mbox": "\\mbox{-}",          # kernel only, no package required
    "nobreakdash": "\\nobreakdash-",   # tidier source, needs amsmath
    "plain": "-",                 # accept the break (default)
}

# Mojibake: UTF-8 bytes that were decoded as CP1252 or Latin-1.  This is a
# different fault from stray smart punctuation and the fix is to re-decode the
# file, not to clean it -- running the replacement table over "don't" spelt
# as a-circumflex + euro + trade-mark would destroy the evidence.  Only two
# signatures are checked, both of which are essentially impossible in real text.
MOJIBAKE_SIGNATURES = {
    "\u00e2\u20ac": "UTF-8 punctuation decoded as CP1252",
    "\u00c2\u00a0": "UTF-8 no-break space decoded as CP1252",
}

REPLACE, DELETE, ERROR = "replace", "delete", "error"


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

class Finding:
    __slots__ = ("line", "column", "char", "kind", "detail")

    def __init__(self, line: int, column: int, char: str, kind: str, detail: str):
        self.line = line
        self.column = column
        self.char = char
        self.kind = kind
        self.detail = detail

    @property
    def fixable(self) -> bool:
        return self.kind in (REPLACE, DELETE)

    def render(self, path: str) -> str:
        name = unicodedata.name(self.char, "<unnamed>")
        where = "%s:%d:%d:" % (path, self.line, self.column)
        glyph = "U+%04X %s" % (ord(self.char), name)
        if self.kind == REPLACE:
            return "%s %s -> %r" % (where, glyph, self.detail)
        if self.kind == DELETE:
            return "%s %s -> DELETE" % (where, glyph)
        return "%s ERROR: %s: %s" % (where, glyph, self.detail)


class Policy:
    def __init__(self, em_dash: str | None = None, keep: set[str] | None = None,
                 strict_ascii: bool = False, context_guard: bool = True,
                 nfc: bool = False, semantic: str | None = None,
                 profile: str = "plain", nb_hyphen: str = "plain"):
        self.profile = profile
        self.replacements = dict(REPLACEMENTS)
        self.hard_errors = dict(HARD_ERRORS)
        self.remove = set(REMOVE)

        if profile == "tex":
            self.replacements.update(TEX_REPLACEMENTS)
            self.replacements["\u2011"] = NB_HYPHEN_FORMS[nb_hyphen]
            for ch, reason in TEX_ERRORS.items():
                self.replacements.pop(ch, None)
                self.hard_errors[ch] = reason

        # Defaults differ per profile; an explicit flag always wins.
        if em_dash is None:
            em_dash = "---" if profile == "tex" else "-"
        if semantic is None:
            # In TeX we cannot tell maths mode from text mode, so replacing
            # \times or \le would be a guess.  Report instead.
            semantic = "error" if profile == "tex" else "replace"
        self.replacements["\u2014"] = em_dash

        if semantic != "replace":
            for ch in SEMANTIC_SYMBOLS:
                self.replacements.pop(ch, None)
                if semantic == "error":
                    self.hard_errors[ch] = (
                        "semantic symbol; write the maths command you mean"
                        if profile == "tex" else
                        "semantic symbol; replacing it would change meaning, "
                        "not just encoding")

        self.keep = keep or set()
        self.strict_ascii = strict_ascii
        self.context_guard = context_guard
        self.nfc = nfc


def joinable(ch: str) -> bool:
    """True when a zero-width joiner after `ch` could be load-bearing."""
    if ord(ch) <= CONTEXT_THRESHOLD:
        return False
    return unicodedata.category(ch) in JOINABLE_CATEGORIES


def scan_once(text: str, policy: Policy) -> tuple[str, list[Finding]]:
    """One pass over the text: replace, delete and report, without normalising.

    Findings carry line/column positions into the text handed in, so check
    mode and fix mode never disagree.
    """
    out: list[str] = []
    findings: list[Finding] = []
    line, column = 1, 1
    emitted = ""          # last character actually written, not merely read

    for ch in text:
        if ch in policy.keep:
            out.append(ch)

        elif ch in policy.hard_errors:
            findings.append(Finding(line, column, ch, ERROR, policy.hard_errors[ch]))
            out.append(ch)

        elif ch in policy.replacements:
            replacement = policy.replacements[ch]
            findings.append(Finding(line, column, ch, REPLACE, replacement))
            out.append(replacement)

        elif ch in policy.remove:
            if policy.context_guard and ch in CONTEXT_SENSITIVE and joinable(emitted):
                out.append(ch)          # emoji ZWJ sequence, Persian ZWNJ, etc.
            else:
                findings.append(Finding(line, column, ch, DELETE, ""))

        else:
            category = unicodedata.category(ch)
            if category in ("Cc", "Cf") and ch not in ALLOWED_CONTROLS:
                findings.append(Finding(
                    line, column, ch, ERROR,
                    "unexpected Unicode %s control/format character" % category))
            elif policy.strict_ascii and ord(ch) > 0x7F:
                findings.append(Finding(
                    line, column, ch, ERROR,
                    "non-ASCII character under --strict-ascii"))
            out.append(ch)

        if out and out[-1]:
            emitted = out[-1][-1]
        if ch == "\n":
            line += 1
            column = 1
        else:
            column += 1

    return "".join(out), findings


MAX_NFC_PASSES = 4


def scan(text: str, policy: Policy) -> tuple[str, list[Finding]]:
    """Clean the text until it satisfies the policy, then report what it found.

    Without --nfc that is exactly one pass.  With it, normalisation and
    replacement each create work for the other, in both directions:

        "="     + U+0338  composes to U+2260, which the policy must judge
        U+FF1D  + U+0338  replaces to "=" + U+0338, which then composes

    Doing either step once leaves characters the policy never examined, and a
    file that --fix called clean would fail the very next check.  So iterate
    to a fixed point.

    Findings come from the first pass, whose positions refer to the text as it
    was read; later passes contribute only characters not already reported.
    """
    if not policy.nfc:
        return scan_once(text, policy)

    cleaned, findings = scan_once(unicodedata.normalize("NFC", text), policy)
    reported = {f.char for f in findings}
    for _ in range(MAX_NFC_PASSES):
        candidate, extra = scan_once(unicodedata.normalize("NFC", cleaned), policy)
        if candidate == cleaned:
            break
        cleaned = candidate
        for finding in extra:
            if finding.char not in reported:
                reported.add(finding.char)
                findings.append(finding)
    return cleaned, findings


# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------

def profile_for(path: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    return "tex" if path.suffix.lower() in TEX_EXTENSIONS else "plain"


def should_process(path: Path, all_files: bool) -> bool:
    if all_files:
        return True
    return path.suffix.lower() in DEFAULT_EXTENSIONS or path.name in SPECIAL_FILENAMES


def looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def find_mojibake(text: str) -> str | None:
    for signature, reason in MOJIBAKE_SIGNATURES.items():
        index = text.find(signature)
        if index != -1:
            line = text.count("\n", 0, index) + 1
            return "line %d: %s; re-decode the file before cleaning it" % (line, reason)
    return None


def atomic_write(path: Path, data: bytes) -> None:
    """Write via a temporary file in the same directory, then rename.

    A crash or a full disk leaves the original intact rather than truncated,
    which matters when this runs unattended from a hook or from CI.

    Symlinks are resolved first: os.replace() on the link itself would silently
    turn it into a regular file and leave the real file dirty.
    """
    path = Path(os.path.realpath(path))
    handle, temporary = tempfile.mkstemp(dir=str(path.parent),
                                         prefix=".cleanchars-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def iter_files(inputs: Iterable[Path], all_files: bool,
               errors: list[str]) -> Iterator[Path]:
    """Files to inspect, plus any enumeration failures appended to `errors`.

    A path named on the command line is taken at face value: it bypasses the
    allowlist, and following a symlink there is the documented behaviour.
    Discovery is stricter, because a walk picks up whatever happens to be in
    the tree.  It yields regular files only -- a FIFO would block forever in
    read_bytes() and reports a size of zero, so --max-bytes does not save us --
    and it does not follow symlinks, which can point outside the tree the user
    named or into a directory the walk deliberately skipped.
    """
    def walk_error(exc: OSError) -> None:
        errors.append(str(exc))
        print("cleanchars: cannot read: %s" % exc, file=sys.stderr)

    seen: set[Path] = set()
    for item in inputs:
        if item.is_file():
            resolved = item.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield item                      # explicit files bypass the allowlist
            continue
        if not item.is_dir():
            errors.append("no such file or directory: %s" % item)
            print("cleanchars: no such file or directory: %s" % item,
                  file=sys.stderr)
            continue
        for root, dirs, names in os.walk(item, onerror=walk_error):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRECTORIES]
            for name in sorted(names):
                path = Path(root) / name
                if not should_process(path, all_files):
                    continue
                if path.is_symlink() or not path.is_file():
                    continue                    # see the docstring
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield path


def process_file(path: Path, policy: Policy, *, fix: bool, diff: bool,
                 quiet: bool, max_bytes: int = MAX_BYTES,
                 output: Path | None = None) -> bool:
    """Return True when the file satisfies the policy."""
    try:
        size = path.stat().st_size
        if max_bytes and size > max_bytes:
            print("%s: ERROR: %d bytes exceeds --max-bytes %d, not inspected"
                  % (path, size, max_bytes), file=sys.stderr)
            return False
        raw = path.read_bytes()
    except OSError as exc:
        print("%s: ERROR: %s" % (path, exc), file=sys.stderr)
        return False

    if looks_binary(raw):
        if output is not None:
            print("%s: ERROR: binary file, no copy written" % path,
                  file=sys.stderr)
            return False
        return True

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print("%s: ERROR: invalid UTF-8 at byte %d: %s" % (path, exc.start, exc.reason),
              file=sys.stderr)
        return False

    mojibake = find_mojibake(text)
    if mojibake:
        print("%s: ERROR: mojibake, %s" % (path, mojibake), file=sys.stderr)
        return False

    cleaned, findings = scan(text, policy)
    fixable = [f for f in findings if f.fixable]
    errors = [f for f in findings if not f.fixable]
    modified = cleaned != text

    if diff:
        sys.stdout.writelines(difflib.unified_diff(
            text.splitlines(True), cleaned.splitlines(True),
            fromfile=str(path), tofile="%s (cleaned)" % path))
    elif output is not None:
        try:
            if output.exists():
                atomic_write(output, cleaned.encode("utf-8"))
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(cleaned.encode("utf-8"))
        except OSError as exc:
            print("%s: ERROR writing output: %s" % (output, exc), file=sys.stderr)
            return False
        if not quiet:
            print("wrote: %s (%d change%s, source untouched)"
                  % (output, len(fixable), "" if len(fixable) == 1 else "s"))
    elif fix:
        if modified:
            try:
                atomic_write(path, cleaned.encode("utf-8"))
            except OSError as exc:
                print("%s: ERROR writing file: %s" % (path, exc), file=sys.stderr)
                return False
            if not quiet:
                print("fixed: %s (%d change%s)"
                      % (path, len(fixable), "" if len(fixable) == 1 else "s"))
    else:
        if not quiet:
            for finding in fixable:
                print(finding.render(str(path)))
            if modified and not fixable:
                # --nfc is the only transformation that has no per-character
                # finding, so say so rather than exiting 1 with no explanation.
                print("%s: normalisation would change this file" % path)

    for finding in errors:
        print(finding.render(str(path)), file=sys.stderr)

    if errors:
        return False
    return not (modified and not fix and output is None)


# ---------------------------------------------------------------------------
# --changed: the files this git repository reports as dirty
# ---------------------------------------------------------------------------

def git_changed_files() -> list[Path] | None:
    """Absolute paths of modified, added and untracked files, or None.

    None means "git could not answer" -- no git on PATH, or not a repository.
    Callers treat that as nothing to do rather than as a failure: --changed is
    built for automation, where exiting non-zero would break someone's turn
    over a condition they did not ask about.
    """
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True)
    except OSError:
        print("cleanchars: --changed needs git on PATH; nothing to do",
              file=sys.stderr)
        return None
    if root.returncode != 0:
        print("cleanchars: --changed only works inside a git repository; "
              "nothing to do", file=sys.stderr)
        return None
    base = Path(os.fsdecode(root.stdout.strip()))

    # -z is the machine-readable form: NUL-terminated records, never quoted,
    # so paths containing spaces or quotes survive.  -uall is required because
    # git otherwise collapses a wholly untracked directory to one "docs/"
    # record and we would never see the files inside it.  Ignored files are
    # already absent; --ignored would bring them back, which is not wanted.
    status = subprocess.run(["git", "status", "--porcelain=v1", "-z", "-uall"],
                            cwd=str(base), capture_output=True)
    if status.returncode != 0:
        print("cleanchars: git status failed; nothing to do", file=sys.stderr)
        return None

    fields = os.fsdecode(status.stdout).split("\0")
    paths: list[Path] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4:            # "" after the final NUL, or a stray field
            continue
        code, name = record[:2], record[3:]
        if "R" in code or "C" in code:
            index += 1                 # under -z the origin path is a separate
                                       # field AFTER the destination; drop it
        if "D" in code:
            continue                   # the path is gone; nothing to read
        # The same boundaries a directory walk observes: git happily reports
        # an untracked node_modules/ that no .gitignore covers, and this mode
        # is the one that runs unattended.
        if any(part in SKIP_DIRECTORIES for part in Path(name).parts[:-1]):
            continue
        path = base / name
        if path.is_symlink() or not path.is_file():
            continue                   # symlinks, FIFOs, and dirty submodules,
        paths.append(path)             # which git reports as a directory
    return paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_keep(raw: str) -> set[str]:
    keep: set[str] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item[:2].lower() == "u+":
            item = item[2:]
        keep.add(chr(int(item, 16)))
    return keep


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanchars",
        description="Normalise troublesome Unicode in source and document files.")
    parser.add_argument("paths", nargs="*", type=Path,
                        help="files or directories; defaults to the current directory")
    parser.add_argument("--fix", action="store_true",
                        help="rewrite fixable characters in place")
    parser.add_argument("--diff", action="store_true",
                        help="print a unified diff and change nothing")
    parser.add_argument("--stdin", action="store_true",
                        help="filter stdin to stdout (always applies fixes)")
    parser.add_argument("--changed", action="store_true",
                        help="work on the files git reports as changed in this "
                             "repository instead of on positional paths")
    parser.add_argument("-o", "--output", type=Path, metavar="FILE",
                        help="write the cleaned result to FILE and leave the input "
                             "alone; requires exactly one input file")
    parser.add_argument("--profile", choices=("auto", "plain", "tex"), default="auto",
                        help="ASCII spelling to target; auto picks tex for .tex, "
                             ".sty, .cls, .bib and friends")
    parser.add_argument("--em-dash", default=None, metavar="STR",
                        help="replacement for U+2014 (default '-', or '---' under "
                             "the tex profile)")
    parser.add_argument("--nb-hyphen", choices=tuple(sorted(NB_HYPHEN_FORMS)),
                        default="plain",
                        help="tex only: how to write U+2011; plain (default) is '-' and "
                             "allows a line break, mbox and nobreakdash keep it "
                             "unbreakable (nobreakdash needs amsmath)")
    parser.add_argument("--semantic", choices=("replace", "error", "keep"),
                        default=None,
                        help="how to treat symbols whose replacement changes meaning "
                             "(x / != <= -> primes); default replace, error under tex")
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES, metavar="N",
                        help="fail on files larger than N bytes; 0 disables the limit")
    parser.add_argument("--keep", default="", metavar="HEX",
                        help="comma-separated codepoints to leave untouched, e.g. 2192,2264")
    parser.add_argument("--strict-ascii", action="store_true",
                        help="after replacement, reject every remaining non-ASCII character")
    parser.add_argument("--all-files", action="store_true",
                        help="ignore the extension allowlist (binary files are still skipped)")
    parser.add_argument("--no-context-guard", action="store_true",
                        help="also strip ZWJ/ZWNJ/variation selectors inside emoji and "
                             "non-Latin scripts")
    parser.add_argument("--nfc", action="store_true",
                        help="apply NFC normalisation (off by default)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="suppress per-character output; errors still print")
    parser.add_argument("--version", action="store_true",
                        help="print the version and exit")
    return parser


def resolve_version() -> str:
    """The installed distribution's version, or the constant above.

    A single file fetched with curl has no package metadata, so the constant
    is the only answer there.  Imported lazily: importlib.metadata costs more
    to import than the whole rest of a typical run.
    """
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("cleanchars")
    except PackageNotFoundError:
        return __version__


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.fix and args.diff:
        parser.error("--fix and --diff are mutually exclusive")

    if args.version:
        print("cleanchars %s" % resolve_version())
        return 0

    if args.output is not None and (args.fix or args.diff or args.stdin or args.changed):
        parser.error("--output cannot be combined with --fix, --diff, --stdin "
                     "or --changed")

    if args.changed and args.paths:
        parser.error("--changed takes its file list from git; "
                     "do not also pass paths")

    # argparse before 3.11 mishandles "--em-dash=--": the bare "--" is taken
    # for the end-of-options marker and the option is left holding [].  Only
    # this exact spelling is affected, and "--" is a value the tex profile
    # genuinely wants, so restore it rather than dropping Python 3.9 and 3.10.
    if args.em_dash == []:
        args.em_dash = "--"

    if args.em_dash is not None and any(ord(c) > 0x7F for c in args.em_dash):
        parser.error("--em-dash replacement must be ASCII")

    try:
        keep = parse_keep(args.keep)
    except ValueError:
        sys.stderr.write("bad --keep value: %s\n" % args.keep)
        return 2

    cache: dict[str, Policy] = {}

    def policy_for(path: Path | None) -> Policy:
        profile = (args.profile if args.profile != "auto" or path is None
                   else profile_for(path, "auto"))
        if profile == "auto":
            profile = "plain"
        if profile not in cache:
            cache[profile] = Policy(em_dash=args.em_dash, keep=keep,
                                    strict_ascii=args.strict_ascii,
                                    context_guard=not args.no_context_guard,
                                    nfc=args.nfc, semantic=args.semantic,
                                    profile=profile, nb_hyphen=args.nb_hyphen)
        return cache[profile]

    if args.stdin:
        # Bytes, not sys.stdin: the text stream would decode with whatever the
        # locale says (PYTHONIOENCODING=cp1252 silently turns UTF-8 accents
        # into mojibake) and would rewrite CRLF on the way in and out.  File
        # mode has always decoded UTF-8 strictly; stdin now matches it.
        policy = policy_for(None)
        raw = sys.stdin.buffer.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            sys.stdout.buffer.write(raw)    # pass through, do not mangle it
            print("<stdin>: ERROR: invalid UTF-8 at byte %d: %s"
                  % (exc.start, exc.reason), file=sys.stderr)
            return 1
        mojibake = find_mojibake(text)
        if mojibake:
            sys.stdout.buffer.write(raw)    # pass through, do not destroy evidence
            print("<stdin>: ERROR: mojibake, %s" % mojibake, file=sys.stderr)
            return 1
        cleaned, findings = scan(text, policy)
        sys.stdout.buffer.write(cleaned.encode("utf-8"))
        for finding in findings:
            if not finding.fixable:
                print(finding.render("<stdin>"), file=sys.stderr)
        return 1 if any(not f.fixable for f in findings) else 0

    paths = args.paths or [Path(".")]

    if args.output is not None:
        if len(paths) != 1 or not paths[0].is_file():
            parser.error("--output requires exactly one existing input file")
        # realpath collapses "./x" and follows symlinks, so an output that is
        # merely spelled differently cannot slip through and clobber the input
        # that this mode promises to leave alone.
        if os.path.realpath(str(args.output)) == os.path.realpath(str(paths[0])):
            parser.error("--output would overwrite the input file; "
                         "use --fix if that is what you meant")
        ok = process_file(paths[0], policy_for(paths[0]), fix=False, diff=False,
                          quiet=args.quiet, max_bytes=args.max_bytes,
                          output=args.output)
        return 0 if ok else 1

    errors: list[str] = []
    if args.changed:
        changed = git_changed_files()
        if changed is None:
            return 0                    # git could not answer; already explained
        # The allowlist and the profile apply exactly as they do to a walk.
        targets: Iterable[Path] = [p for p in changed
                                   if should_process(p, args.all_files)]
    else:
        targets = iter_files(paths, args.all_files, errors)

    ok = True
    for path in targets:
        if not process_file(path, policy_for(path), fix=args.fix, diff=args.diff,
                            quiet=args.quiet, max_bytes=args.max_bytes):
            ok = False
    # A mistyped path must not pass for "clean": in automation that is the
    # difference between checking a file and checking nothing at all.
    return 0 if ok and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
