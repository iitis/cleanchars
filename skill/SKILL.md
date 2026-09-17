---
name: cleanchars
description: Use cleanchars to remove unwanted Unicode typography or handle its diagnostics.
---

# cleanchars

Report mode is the default; `--fix` rewrites. Preview source changes: replacements
are text-based and can alter string literals or break syntax.

```bash
cleanchars --diff notes.md     # preview
cleanchars --fix notes.md      # rewrite in place
```

Exit codes: `0` clean, `1` findings remain, `2` usage error.

- **TeX errors:** choose maths commands and quotation forms from the source
  context. Do not use `--semantic=replace` merely to silence diagnostics.
- **Mojibake:** re-decode or recover the source before cleaning; the tool leaves
  affected files untouched. For U+FFFD/U+FFFC, recover missing content instead
  of guessing a replacement.
- **Remaining Unicode:** this is not a transliterator. `--strict-ascii` reports
  remaining non-ASCII characters for review; it does not convert them.

Use `cleanchars --help` for flags and the
[README](https://github.com/iitis/cleanchars#readme) for installation,
profiles, and policy details.
