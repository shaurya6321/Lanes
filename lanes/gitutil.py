"""Tiny git helpers. All return [] / None instead of raising when git is unavailable."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(root: Path | str | None, *args: str, timeout: float = 5) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root or None, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def toplevel(start: Path | str | None = None) -> Path | None:
    out = run_git(start, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else None


def branch(root: Path) -> str | None:
    out = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if out else None


def git_path(root: Path, name: str) -> Path | None:
    out = run_git(root, "rev-parse", "--git-path", name)
    if not out:
        return None
    p = Path(out.strip())
    return p if p.is_absolute() else root / p


def in_merge(root: Path) -> bool:
    p = git_path(root, "MERGE_HEAD")
    return bool(p and p.exists())


def dirty_paths(root: Path) -> list[str]:
    """Modified, staged, deleted and untracked paths (repo-relative, POSIX)."""
    out = run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if not out:
        return []
    entries = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:  # rename/copy: next field is the source path
            if i < len(entries) and entries[i]:
                paths.append(entries[i])
            i += 1
    return sorted(set(paths))


def staged_paths(root: Path) -> list[str]:
    """Every path a commit would touch, including both sides of a rename."""
    out = run_git(root, "diff", "--cached", "--name-status", "-z", "--diff-filter=ACDMRT")
    if not out:
        return []
    fields = [f for f in out.split("\0")]
    paths: list[str] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        if not status:
            i += 1
            continue
        if status[0] in "RC":
            paths += fields[i + 1 : i + 3]
            i += 3
        else:
            paths.append(fields[i + 1])
            i += 2
    return sorted(set(p for p in paths if p))


def changed_since_head(root: Path) -> list[str]:
    out = run_git(root, "diff", "--name-only", "HEAD")
    return sorted(set(out.split())) if out else []


def show_head(root: Path, rel: str) -> str | None:
    return run_git(root, "show", f"HEAD:{rel}")


def tracked_files(root: Path) -> list[str]:
    """Files git knows about: tracked plus untracked-but-not-ignored, as repo-relative POSIX paths."""
    out = run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", timeout=15)
    return sorted({p for p in out.split("\0") if p}) if out else []
