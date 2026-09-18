# cleanchars
[![PyPI](https://img.shields.io/pypi/v/cleanchars)](https://pypi.org/project/cleanchars/)
[![CI](https://github.com/iitis/cleanchars/actions/workflows/ci.yml/badge.svg)](https://github.com/iitis/cleanchars/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/cleanchars)](https://pypi.org/project/cleanchars/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Clean unwanted typographic Unicode from LaTeX, Markdown, and source files**, replacing it with deterministic, file-type-aware ASCII equivalents: curly quotes, em dashes, non-breaking spaces, and invisible formatting marks introduced by rich-text editors and LLM tools.

- **Report first.** Files are unchanged unless `--fix` is used.
- **Deterministic.** Only explicit mappings are rewritten; ambiguous cases are reported.
- **File-type aware.** Plain text/code and TeX require different replacements.
- **Small and auditable.** One Python file, Python 3.9+, standard library only.

## Install

```bash
# try it, no install
uvx cleanchars --diff notes.md

# keep it
uv tool install cleanchars          # or: pipx install cleanchars

# into the current environment
pip install cleanchars

# no install, no package manager
curl -O https://raw.githubusercontent.com/iitis/cleanchars/v1.0.0/cleanchars.py
python3 cleanchars.py --diff notes.md
```
On PyPI: [pypi.org/project/cleanchars](https://pypi.org/project/cleanchars/)

## Use

```bash
cleanchars                          # report on the current directory
cleanchars --diff notes.md          # preview, change nothing
cleanchars --fix notes.md           # rewrite in place, atomically
cleanchars --fix src/ docs/         # recurse
cleanchars --changed --fix          # only what git says changed
cleanchars -o clean.md notes.md     # cleaned copy, input untouched
cat x | cleanchars --stdin          # filter mode
```

Reporting is the default: without `--fix` the input files are never
modified. The two commands that do produce output say so in their name --
`-o FILE` writes the cleaned copy to `FILE`, and `--stdin` writes the
cleaned text to stdout -- and neither touches the input.

Output is `path:line:col: U+XXXX NAME -> replacement`, which VS Code terminals make clickable.

Driving this from an AI coding agent instead of by hand? See
[Run it automatically](#run-it-automatically) below with ready-made hooks for Claude, Codex and CI.

## What it will not do

- **Transliterate.** Accents, CJK, Greek and emoji are left alone. This is a curated cleaner, not an ASCII converter; `--strict-ascii` reports what remains instead of transliterating it, so you decide. Some characters on the replacement table are emoji as well as symbols, and the table wins: see below.
- **Guess.** U+FFFD, U+FFFC and the invisible maths operators U+2061-U+2064 are errors, never substitutions.
- **Touch mojibake.** A file whose apostrophes arrived as the usual
  UTF-8-read-as-CP1252 garble is reported and left intact so you can re-decode it. Rewriting it would destroy the evidence.
- **Preserve every emoji.** Joiners and variation selectors are kept where the context guard allows; mapped symbols and Unicode tags are still changed.
- **Wander.** Directory walks and `--changed` skip `.git`, `node_modules`, `dist`, `build`, `.venv` and friends, follow an extension allowlist, and
  read regular files only: a symlink found while scanning is left alone, because it can point outside the tree you named. A file named explicitly on the command line is always processed, symlinks included.

Two deliberate exceptions to "emoji are left alone", both of them the point of the tool rather than oversights:

- `(C)`, `(R)` and `(TM)` replace U+00A9, U+00AE and U+2122 even when they carry an emoji variation selector (`tex` uses `\textcopyright{}`, `\textregistered{}` and `\texttrademark{}`). Other mapped symbols, including U+203C and U+2194, are replaced too.
- Unicode tag characters are always deleted, so the subdivision flags for Scotland, Wales and England lose their tags and come out as a plain black flag. The tag block can carry invisible payloads a reader never sees; stripping it is a deliberate part of the deletion policy, not an oversight.

## Profiles

The right ASCII spelling depends on the file type, and is chosen from the extension:

| | plain | tex |
|---|---|---|
| en dash | `-` | `--` |
| em dash | `-` | `---` |
| `'x'` `"y"` | `'x'` `"y"` | `` `x' `` ``` ``y'' ``` |
| no-break space | space | `~` |
| thin space | space | `\,` |
| ellipsis | `...` | `\ldots{}` |
| non-breaking hyphen | `-` | `-` |
| maths signs | replaced (`x`, `<=`, `->`) | reported as errors |

`tex` applies to `.tex .ltx .sty .cls .dtx .bib .tikz .pgf`. Override either way with `--profile=plain` or `--profile=tex`.

Maths symbols are errors under `tex` because the source does not say whether they sit in maths mode: a multiplication sign might want `\times` or `$\times$`. You get the line and column and decide.

### Hyphens and dashes

Four separate characters, four separate rules:

| char | what it is | plain | tex | why |
|---|---|---|---|---|
| U+2010 hyphen | a hyphen | `-` | `-` | ASCII `-` is this character |
| U+2011 non-breaking hyphen | a hyphen that forbids a break | `-` | `-` | ASCII has no way to say "don't break"; `\mbox{-}` is markup, not punctuation |
| U+2013 en dash | a range, e.g. 2019&ndash;2025 | `-` | `--` | TeX spells en dash as `--` |
| U+2014 em dash | a clause break, e.g. text&mdash;text | `-` | `---` | TeX spells em dash as `---` |

Hyphens stay hyphens. U+2010 and U+2011 both become `-`, in both profiles. The
non-breaking property is lost, deliberately: expressing it requires
`\mbox{-}` or `\nobreakdash-`, which is injected markup rather than a
character, and `\mbox` additionally blocks hyphenation of the surrounding
words. Use `--nb-hyphen=mbox` where it genuinely matters.

Dashes keep their length: this is the part that must not regress. In `tex`,
an en dash and an em dash are different characters and must stay different,
`--` and `---`. Flattening both to `-` would turn a date range into a hyphen
and a clause break into a hyphen too.

In `plain`, all four collapse to `-`. Markdown has no line-breaking marker to
preserve and no `--`/`---` convention, so there is nothing left to keep.

```bash
cleanchars --fix --nb-hyphen=mbox main.tex
```

That turns 2019&ndash;2025 into `2019--2025`, May&ndash;August into
`May--August`, an em-dash clause break into `--- clause ---`, and a
non-breaking hyphen into `\mbox{-}`. Drop the flag for anything that is not a
typeset document; `\mbox{-}` is not the default because it also blocks
hyphenation of the words around it.

## Flags worth knowing

| Flag | Use it when |
|---|---|
| `--changed` | you want the files git reports as changed, not a path list |
| `-o FILE` | you want a cleaned copy for testing, input left alone |
| `--profile=plain` | forcing plain spelling on a `.tex` file, or `tex` on something else |
| `--nb-hyphen=mbox` | under `tex`, keeping U+2011 unbreakable as `\mbox{-}` (or `nobreakdash`, needs `amsmath`) |
| `--semantic=error` | scientific code where `x` `<=` `->` `'` change meaning (already the default under `tex`) |
| `--keep=2192,2264` | a specific codepoint is deliberate |
| `--strict-ascii` | you want every remaining non-ASCII character reported |
| `--all-files` | ignoring the extension allowlist |
| `--nfc` | composing accents; off by default |
| `--max-bytes N` | raising or removing (`0`) the 5 MiB limit |

Exit codes: `0` clean, `1` findings remain, `2` usage error.

## Run it automatically

`--changed` is the agent-neutral way to do this. It asks git for the modified, added and untracked files in the current repository, applies the usual allowlist, and does nothing (exit 0) outside a repository or without git, so it is safe to wire into something that runs unattended.

**pre-commit.** Report mode, so a commit is never silently rewritten:

```yaml
repos:
  - repo: https://github.com/iitis/cleanchars
    rev: v1.0.0
    hooks:
      - id: cleanchars
```

Opt into rewriting with `args: [--fix]` if you would rather it fixed staged files than told you about them.

**CI.** Report mode is already a gate:

```yaml
- run: pipx run cleanchars .
```

**Your agent, optional, paste it yourself.** cleanchars does not write to anyone's configuration; these are snippets for you to add if you want them.

```jsonc
// ~/.claude/settings.json - clean every changed file in the repository
{ "hooks": { "Stop": [ { "hooks": [
  { "type": "command", "command": "cleanchars --changed --fix" } ] } ] } }
```

`--changed` cannot tell the agent's edits from yours: it fixes every file git
reports as changed, including your own uncommitted work. Findings it cannot
fix are printed but do not stop the agent, because the hook exits 1, not 2.

Codex takes the equivalent `Stop` entry in `~/.codex/hooks.json`. Codex
requires you to review and trust hooks before they run; until you do, nothing happens and it looks broken.

The optional [skill](skill/SKILL.md) gives agents compact usage and diagnostic guidance. To install it, copy `skill/` as `cleanchars/` into your agent's skill directory.

## Verify

```bash
python tests/verify.py
```

168 property checks covering the replacement tables, invisible-character handling, emoji, symlinks, atomic writes, git enumeration, stdin encoding, exit codes and every CLI flag. Two are POSIX-only, so Windows reports 166. No test framework, no dependencies.

## License

MIT, copyright the Institute of Theoretical and Applied Informatics, Polish Academy of Sciences (ITAI PAS). See [LICENSE](LICENSE).
