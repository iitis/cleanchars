#!/usr/bin/env python3
"""Verification harness for cleanchars.py.

Every test states a property and runs cleanchars.py (at the repository root,
one level above this file) as a subprocess with the current interpreter.

    python tests/verify.py      exit 0 when every check passes

No test framework, no dependencies: standard library only, like the tool.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "cleanchars.py")

C = chr
results = []


def run(script, args, cwd=None, stdin=None):
    """Run the tool with UTF-8 pinned on both sides of the pipe.

    text=True on its own encodes and decodes with the system locale, so a
    fixture containing U+2192 raises UnicodeEncodeError before cleanchars ever
    sees it, and the child would answer in a different encoding than the one
    we decode with.  Windows CI depends on this being pinned.
    """
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, script] + args, cwd=cwd,
                          input=stdin, capture_output=True, text=True,
                          encoding="utf-8", env=environment)
    return proc.returncode, proc.stdout, proc.stderr


def run_bytes(script, args, stdin=b"", env=None, timeout=None):
    """Like run(), but nothing decodes or translates newlines on the way."""
    environment = dict(os.environ)
    environment.update(env or {})
    proc = subprocess.run([sys.executable, script] + args, input=stdin,
                          capture_output=True, env=environment, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def read_raw(path):
    with open(path, "rb") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(text.encode("utf-8"))


def read(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def check(name, condition, note=""):
    results.append((name, bool(condition), note))


def tmp():
    return tempfile.mkdtemp(prefix="cleanchars_verify_")


def _force_remove_readonly(func, path, exc_info):
    """shutil.rmtree onerror hook: clear the read-only bit and retry.

    Git marks a committed loose object read-only (0444) on every platform.
    POSIX only checks the parent directory's permissions to unlink an entry,
    so this is silent there; Windows checks the file's own attributes too and
    refuses, which turned every --changed test directory into garbage that
    could never be cleaned up.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(path):
    shutil.rmtree(path, onerror=_force_remove_readonly)


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, capture_output=True, check=True)


def git_repo():
    """A throwaway repository with an identity, so commits work in CI."""
    d = tmp()
    git(["init", "-q", "."], d)
    git(["config", "user.email", "verify@example.invalid"], d)
    git(["config", "user.name", "cleanchars verify"], d)
    return d


if shutil.which("git") is None:
    sys.exit("verify.py needs git on PATH: the --changed checks require it")


# ---------------------------------------------------------------------------
print("running verification...\n")

# Windows refuses to unlink read-only files such as Git's loose objects.
# Exercise the cleanup wrapper before the Git-backed checks depend on it.
d = tmp()
p = os.path.join(d, "nested", "readonly")
write(p, "fixture\n")
os.chmod(p, stat.S_IREAD)
rmtree(d)
check("cleanup removes a tree containing a read-only file", not os.path.exists(d))

# 1. The tool and this harness are pure ASCII -> safe to run on themselves.
for label, path in (("cleanchars.py", SCRIPT), ("verify.py", os.path.abspath(__file__))):
    with open(path, "rb") as fh:
        check("%s source is pure ASCII" % label, all(b < 128 for b in fh.read()))

# 2. The tool is a no-op on its own source.
d = tmp()
shutil.copy(SCRIPT, os.path.join(d, "cleanchars.py"))
before = read(os.path.join(d, "cleanchars.py"))
run(SCRIPT, ["--fix", os.path.join(d, "cleanchars.py")])
check("cleanchars is a no-op on its own source",
      read(os.path.join(d, "cleanchars.py")) == before)
rmtree(d)

# ---------------------------------------------------------------------------
# Shared torture input
TORTURE = "\n".join([
    "quotes " + C(0x201C) + "hi" + C(0x201D) + " " + C(0x2018) + "x" + C(0x2019),
    "dash a" + C(0x2014) + "b ellipsis " + C(0x2026),
    "arrows " + C(0x2192) + " " + C(0x21D2) + " maths 3" + C(0x00D7) + "4 " + C(0x2264) + " 20",
    "bullet " + C(0x2022) + " tm " + C(0x2122),
    "nbsp[" + C(0x00A0) + "] zwsp[" + C(0x200B) + "] bom[" + C(0xFEFF) + "]",
    "linesep[" + C(0x2028) + "] parasep[" + C(0x2029) + "]",
    "invistimes 2" + C(0x2062) + "x tag[" + C(0xE0041) + "]",
    "bad[" + C(0xFFFD) + "] arabicmark[" + C(0x0605) + "]",
    "legit caf" + C(0x00E9) + " " + C(0x4E2D) + C(0x6587),
]) + "\n"


d = tmp()
p = os.path.join(d, "t.md")
write(p, TORTURE)
_, _, t_err = run(SCRIPT, ["--fix", p])
t_out = read(p)
rmtree(d)

# 3. Baseline typography
check("replaces smart quotes", '"hi"' in t_out and "'x'" in t_out)
check("replaces em dash and ellipsis", "a-b" in t_out and "ellipsis ..." in t_out)
check("replaces nbsp", C(0x00A0) not in t_out)
check("deletes zwsp and bom", C(0x200B) not in t_out and C(0xFEFF) not in t_out)

