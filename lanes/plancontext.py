"""`lanes plan context`: everything `/lanes-plan` needs, in one compact text.

PLAN.md, the current plan, existing contracts, the repo's files, and the import
graph between them (Python via `ast`, JS/TS via relative `import`/`require`),
with two hints derived from the graph:

- hub candidates: files imported from several top-level areas (give them one owner);
- clusters: groups of files connected by imports once hubs are set aside
  (keep each cluster in one task).

Standard library only, and bounded (file count, file size) so it stays fast.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath

from . import gitutil
from .paths import PLAN_FILE
from .proposal import CONTRACTS_DIR, DRAFT_CONTRACTS, PLAN_MD, PROPOSAL_FILE, _group, current_plan, plan_fingerprint

MAX_SOURCE_FILES = 3000
MAX_FILE_BYTES = 300_000
MAX_TREE_FILES = 400
MAX_EDGE_LINES = 250
PY = (".py",)
JS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_JS_IMPORT = re.compile(
    r"""(?:\bimport\s+(?:[\w*{}\s,]+\s+from\s+)?|\bexport\s+[\w*{}\s,]+\s+from\s+|\brequire\s*\(\s*|\bimport\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]"""
)


def _read(path: Path, limit: int = MAX_FILE_BYTES) -> str | None:
    try:
        if path.stat().st_size > limit:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---- import graph ---------------------------------------------------------------------------


def _py_modules(files: list[str]) -> dict[str, str]:
    """Dotted module name -> file, for the repo root and common source roots (src/, lib/, ...)."""
    roots = {""}
    for f in files:
        parts = PurePosixPath(f).parts
        if len(parts) > 2 and parts[-1] == "__init__.py":
            roots.add(parts[0] + "/")  # e.g. "src/" in a src layout
    mods: dict[str, str] = {}
    for f in files:
        if not f.endswith(".py"):
            continue
        for root in roots:
            if root and not f.startswith(root):
                continue
            rel = f[len(root):][:-3]
            name = rel.replace("/", ".")
            if name.endswith(".__init__"):
                name = name[: -len(".__init__")]
            mods.setdefault(name, f)
    return mods


def _py_edges(root: Path, f: str, mods: dict[str, str]) -> set[str]:
    text = _read(root / f)
    if text is None:
        return set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    pkg_parts = f[:-3].split("/")[:-1]  # the package a relative import starts from (same for __init__.py)
    out: set[str] = set()

    def resolve(name: str) -> None:
        parts = name.split(".")
        while parts:  # "a.b.c" -> try a.b.c, then a.b (c may be a symbol)
            dotted = ".".join(parts)
            # absolute, then a sibling module (scripts and tests import their neighbours: `from conftest import x`)
            hit = mods.get(dotted) or (mods.get(".".join(pkg_parts + parts)) if pkg_parts else None)
            if hit:
                out.add(hit)
                return
            parts.pop()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                resolve(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            for a in node.names:
                resolve(f"{prefix}.{a.name}" if prefix else a.name)
    out.discard(f)
    return out


def _js_edges(root: Path, f: str, fileset: set[str]) -> set[str]:
    text = _read(root / f)
    if text is None:
        return set()
    out: set[str] = set()
    base = PurePosixPath(f).parent
    for spec in _JS_IMPORT.findall(text):
        target = _norm(base / spec)
        candidates = [target] + [target + ext for ext in JS] + [f"{target}/index{ext}" for ext in JS]
        if target.endswith(".js"):  # TS projects import "./x.js" for "./x.ts"
            candidates += [target[:-3] + ".ts", target[:-3] + ".tsx"]
        hit = next((c for c in candidates if c in fileset), None)
        if hit and hit != f:
            out.add(hit)
    return out


def _norm(p: PurePosixPath) -> str:
    parts: list[str] = []
    for seg in p.parts:
        if seg == "..":
            if parts:
                parts.pop()
        elif seg != ".":
            parts.append(seg)
    return "/".join(parts)


def import_graph(root: Path, files: list[str]) -> dict[str, set[str]]:
    sources = [f for f in files if f.endswith(PY + JS)][:MAX_SOURCE_FILES]
    fileset = set(files)
    mods = _py_modules(sources)
    graph: dict[str, set[str]] = {}
    for f in sources:
        edges = _py_edges(root, f, mods) if f.endswith(PY) else _js_edges(root, f, fileset)
        if edges:
            graph[f] = edges
    return graph


_CONTAINERS = ("src", "lib", "app", "packages", "apps")


def _area(f: str) -> str:
    """A file's area: its first two directories, below a container like src/ ("src/shop/cart/x.py" -> "shop/cart")."""
    dirs = list(PurePosixPath(f).parts[:-1])
    if dirs and dirs[0] in _CONTAINERS:
        dirs = dirs[1:]
    return "/".join(dirs[:2]) or "(root)"


_TEST = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.py$|\.(test|spec)\.[jt]sx?$|(^|/)conftest\.py$")


def is_test(f: str) -> bool:
    return bool(_TEST.search(f))


HUB_FAN_IN = 8


def hub_candidates(graph: dict[str, set[str]]) -> list[tuple[str, int, int]]:
    """(file, importers, areas) for files imported from 2+ other areas or by HUB_FAN_IN+ files.

    Tests are left out: a test importing the module it tests is coupling, not sharing.
    """
    importers: dict[str, set[str]] = defaultdict(set)
    for src, targets in graph.items():
        if is_test(src):
            continue
        for t in targets:
            importers[t].add(src)
    hubs = []
    for f, who in importers.items():
        other = {_area(w) for w in who} - {_area(f)}
        if len(other) >= 2 or len(who) >= HUB_FAN_IN:
            hubs.append((f, len(who), len(other) + 1))
    return sorted(hubs, key=lambda h: (-h[2], -h[1], h[0]))


def clusters(graph: dict[str, set[str]], hubs: set[str]) -> list[list[str]]:
    """Connected components of the undirected import graph without hubs or tests (2+ files each)."""
    adj: dict[str, set[str]] = defaultdict(set)
    for a, targets in graph.items():
        for b in targets:
            if a in hubs or b in hubs or is_test(a) or is_test(b):
                continue
            adj[a].add(b)
            adj[b].add(a)
    seen: set[str] = set()
    comps: list[list[str]] = []
    for start in sorted(adj):
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if len(comp) > 1:
            comps.append(sorted(comp))
    return sorted(comps, key=lambda c: (-len(c), c[0]))


# ---- the report -----------------------------------------------------------------------------


def build_context(root: Path, member: str | None = None) -> str:
    plan = current_plan(root)
    files = [f for f in gitutil.tracked_files(root) if not f.startswith(".lanes/")]
    out: list[str] = ["# Lanes planning context", ""]
    out.append(f"based_on: {plan_fingerprint(root)}   (copy this into `proposal.based_on`)")
    if plan:
        out.append(f"plan owner: {plan.owner} · you: {member or 'unknown'}" + ("" if member == plan.owner else "   <- only the plan owner may write a proposal"))
    if (root / PROPOSAL_FILE).is_file():
        out.append(f"note: {PROPOSAL_FILE} already exists; a new proposal replaces it")
    out.append("")

    plan_md = _read(root / PLAN_MD)
    out.append(f"## {PLAN_MD}")
    out.append(re.sub(r"<!--.*?-->\n?", "", plan_md, flags=re.S).strip() if plan_md else "(missing: ask the team to write it first)")
    out.append("")

    out.append(f"## Current {PLAN_FILE}")
    current = _read(root / PLAN_FILE)
    out.append(current.strip() if current else "(none)")
    out.append("")

    out.append(f"## Existing contracts ({CONTRACTS_DIR}/): reuse these by id; never edit them")
    listed = {c.file: c for c in plan.contracts} if plan else {}
    found = False
    for f in sorted((root / CONTRACTS_DIR).glob("*.md")) if (root / CONTRACTS_DIR).is_dir() else []:
        if f.name.startswith("_"):
            continue
        rel = f"{CONTRACTS_DIR}/{f.name}"
        c = listed.get(rel)
        head = "\n".join(ln for ln in (_read(f, 50_000) or "").splitlines()[:25] if ln.strip())
        out.append(f"### {rel}" + (f" (id {c.id}, owner {c.owner})" if c else " (not in the plan)"))
        out.append(head)
        found = True
    if not found:
        out.append("(none)")
    drafts = root / DRAFT_CONTRACTS
    if drafts.is_dir() and any(drafts.iterdir()):
        out.append(f"(older drafts in {DRAFT_CONTRACTS}/: {', '.join(sorted(p.name for p in drafts.iterdir()))}; replace or delete them)")
    out.append("")

    out.append(f"## Files ({len(files)}, excluding .lanes/)")
    if len(files) <= MAX_TREE_FILES:
        out += [f"- {f}" for f in files]
    else:
        counts: dict[str, int] = defaultdict(int)
        for f in files:
            parts = PurePosixPath(f).parts
            counts["/".join(parts[:2]) + "/" if len(parts) > 2 else (parts[0] + "/" if len(parts) > 1 else f)] += 1
        out += [f"- {d} ({n})" if n > 1 else f"- {d}" for d, n in sorted(counts.items())]
    out.append("")

    graph = import_graph(root, files)
    hubs = hub_candidates(graph)
    out.append("## Import graph (repo files only; `a -> b` means a imports b)")
    lines = [f"{src} -> {', '.join(sorted(t))}" for src, t in sorted(graph.items())]
    out += lines[:MAX_EDGE_LINES] or ["(no imports between repo files found; only Python and JS/TS are analyzed)"]
    if len(lines) > MAX_EDGE_LINES:
        out.append(f"... and {len(lines) - MAX_EDGE_LINES} more files with imports")
    out.append("")
    out.append("## Hub candidates (imported from several areas: one owner, usually upstream)")
    out += [f"- {f} (imported by {n} files from {a} area{'s' if a > 1 else ''})" for f, n, a in hubs[:30]] or ["(none)"]
    out.append("")
    out.append("## Clusters (files coupled by imports, hubs and tests set aside: keep each in one task; tests go with the code they test)")
    comps = clusters(graph, {h[0] for h in hubs})
    out += [f"- {i}. {len(c)} files: {_group(c)}" for i, c in enumerate(comps[:30], 1)] or ["(none)"]
    out.append("")
    if plan:
        out.append("## Current ownership by area")
        owners: dict[str, set[str]] = defaultdict(set)
        for f in files:
            own = plan.owner_of(f)
            owners[_area(f)].add(f"{own.task.id} ({own.owner})" if own.kind == "task" and own.task else (f"hub ({own.owner})" if own.kind == "hub" else own.kind))
        out += [f"- {a}: {', '.join(sorted(o))}" for a, o in sorted(owners.items())]
    return "\n".join(out).rstrip() + "\n"
