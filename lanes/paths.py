"""Path and glob helpers.

Everything Lanes compares is a repo-relative POSIX path ("src/api/cart/x.py"),
so the same plan works on macOS and Windows. Windows paths such as
"C:\\repo\\src\\api\\cart\\x.py" are normalized before matching.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

LANES_DIR = ".lanes"
PLAN_FILE = ".lanes/plan.yaml"

_DRIVE = re.compile(r"^[A-Za-z]:/")
_WILDCARDS = set("*?")


def to_posix(path: str | os.PathLike) -> str:
    """Normalize separators, '.', '..' and duplicate slashes, lexically."""
    p = str(path).replace("\\", "/")
    prefix = ""
    if _DRIVE.match(p):
        prefix, p = p[0].upper() + ":", p[2:]
    leading = p.startswith("/")
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            elif not leading:
                parts.append("..")
            continue
        parts.append(seg)
    return prefix + ("/" if leading else "") + "/".join(parts)


def is_absolute(path: str) -> bool:
    p = str(path).replace("\\", "/")
    return p.startswith("/") or bool(_DRIVE.match(p))


def repo_relative(path: str | os.PathLike, root: str | os.PathLike) -> str | None:
    """Return `path` relative to `root` as a POSIX string, or None if outside it."""
    p = to_posix(path)
    if not is_absolute(p):
        return None if p == ".." or p.startswith("../") else p
    rel = _strip_root(p, to_posix(root))
    if rel is not None:
        return rel
    # macOS: /tmp is a symlink to /private/tmp, so compare resolved paths too.
    if os.path.isabs(str(path)) and os.path.isabs(str(root)):
        return _strip_root(to_posix(os.path.realpath(path)), to_posix(os.path.realpath(root)))
    return None


def _strip_root(p: str, r: str) -> str | None:
    windows = bool(_DRIVE.match(r))
    cp, cr = (p.lower(), r.lower()) if windows else (p, r)
    cr = cr.rstrip("/")
    if cp == cr:
        return ""
    if cp.startswith(cr + "/"):
        return p[len(cr) + 1 :]
    return None


def find_root(start: str | os.PathLike | None = None) -> Path | None:
    """Walk up from `start` to the first directory that contains `.lanes/`."""
    here = Path(start or os.getcwd()).absolute()
    for d in (here, *here.parents):
        if (d / LANES_DIR).is_dir():
            return d
    return None


# ----------------------------------------------------------------------------
# Globs: `*` stays inside one directory, `**` crosses directories.
# A pattern with no wildcards also matches everything below it ("src/api").
# ----------------------------------------------------------------------------


def _clean_pattern(pattern: str) -> str:
    pat = to_posix(pattern).lstrip("/")
    if str(pattern).replace("\\", "/").endswith("/"):
        pat += "/**"
    return pat


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    pat = _clean_pattern(pattern)
    out: list[str] = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(pattern: str, rel_path: str) -> bool:
    rel = to_posix(rel_path)
    if _compile(pattern).match(rel):
        return True
    pat = _clean_pattern(pattern)
    return not (_WILDCARDS & set(pat)) and rel.startswith(pat.rstrip("/") + "/")


def specificity(pattern: str) -> tuple[int, int]:
    """Higher is more specific: (literal prefix length, total literal chars)."""
    pat = _clean_pattern(pattern)
    prefix = 0
    for ch in pat:
        if ch in _WILDCARDS:
            break
        prefix += 1
    return prefix, sum(1 for ch in pat if ch not in _WILDCARDS)