# 4. Arrows, maths signs, bullets, symbols
for label, cp in (("arrow U+2192", 0x2192),
                  ("multiplication U+00D7", 0x00D7),
                  ("less-or-equal U+2264", 0x2264),
                  ("bullet U+2022", 0x2022),
                  ("trade mark U+2122", 0x2122)):
    check("handles %s" % label, C(cp) not in t_out)

# 5. Separators and characters that must be reported, not guessed at
check("converts U+2028 to newline", C(0x2028) not in t_out)
check("converts U+2029 to newlines", C(0x2029) not in t_out)
check("errors on U+2062 rather than deleting it",
      "U+2062" in t_err and C(0x2062) in t_out)
check("errors on U+FFFD", "U+FFFD" in t_err)
check("catches an unlisted Cf character (U+0605)", "U+0605" in t_err)

# 6. Tag block
check("deletes the Unicode tag block", C(0xE0041) not in t_out)

# 7. Legitimate Unicode survives
check("preserves accented and CJK text",
      "caf" + C(0x00E9) in t_out and C(0x4E2D) + C(0x6587) in t_out)

# ---------------------------------------------------------------------------
# 8. CRLF preservation
d = tmp()
p = os.path.join(d, "crlf.md")
write(p, "a" + C(0x2014) + "b\r\nsecond\r\n")
run(SCRIPT, ["--fix", p])
check("preserves CRLF line endings", read(p) == "a-b\r\nsecond\r\n")
rmtree(d)

# 9. Line numbers refer to the original file, consistently
d = tmp()
p = os.path.join(d, "lines.md")
# U+2029 on line 1 expands to two newlines; the hard error is on original line 3
write(p, "para[" + C(0x2029) + "]\nfiller\nerr[" + C(0x2062) + "]\n")
_, _, err = run(SCRIPT, [p])
check("reports the hard error at original line 3",
      any(ln.startswith(p + ":3:") for ln in err.splitlines() if "U+2062" in ln),
      err.strip().splitlines()[-1] if err.strip() else "")
rmtree(d)

# ---------------------------------------------------------------------------
# 10. Directory walk respects the extension allowlist
d = tmp()
write(os.path.join(d, "proj", "notes.md"), "a" + C(0x2014) + "b\n")
write(os.path.join(d, "proj", "data", "m.csv"), "n,s\nw,3" + C(0x00D7) + "4\n")
write(os.path.join(d, "proj", "node_modules", "z.js"), "a" + C(0x2014) + "b\n")
run(SCRIPT, ["--fix", os.path.join(d, "proj")])
check("fixes .md in a directory walk",
      read(os.path.join(d, "proj", "notes.md")) == "a-b\n")
check("leaves .csv alone in a directory walk",
      C(0x00D7) in read(os.path.join(d, "proj", "data", "m.csv")))
check("skips node_modules",
      C(0x2014) in read(os.path.join(d, "proj", "node_modules", "z.js")))
rmtree(d)

# 11. An explicitly named file bypasses the allowlist
d = tmp()
p = os.path.join(d, "m.csv")
write(p, "n,s\nw,3" + C(0x00D7) + "4\n")
run(SCRIPT, ["--fix", p])
check("explicitly named file bypasses the allowlist", "3x4" in read(p))
rmtree(d)

# ---------------------------------------------------------------------------
# 12. --em-dash, --keep, --stdin
d = tmp()
p = os.path.join(d, "a.tex")
write(p, "a" + C(0x2014) + "b " + C(0x2192) + " c " + C(0x2264) + " d\n")
run(SCRIPT, ["--fix", "--profile=plain", "--em-dash=--", "--keep=2192", p])
res = read(p)
check("--em-dash produces the LaTeX ligature", "a--b" in res)
check("--keep preserves the requested codepoint", C(0x2192) in res)
check("--keep does not leak to other codepoints", C(0x2264) not in res)
rmtree(d)

rc, out, err = run(SCRIPT, ["--stdin"], stdin="q" + C(0x2019) + "z" + C(0x2192))
check("--stdin filters to stdout", out == "q'z->")

rc, out, err = run(SCRIPT, ["--stdin"], stdin="bad" + C(0xFFFD))
check("--stdin still reports hard errors on stderr", "U+FFFD" in err and rc == 1)

moji_in = "don" + C(0x00E2) + C(0x20AC) + C(0x2122) + "t"
rc, out, err = run(SCRIPT, ["--stdin"], stdin=moji_in)
check("--stdin passes mojibake through untouched and reports it",
      out == moji_in and rc == 1 and "mojibake" in err)

# 13. --diff changes nothing
d = tmp()
p = os.path.join(d, "n.md")
write(p, "a" + C(0x2014) + "b\n")
rc, out, err = run(SCRIPT, ["--diff", p])
check("--diff leaves the file untouched", read(p) == "a" + C(0x2014) + "b\n")
check("--diff prints a unified diff", "+a-b" in out and "-a" in out)
check("--diff exits 1 when there are findings", rc == 1)
rmtree(d)

