# Changelog

## 1.0.0 - unreleased

First packaged release. Previously circulated as a loose script called
`asciify`.

### Changed

- **Renamed to `cleanchars`.** The distribution, the command, the module and
  the repository all use the one name. `asciify.py` is now `cleanchars.py`,
  and `verify.py` moved to `tests/verify.py`.
- Packaged with a `pyproject.toml`: `uv tool install`, `pipx install` and a
  `cleanchars` entry point. The single-file `curl` route still works, because
  the module still has no dependencies.
- `--version` reports the installed distribution version, falling back to the
  module constant when there is no package metadata.
- A `.pre-commit-hooks.yaml` so the tool can be used from pre-commit in report
  mode.
- Requires Python 3.9 or newer. CI runs `python tests/verify.py` on Linux and
  Windows across 3.9 to 3.13, and separately builds the wheel, installs it and
  runs the command from outside the checkout.
- Moved to the `iitis` GitHub organization, at `github.com/iitis/cleanchars`.
- Licensed MIT, copyright the Institute of Theoretical and Applied Informatics,
  Polish Academy of Sciences (ITAI PAS); maintainer contact is now
  `mromaszewski@iitis.pl`.

### Added

- **`--changed`**: take the file list from `git status` (modified, added and
  untracked; not ignored, not deleted) instead of from positional paths. The
  usual extension allowlist and profile selection apply. Outside a git
  repository, or with no git on `PATH`, it explains itself on stderr and exits
  0, so it is safe in automation.

### Removed

- **`--hook`** and its agent event parsing. Hook configuration is the user's
  business: the README carries snippets to paste, and `--changed` is the
  agent-neutral replacement. Nothing in this tool writes to anyone's
  configuration.
- The POSIX wrapper script, which searched for a hard-coded personal conda
  environment and cost 1.1 s per invocation.

### Fixed

- `--em-dash=--` was silently lost on Python 3.9 and 3.10, where `argparse`
  mistakes the value for the end-of-options marker.
- `-o FILE` no longer overwrites its own input when the two paths are the same
  file by a different name, including through a symlink. It is now a usage
  error.
- `--stdin` decodes and encodes UTF-8 explicitly instead of trusting the
  locale, so `PYTHONIOENCODING=cp1252` can no longer turn accented text into
  mojibake, invalid UTF-8 fails as it does in file mode, and CRLF survives.
- A path that does not exist now fails instead of exiting 0, so a mistyped
  argument in automation cannot pass for a clean result. Directory traversal
  errors are reported the same way.
- Directory scans read regular files only. A FIFO in the tree used to block
  the process forever, and `--max-bytes` could not help because a FIFO reports
  a size of zero.
- Directory scans and `--changed` no longer follow symlinks they discovered,
  which could reach outside the tree that was named or into a skipped
  directory. An explicitly named symlink is still followed.
- `--nfc` now iterates normalisation and replacement to a fixed point.
  Composition creates characters the policy must judge (`=` plus U+0338 is
  U+2260) and replacement creates sequences that then compose (U+FF1D plus
  U+0338 becomes `=` plus U+0338). Doing either once meant `--fix` could
  report success on a file that failed the very next check.
- `.ltx`, `.dtx`, `.tikz` and `.pgf` are selected automatically. They were
  listed as tex-profile extensions but were missing from the allowlist, so a
  scan silently ignored them.
- `--changed` observes the same skipped directories as a walk, so an untracked
  `node_modules` is no longer rewritten by an unattended `--changed --fix`.
- `-o` reports a binary input as a failure instead of exiting 0 without
  writing the copy it promised.
- `--changed` uses `git status -uall`, so files inside a wholly untracked
  directory are seen individually rather than collapsed into one directory
  entry.
