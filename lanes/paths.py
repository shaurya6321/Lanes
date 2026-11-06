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
PROPOSAL_FILE = ".lanes/plan.proposed.yaml"  # written by /lanes-plan; plan owner only
PROPOSAL_DIR = ".lanes/proposal"  # draft contracts for the proposal; plan owner only

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


def is_proposal_path(rel: str) -> bool:
    """`.lanes/plan.proposed.yaml` or anything under `.lanes/proposal/` (case-insensitive, like the file systems)."""
    low = to_posix(rel).lower()
    return low == PROPOSAL_FILE or low == PROPOSAL_DIR or low.startswith(PROPOSAL_DIR + "/")


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


# ----------------------------------------------------------------------------
# Glob overlap: could some path match both patterns? Each pattern becomes a
# small NFA with the same semantics as `_compile`, and we search their product.
# ----------------------------------------------------------------------------

_ANY, _NONSLASH = "<any>", "<nonslash>"  # edge labels; literal labels are single chars


@lru_cache(maxsize=512)
def _nfa(pattern: str) -> tuple[tuple[tuple[tuple[str, int], ...], ...], tuple[tuple[int, ...], ...], frozenset[int]]:
    """(edges, epsilon moves, accepting states) per state; state 0 is the start."""
    pat = _clean_pattern(pattern)
    edges: list[list[tuple[str, int]]] = []
    eps: list[list[int]] = []

    def new() -> int:
        edges.append([])
        eps.append([])
        return len(edges) - 1

    s = new()
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):  # (?:.*/)?
            end, loop = new(), new()
            eps[s] += [end, loop]
            edges[loop] += [(_ANY, loop), ("/", end)]
            s, i = end, i + 3
            continue
        nxt = new()
        if pat.startswith("**", i):  # .*
            edges[s].append((_ANY, s))
            eps[s].append(nxt)
            i += 2
        elif pat[i] == "*":  # [^/]*
            edges[s].append((_NONSLASH, s))
            eps[s].append(nxt)
            i += 1
        else:
            edges[s].append((_NONSLASH if pat[i] == "?" else pat[i], nxt))
            i += 1
        s = nxt
    accept = {s}
    if not (_WILDCARDS & set(pat)):  # "src/api" also matches everything below it
        below = new()
        edges[s].append(("/", below))
        edges[below].append((_ANY, below))
        accept.add(below)
    return tuple(map(tuple, edges)), tuple(map(tuple, eps)), frozenset(accept)


def _closure(eps: tuple[tuple[int, ...], ...], state: int) -> set[int]:
    seen, stack = {state}, [state]
    while stack:
        for nxt in eps[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _labels_meet(a: str, b: str) -> bool:
    if a == _ANY or b == _ANY:
        return True
    if a == _NONSLASH or b == _NONSLASH:
        other = b if a == _NONSLASH else a
        return other != "/"
    return a == b


def globs_overlap(a: str, b: str) -> bool:
    """True if at least one path matches both glob patterns."""
    edges_a, eps_a, acc_a = _nfa(a)
    edges_b, eps_b, acc_b = _nfa(b)
    seen: set[tuple[int, int]] = {(0, 0)}
    stack = [(0, 0)]
    while stack:
        x, y = stack.pop()
        xs, ys = _closure(eps_a, x), _closure(eps_b, y)
        if xs & acc_a and ys & acc_b:
            return True
        for sx in xs:
            for la, tx in edges_a[sx]:
                for sy in ys:
                    for lb, ty in edges_b[sy]:
                        if (tx, ty) not in seen and _labels_meet(la, lb):
                            seen.add((tx, ty))
                            stack.append((tx, ty))
    return False