# 14. --strict-ascii
d = tmp()
p = os.path.join(d, "s.md")
write(p, "caf" + C(0x00E9) + "\n")
rc, out, err = run(SCRIPT, [p])
check("legitimate non-ASCII passes by default", rc == 0)
rc, out, err = run(SCRIPT, ["--strict-ascii", p])
check("--strict-ascii rejects legitimate non-ASCII", rc == 1 and "U+00E9" in err)
rmtree(d)

# 15. Emoji and non-Latin joiners survive; ASCII-adjacent ones do not
d = tmp()
p = os.path.join(d, "e.md")
family = C(0x1F468) + C(0x200D) + C(0x1F469) + C(0x200D) + C(0x1F467)
warning = C(0x26A0) + C(0xFE0F)
stego = "he" + C(0x200B) + "ll" + C(0x200D) + "o"
write(p, family + " " + warning + " " + stego + "\n")
run(SCRIPT, ["--fix", p])
emoji = read(p)
check("keeps the emoji ZWJ family intact", family in emoji)
check("keeps the emoji variation selector", warning in emoji)
check("still strips zero-width chars inside ASCII words", "hello" in emoji)
rmtree(d)

# 16. NFC is opt-in
d = tmp()
p = os.path.join(d, "n.md")
decomposed = "cafe" + C(0x0301) + "\n"
write(p, decomposed)
run(SCRIPT, ["--fix", p])
check("NFC is off by default", read(p) == decomposed)
write(p, decomposed)
run(SCRIPT, ["--fix", "--nfc", p])
check("--nfc composes the text", read(p) == "caf" + C(0x00E9) + "\n")
rmtree(d)

# 17. Binary and oversized files are skipped
d = tmp()
p = os.path.join(d, "b.md")
with open(p, "wb") as fh:
    fh.write(b"a\x00b" + C(0x2014).encode("utf-8"))
rc, out, err = run(SCRIPT, ["--fix", p])
check("binary files are skipped", open(p, "rb").read().endswith(C(0x2014).encode("utf-8")))
rmtree(d)

# 18. Invalid UTF-8 is reported, not silently skipped
d = tmp()
p = os.path.join(d, "bad.md")
with open(p, "wb") as fh:
    fh.write(b"a\xffb\n")
rc, out, err = run(SCRIPT, [p])
check("invalid UTF-8 is reported and fails", rc == 1 and "invalid UTF-8" in err)
rmtree(d)

# 19. Exit codes
d = tmp()
p = os.path.join(d, "x.md")
write(p, "a" + C(0x2014) + "b\n")
rc_check, _, _ = run(SCRIPT, [p])
rc_fix, _, _ = run(SCRIPT, ["--fix", p])
rc_after, _, _ = run(SCRIPT, [p])
check("check mode exits 1 when dirty", rc_check == 1)
check("fix mode exits 0 when everything was fixable", rc_fix == 0)
check("re-checking a fixed file exits 0", rc_after == 0)
rmtree(d)

# 20. Full-width forms
d = tmp()
p = os.path.join(d, "f.md")
write(p, C(0xFF08) + "a" + C(0xFF09) + C(0xFF1A) + C(0xFF21) + "\n")
run(SCRIPT, ["--fix", p])
check("full-width forms map to ASCII", read(p) == "(a):A\n")
rmtree(d)

# 21. Report format is editor-parseable
d = tmp()
p = os.path.join(d, "r.md")
write(p, "ab" + C(0x2014) + "c\n")
rc, out, err = run(SCRIPT, [p])
check("report uses path:line:col with codepoint and name",
      "%s:1:3: U+2014 EM DASH -> '-'" % p in out, out.strip())
rmtree(d)

# 22. Supplementary variation selectors U+E0100-U+E01EF
d = tmp()
p = os.path.join(d, "svs.md")
write(p, "text" + C(0xE0101) + " end\n")
run(SCRIPT, ["--fix", p])
check("supplementary variation selector removed after ASCII", C(0xE0101) not in read(p))
write(p, C(0x4E2D) + C(0xE0101) + "\n")
run(SCRIPT, ["--fix", p])
check("supplementary variation selector kept after CJK", C(0xE0101) in read(p))
rmtree(d)

# 23. Mojibake is refused, not rewritten
d = tmp()
p = os.path.join(d, "moji.md")
mojibake = "don" + C(0x00E2) + C(0x20AC) + C(0x2122) + "t\n"
write(p, mojibake)
rc, out, err = run(SCRIPT, ["--fix", p])
check("mojibake is reported as an error", rc == 1 and "mojibake" in err)
check("mojibake file is left untouched for re-decoding", read(p) == mojibake)
rmtree(d)

# 24. --semantic profiles
d = tmp()
p = os.path.join(d, "m.md")
body = "f" + C(0x2032) + "(x) 3" + C(0x00D7) + "4 a" + C(0x2192) + "b " + C(0x2014) + "\n"
write(p, body)
rc, out, err = run(SCRIPT, ["--semantic=error", p])
check("--semantic=error rejects semantic symbols",
      rc == 1 and "U+00D7" in err and "U+2192" in err and "U+2032" in err)
check("--semantic=error still fixes the em dash", "U+2014 EM DASH -> '-'" in out)
run(SCRIPT, ["--fix", "--semantic=keep", p])
kept = read(p)
check("--semantic=keep leaves symbols alone but fixes typography",
      C(0x00D7) in kept and C(0x2192) in kept and C(0x2014) not in kept)
write(p, body)
run(SCRIPT, ["--fix", p])
check("default profile still replaces semantic symbols",
      C(0x00D7) not in read(p) and C(0x2192) not in read(p))
rmtree(d)

# 25. --max-bytes no longer passes silently
d = tmp()
p = os.path.join(d, "big.md")
write(p, ("x" * 200) + C(0x2014) + "\n")
rc, out, err = run(SCRIPT, ["--max-bytes", "50", p])
check("oversized file fails instead of silently passing",
      rc == 1 and "exceeds --max-bytes" in err)
rc, out, err = run(SCRIPT, ["--max-bytes", "0", p])
check("--max-bytes 0 disables the limit", rc == 1 and "U+2014" in out)
rmtree(d)

# 26. Atomic write: permissions preserved, no temp files left behind
d = tmp()
p = os.path.join(d, "perm.md")
write(p, "a" + C(0x2014) + "b\n")
os.chmod(p, 0o640)
inode_before = os.stat(p).st_mode
run(SCRIPT, ["--fix", p])
check("atomic write preserves file mode", os.stat(p).st_mode == inode_before)
check("atomic write leaves no temporary files",
      [n for n in os.listdir(d) if n.startswith(".cleanchars-")] == [])
check("atomic write produced the right content", read(p) == "a-b\n")
rmtree(d)

# 27. Reviewer regressions
d = tmp()
p = os.path.join(d, "guard.md")
write(p, "a" + C(0x2014) + C(0x200D) + "b\n")
run(SCRIPT, ["--fix", p])
check("ZWJ after an em dash is removed, not mistaken for script context",
      read(p) == "a-b\n")
write(p, C(0x0627) + C(0x200C) + C(0x0628) + "\n")
run(SCRIPT, ["--fix", p])
check("ZWNJ between Arabic letters is preserved", C(0x200C) in read(p))
write(p, C(0x3010) + C(0x200D) + "x\n")
run(SCRIPT, ["--fix", p])
check("ZWJ after CJK punctuation is removed", C(0x200D) not in read(p))
rmtree(d)

d = tmp()
p = os.path.join(d, "nfc.md")
write(p, "cafe" + C(0x0301) + "\n")
rc_check, out_check, _ = run(SCRIPT, ["--nfc", p])
rc_diff, out_diff, _ = run(SCRIPT, ["--nfc", "--diff", p])
check("--nfc check mode exits 1 when normalisation would change the file",
      rc_check == 1)
check("--nfc check mode explains the change", "normalisation" in out_check)
check("--nfc --diff exits 1 when it prints a diff", rc_diff == 1 and out_diff)
run(SCRIPT, ["--nfc", "--fix", p])
rc_after, _, _ = run(SCRIPT, ["--nfc", p])
check("--nfc re-check of a fixed file exits 0", rc_after == 0)
rmtree(d)

d = tmp()
target = os.path.join(d, "real.md")
link = os.path.join(d, "link.md")
write(target, "a" + C(0x2014) + "b\n")
os.symlink(target, link)
run(SCRIPT, ["--fix", link])
check("fixing through a symlink keeps the link", os.path.islink(link))
check("fixing through a symlink updates the target", read(target) == "a-b\n")
check("fixing through a symlink leaves no temp files",
      [n for n in os.listdir(d) if n.startswith(".cleanchars-")] == [])
rmtree(d)

d = tmp()
p = os.path.join(d, "em.md")
write(p, "a" + C(0x2014) + "b\n")
rc, out, err = run(SCRIPT, ["--em-dash=" + C(0x00E9), "--fix", p])
check("a non-ASCII --em-dash is rejected",
      rc == 2 and read(p) == "a" + C(0x2014) + "b\n")
rmtree(d)

# 28. LaTeX profile
d = tmp()
p = os.path.join(d, "paper.tex")
write(p, "2019" + C(0x2013) + "2025 " + C(0x2014) + " the " + C(0x2018) + "x" + C(0x2019)
      + " " + C(0x201C) + "y" + C(0x201D) + " Fig." + C(0x00A0) + "3" + C(0x2026)
      + " 5" + C(0x2009) + "km 3" + C(0x00D7) + "4 " + C(0x2212) + "7\n")
rc, out, err = run(SCRIPT, ["--fix", p])
res = read(p)
check("tex: en dash becomes --", "2019--2025" in res)
check("tex: em dash becomes ---", "--- the" in res)
check("tex: opening single quote becomes a backtick", "`x'" in res)
check("tex: double quotes become `` and ''", "``y''" in res)
check("tex: no-break space becomes a tilde", "Fig.~3" in res)
check("tex: ellipsis becomes \\ldots", "\\ldots{}" in res)
check("tex: thin space becomes \\,", "5\\,km" in res)
check("tex: maths symbols are reported, not replaced",
      C(0x00D7) in res and C(0x2212) in res)
check("tex: maths symbols raise errors", "U+00D7" in err and "U+2212" in err)
rmtree(d)

d = tmp()
p = os.path.join(d, "plain.md")
write(p, "2019" + C(0x2013) + "2025 " + C(0x2014) + " " + C(0x2018) + "x" + C(0x2019) + "\n")
run(SCRIPT, ["--fix", p])
check("markdown keeps the plain profile", read(p) == "2019-2025 - 'x'\n")
rmtree(d)

d = tmp()
p = os.path.join(d, "forced.tex")
write(p, "a" + C(0x2013) + "b\n")
run(SCRIPT, ["--fix", "--profile=plain", p])
check("--profile=plain overrides the extension", read(p) == "a-b\n")
write(p, "a" + C(0x2014) + "b\n")
run(SCRIPT, ["--fix", "--em-dash=--", p])
check("an explicit --em-dash still wins under tex", read(p) == "a--b\n", read(p))
rmtree(d)

# 29. --output writes elsewhere and leaves the source alone
d = tmp()
p = os.path.join(d, "in.tex")
original = "a" + C(0x2013) + "b " + C(0x201C) + "q" + C(0x201D) + "\n"
write(p, original)
out_path = os.path.join(d, "variants", "test.tex")
rc, out, err = run(SCRIPT, ["-o", out_path, p])
check("--output leaves the source untouched", read(p) == original)
check("--output writes the cleaned copy", read(out_path) == "a--b ``q''\n")
check("--output creates missing parent directories", os.path.isdir(os.path.dirname(out_path)))
check("--output exits 0 when it succeeded", rc == 0)
rc, out, err = run(SCRIPT, ["-o", out_path, "--fix", p])
check("--output rejects --fix", rc == 2)
rc, out, err = run(SCRIPT, ["-o", out_path, p, p])
check("--output rejects multiple inputs", rc == 2)
write(p, "bad" + C(0xFFFD) + "\n")
rc, out, err = run(SCRIPT, ["-o", out_path, p])
check("--output still exits 1 on hard errors", rc == 1)
rmtree(d)

# 30. Non-breaking hyphen under tex: plain "-" by default, unbreakable on request
d = tmp()
p = os.path.join(d, "nb.tex")
body = "Sentinel" + C(0x2011) + "2 U" + C(0x2011) + "Net a" + C(0x2010) + "b\n"
write(p, body)
run(SCRIPT, ["--fix", p])
check("tex: U+2011 becomes a plain hyphen by default",
      read(p) == "Sentinel-2 U-Net a-b\n")
write(p, body)
run(SCRIPT, ["--fix", "--nb-hyphen=nobreakdash", p])
check("--nb-hyphen=nobreakdash uses the amsmath form",
      read(p) == "Sentinel\\nobreakdash-2 U\\nobreakdash-Net a-b\n")
write(p, body)
run(SCRIPT, ["--fix", "--nb-hyphen=mbox", p])
check("--nb-hyphen=mbox keeps the hyphen unbreakable",
      read(p) == "Sentinel\\mbox{-}2 U\\mbox{-}Net a-b\n")
write(p, body)
run(SCRIPT, ["--fix", "--nb-hyphen=mbox", p])
first = read(p)
run(SCRIPT, ["--fix", "--nb-hyphen=mbox", p])
check("tex non-breaking hyphen output is idempotent", read(p) == first)
rmtree(d)

d = tmp()
p = os.path.join(d, "nb.md")
write(p, "Sentinel" + C(0x2011) + "2\n")
run(SCRIPT, ["--fix", p])
check("plain profile still flattens U+2011 to a hyphen", read(p) == "Sentinel-2\n")
rmtree(d)

# ---------------------------------------------------------------------------
# 31. --changed takes its file list from git.  The porcelain -z format is
#     parsed here against real git output rather than against its documentation.
EM = C(0x2014)

d = git_repo()
p = os.path.join(d, "notes.md")
write(p, "clean\n")
git(["add", "-A"], d)
git(["commit", "-qm", "base"], d)
write(p, "a" + EM + "b\n")
rc, out, err = run(SCRIPT, ["--changed"], cwd=d)
check("--changed reports a modified tracked file", rc == 1 and "U+2014" in out, out)
rc, out, err = run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed --fix rewrites a modified tracked file", read(p) == "a-b\n")
check("--changed --fix exits 0 when everything was fixable", rc == 0)
rmtree(d)

d = git_repo()
write(os.path.join(d, "fresh.md"), "a" + EM + "b\n")
rc, out, err = run(SCRIPT, ["--changed"], cwd=d)
check("--changed finds an untracked file", rc == 1 and "U+2014" in out, out)
rmtree(d)

d = git_repo()
write(os.path.join(d, ".gitignore"), "ignored.md\n")
write(os.path.join(d, "ignored.md"), "a" + EM + "b\n")
write(os.path.join(d, "seen.md"), "a" + EM + "b\n")
run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed skips a gitignored file",
      read(os.path.join(d, "ignored.md")) == "a" + EM + "b\n")
check("--changed fixes the file next to the ignored one",
      read(os.path.join(d, "seen.md")) == "a-b\n")
rmtree(d)

d = git_repo()
write(os.path.join(d, "gone.md"), "a" + EM + "b\n")
write(os.path.join(d, "kept.md"), "clean\n")
git(["add", "-A"], d)
git(["commit", "-qm", "base"], d)
git(["rm", "-q", "gone.md"], d)
write(os.path.join(d, "kept.md"), "a" + EM + "b\n")      # dirty alongside the deletion
rc, out, err = run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed ignores a deleted file instead of crashing",
      rc == 0 and "ERROR" not in err, err.strip())
check("--changed still fixed the surviving file",
      read(os.path.join(d, "kept.md")) == "a-b\n")
rmtree(d)

d = git_repo()
write(os.path.join(d, "old.md"), "a" + EM + "b\n")
git(["add", "-A"], d)
git(["commit", "-qm", "base"], d)
git(["mv", "old.md", "new.md"], d)
rc, out, err = run(SCRIPT, ["--changed"], cwd=d)
check("--changed reports the destination of a rename", "new.md" in out, out)
check("--changed drops the origin path of a rename",
      "old.md" not in out and "old.md" not in err, out + err)
rmtree(d)

d = git_repo()
p = os.path.join(d, "a file.md")
write(p, "a" + EM + "b\n")
run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed handles a path containing a space", read(p) == "a-b\n")
rmtree(d)

d = git_repo()
write(os.path.join(d, "table.csv"), "a" + EM + "b\n")
rc, out, err = run(SCRIPT, ["--changed"], cwd=d)
check("--changed applies the extension allowlist", rc == 0 and not out.strip(), out)
rc, out, err = run(SCRIPT, ["--changed", "--all-files"], cwd=d)
check("--changed --all-files widens the allowlist", rc == 1 and "U+2014" in out, out)
rmtree(d)

d = git_repo()
p = os.path.join(d, "docs", "deep.md")
write(p, "a" + EM + "b\n")
run(SCRIPT, ["--changed", "--fix"], cwd=os.path.join(d, "docs"))
check("--changed works from a subdirectory of the repository", read(p) == "a-b\n")
rmtree(d)

d = tmp()                                   # deliberately not a repository
p = os.path.join(d, "loose.md")
write(p, "a" + EM + "b\n")
rc, out, err = run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed outside a repository exits 0", rc == 0, err.strip())
check("--changed outside a repository says so on stderr", "git repository" in err, err.strip())
check("--changed outside a repository writes nothing", read(p) == "a" + EM + "b\n")
rmtree(d)

d = git_repo()
p = os.path.join(d, "x.md")
write(p, "a" + EM + "b\n")
rc, out, err = run(SCRIPT, ["--changed", "x.md"], cwd=d)
check("--changed plus a positional path is a usage error", rc == 2, err.strip())
check("--changed plus a positional path writes nothing", read(p) == "a" + EM + "b\n")
rmtree(d)

# ---------------------------------------------------------------------------
# 32. --version
declared = read(SCRIPT).split('__version__ = "')[1].split('"')[0]
rc, out, err = run(SCRIPT, ["--version"])
check("--version exits 0", rc == 0, err.strip())
check("--version prints the command name and the version",
      out.strip() == "cleanchars " + declared, out.strip())
check("--version scans nothing", not err.strip(), err.strip())

# ---------------------------------------------------------------------------
# 33. -o must never write over the file it promises to leave alone.
d = tmp()
p = os.path.join(d, "in.md")
original = "a" + C(0x2014) + "b\n"
os.symlink(p, os.path.join(d, "l.md"))
for label, alias in (("the same path", p),
                     ("a relative alias", os.path.join(d, ".", "in.md")),
                     ("a symlink alias", os.path.join(d, "l.md"))):
    write(p, original)
    rc, out, err = run(SCRIPT, ["-o", alias, p])
    check("-o rejects %s as its own input" % label, rc == 2, err.strip())
    check("-o leaves the input bytes alone for %s" % label, read(p) == original)
check("-o rejecting a symlink alias leaves the link intact",
      os.path.islink(os.path.join(d, "l.md")))
rmtree(d)

d = tmp()
p = os.path.join(d, "bin.md")
write_bytes(p, b"a\x00b")
rc, out, err = run(SCRIPT, ["-o", os.path.join(d, "copy.md"), p])
check("-o fails rather than silently skipping a binary input", rc == 1, err.strip())
check("-o writes no copy for a binary input",
      not os.path.exists(os.path.join(d, "copy.md")))
rmtree(d)

# ---------------------------------------------------------------------------
# 34. --stdin reads and writes UTF-8 bytes, whatever the locale says.
ACCENT = ("caf" + C(0x00E9) + "\r\n").encode("utf-8")
EMOJI = ("ok " + C(0x1F600) + "\n").encode("utf-8")
for label, env in (("with a UTF-8 locale", {"PYTHONIOENCODING": "utf-8"}),
                   ("with a cp1252 locale", {"PYTHONIOENCODING": "cp1252"})):
    rc, out, err = run_bytes(SCRIPT, ["--stdin"], stdin=ACCENT, env=env)
    check("--stdin round-trips accented UTF-8 %s" % label, out == ACCENT, repr(out))
    rc, out, err = run_bytes(SCRIPT, ["--stdin"], stdin=EMOJI, env=env)
    check("--stdin round-trips an emoji %s" % label, out == EMOJI, repr(out))

rc, out, err = run_bytes(SCRIPT, ["--stdin"], stdin=b"a\xffb\n")
check("--stdin rejects invalid UTF-8 as file mode does", rc == 1, err.decode())
check("--stdin passes invalid bytes through untouched", out == b"a\xffb\n", repr(out))

crlf = ("a" + C(0x2014) + "b\r\nsecond\r\n").encode("utf-8")
rc, out, err = run_bytes(SCRIPT, ["--stdin"], stdin=crlf)
check("--stdin preserves CRLF as file mode does", out == b"a-b\r\nsecond\r\n", repr(out))

# ---------------------------------------------------------------------------
# 35. An input that was never inspected is not a success.
d = tmp()
missing = os.path.join(d, "nope.md")
write(os.path.join(d, "clean.md"), "all ascii\n")
rc, out, err = run(SCRIPT, [missing])
check("a missing input fails instead of passing", rc == 1, err.strip())
rc, out, err = run(SCRIPT, [missing, os.path.join(d, "clean.md")])
check("a missing input fails even beside a clean file", rc == 1, err.strip())
rc, out, err = run(SCRIPT, [d])
check("a directory of clean files still passes", rc == 0, err.strip())
os.makedirs(os.path.join(d, "empty"))
rc, out, err = run(SCRIPT, [os.path.join(d, "empty")])
check("an empty directory passes", rc == 0, err.strip())
rmtree(d)

# ---------------------------------------------------------------------------
# 36. A walk reads regular files only.  A FIFO reports a size of zero, so
#     --max-bytes cannot save us; read_bytes() would block until killed.
if hasattr(os, "mkfifo"):
    d = tmp()
    os.mkfifo(os.path.join(d, "pipe.md"))
    write(os.path.join(d, "real.md"), "a" + C(0x2014) + "b\n")
    try:
        run_bytes(SCRIPT, ["--fix", d], timeout=20)
        finished = True
    except subprocess.TimeoutExpired:
        finished = False
    check("a directory scan containing a FIFO terminates", finished)
    check("a scan containing a FIFO still fixes the ordinary files",
          finished and read(os.path.join(d, "real.md")) == "a-b\n")
    os.unlink(os.path.join(d, "pipe.md"))
    rmtree(d)

# ---------------------------------------------------------------------------
# 37. Discovered symlinks are not followed; explicitly named ones still are.
d = tmp()
write(os.path.join(d, "outside.md"), "a" + C(0x2014) + "b\n")
os.makedirs(os.path.join(d, "scope"))
os.symlink(os.path.join(d, "outside.md"), os.path.join(d, "scope", "link.md"))
write(os.path.join(d, "scope", "normal.md"), "a" + C(0x2014) + "b\n")
run(SCRIPT, ["--fix", os.path.join(d, "scope")])
check("a walk does not follow a symlink out of the tree it was given",
      read(os.path.join(d, "outside.md")) == "a" + C(0x2014) + "b\n")
check("a walk still fixes the ordinary files beside it",
      read(os.path.join(d, "scope", "normal.md")) == "a-b\n")
run(SCRIPT, ["--fix", os.path.join(d, "scope", "link.md")])
check("an explicitly named symlink is still followed",
      read(os.path.join(d, "outside.md")) == "a-b\n")
rmtree(d)

# ---------------------------------------------------------------------------
# 38. --nfc: composition creates characters the policy must still judge.
d = tmp()
for name, body, expected in (("compose.md", "=" + C(0x0338) + "\n", "!=\n"),
                             ("greek.md", "x" + C(0x0387) + "y\n", "x-y\n")):
    p = os.path.join(d, name)
    write(p, body)
    run(SCRIPT, ["--nfc", "--fix", p])
    after = read(p)
    rc_again, _, _ = run(SCRIPT, ["--nfc", p])
    before_second = read_raw(p)
    run(SCRIPT, ["--nfc", "--fix", p])
    check("--nfc resolves %s in one pass" % name, after == expected, repr(after))
    check("--nfc leaves %s passing an immediate re-check" % name, rc_again == 0)
    check("--nfc fixing %s twice changes no bytes" % name,
          read_raw(p) == before_second)
p = os.path.join(d, "maths.tex")
write(p, "=" + C(0x0338) + "\n")
rc, out, err = run(SCRIPT, ["--nfc", "--fix", p])
check("--nfc reports the composed tex error on the first run",
      rc == 1 and "U+2260" in err, err.strip())
rmtree(d)

# ---------------------------------------------------------------------------
# 39. Every advertised tex extension is selected automatically.
TEX_SUFFIXES = (".tex", ".ltx", ".sty", ".cls", ".dtx", ".bib", ".tikz", ".pgf")
d = tmp()
for suffix in TEX_SUFFIXES:
    write(os.path.join(d, "doc" + suffix), "a" + C(0x2014) + "b\n")
run(SCRIPT, ["--fix", d])
missed = [x for x in TEX_SUFFIXES if read(os.path.join(d, "doc" + x)) != "a---b\n"]
check("a directory scan selects every tex extension", not missed, str(missed))
rmtree(d)

d = git_repo()
for suffix in TEX_SUFFIXES:
    write(os.path.join(d, "doc" + suffix), "a" + C(0x2014) + "b\n")
run(SCRIPT, ["--changed", "--fix"], cwd=d)
missed = [x for x in TEX_SUFFIXES if read(os.path.join(d, "doc" + x)) != "a---b\n"]
check("--changed selects every tex extension too", not missed, str(missed))
rmtree(d)

# ---------------------------------------------------------------------------
# 40. --changed observes the same skipped directories as a walk.
d = git_repo()
write(os.path.join(d, "node_modules", "dep.js"), "a" + C(0x2014) + "b\n")
write(os.path.join(d, "vendor", "lib.py"), "a" + C(0x2014) + "b\n")
write(os.path.join(d, "app.md"), "a" + C(0x2014) + "b\n")
run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed skips an untracked node_modules",
      read(os.path.join(d, "node_modules", "dep.js")) == "a" + C(0x2014) + "b\n")
check("--changed skips vendor",
      read(os.path.join(d, "vendor", "lib.py")) == "a" + C(0x2014) + "b\n")
check("--changed still fixes the file outside them",
      read(os.path.join(d, "app.md")) == "a-b\n")

git(["add", "-A", "-f"], d)                     # now tracked, still skipped
git(["commit", "-qm", "vendored"], d)
write(os.path.join(d, "node_modules", "dep.js"), "c" + C(0x2014) + "d\n")
run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed skips a tracked file in a skipped directory",
      read(os.path.join(d, "node_modules", "dep.js")) == "c" + C(0x2014) + "d\n")

write(os.path.join(d, "deep", "note.md"), "a" + C(0x2014) + "b\n")
run(SCRIPT, ["--changed", "--fix"], cwd=os.path.join(d, "deep"))
check("--changed from a subdirectory keeps the same boundaries",
      read(os.path.join(d, "deep", "note.md")) == "a-b\n"
      and read(os.path.join(d, "node_modules", "dep.js")) == "c" + C(0x2014) + "d\n")
rmtree(d)

d = git_repo()
write(os.path.join(d, "outside.md"), "a" + C(0x2014) + "b\n")
os.symlink(os.path.join(d, "outside.md"), os.path.join(d, "link.md"))
run(SCRIPT, ["--changed", "--fix"], cwd=d)
check("--changed does not follow a symlink it discovered",
      os.path.islink(os.path.join(d, "link.md")))
rmtree(d)

# ---------------------------------------------------------------------------
# 41. The README's emoji promise, pinned to what the tool actually does.
d = tmp()
p = os.path.join(d, "emoji.md")
flag = C(0x1F3F4) + "".join(C(cp) for cp in (0xE0067, 0xE0062, 0xE0073,
                                             0xE0063, 0xE0074, 0xE007F))
write(p, C(0x00A9) + C(0xFE0F) + " " + C(0x2122) + C(0xFE0F) + " " + flag
      + " " + C(0x1F600) + " " + C(0x26A0) + C(0xFE0F) + "\n")
run(SCRIPT, ["--fix", p])
after = read(p)
check("an emoji-presentation copyright sign still becomes (C)",
      "(C)" in after and C(0x00A9) not in after, after)
check("an emoji-presentation trade mark still becomes (TM)",
      "(TM)" in after and C(0x2122) not in after, after)
check("a subdivision flag loses its tag characters",
      C(0x1F3F4) in after and C(0xE0073) not in after, after)
check("an ordinary emoji is untouched", C(0x1F600) in after, after)
check("an emoji variation selector is untouched",
      C(0x26A0) + C(0xFE0F) in after, after)
rmtree(d)

# ---------------------------------------------------------------------------
# 42. --nfc reaches a fixed point when replacement feeds normalisation.
#     U+FF1D becomes "=", which then composes with U+0338 into U+2260.
d = tmp()
for name, expected_rc in (("compose.md", 0), ("compose.tex", 1)):
    p = os.path.join(d, name)
    write(p, C(0xFF1D) + C(0x0338) + "\n")
    rc_fix, _, _ = run(SCRIPT, ["--nfc", "--fix", p])
    rc_again, _, _ = run(SCRIPT, ["--nfc", p])
    check("--nfc --fix and its re-check agree on %s" % name,
          rc_fix == rc_again == expected_rc,
          "fix=%d recheck=%d" % (rc_fix, rc_again))
check("--nfc resolves a replaced-then-composed sequence in plain mode",
      read(os.path.join(d, "compose.md")) == "!=\n",
      read(os.path.join(d, "compose.md")))
check("--nfc reports the composed symbol under tex rather than hiding it",
      read(os.path.join(d, "compose.tex")) == C(0x2260) + "\n",
      read(os.path.join(d, "compose.tex")))
rmtree(d)

# ---------------------------------------------------------------------------
print("PROPERTY CHECKS")
print("-" * 72)
failed = 0
for name, passed, note in results:
    flag = "PASS" if passed else "FAIL"
    if not passed:
        failed += 1
    print("  [%s] %s%s" % (flag, name, ("   <- %s" % note) if (note and not passed) else ""))

print()
print("%d checks, %d failed" % (len(results), failed))
sys.exit(1 if failed else 0)
