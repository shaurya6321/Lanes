"""`lanes sync`: share .lanes/ (notices, summaries, handoffs, plan) with teammates through git.

1. If you're the plan owner and plan.yaml changed, make sure its plan notice exists.
2. Commit .lanes/ ONLY (`git commit -- .lanes`), so code you staged stays staged.
   The pre-commit lane check still runs on that commit.
3. `git pull --rebase --autostash`, so uncommitted work (including the session
   summary the Stop hook rewrites after every reply) never blocks the pull.
   On a conflict the rebase is aborted and your branch is left as it was.
4. Push, but only when every unpushed commit touches .lanes/ alone. If any
   unpushed commit has code in it, list them and stop unless --include-code.

Phase 0 assumes the whole team shares one branch (usually main); notices only
reach teammates who pull the same branch.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

LANES = ".lanes"
NET_TIMEOUT = 120


@dataclass
class SyncResult:
    code: int = 0
    lines: list[str] = field(default_factory=list)

    def say(self, text: str) -> None:
        self.lines.append(text)

    def fail(self, text: str) -> "SyncResult":
        self.lines.append(text)
        self.code = 1
        return self


def _git(root: Path, *args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(["git", *args], 1, "", str(exc))


def _out(root: Path, *args: str) -> str | None:
    p = _git(root, *args)
    return p.stdout.strip() if p.returncode == 0 else None


def _tail(p: subprocess.CompletedProcess, n: int = 6) -> str:
    text = (p.stderr or p.stdout or "").strip().splitlines()
    return "\n".join(f"    {ln}" for ln in text[-n:])


def _in_progress(root: Path) -> str | None:
    for name, what in (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase or am"), ("CHERRY_PICK_HEAD", "a cherry-pick")):
        path = _out(root, "rev-parse", "--git-path", name)
        if path and (root / path if not Path(path).is_absolute() else Path(path)).exists():
            return what
    return None


def unpushed(root: Path, upstream: str) -> list[tuple[str, str, list[str]]]:
    """(sha, subject, files) for each commit on HEAD that isn't on the upstream, oldest first."""
    out = _out(root, "rev-list", "--reverse", f"{upstream}..HEAD")
    commits = []
    for sha in (out or "").split():
        subject = _out(root, "log", "-1", "--format=%s", sha) or ""
        files = (_out(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--root", sha) or "").splitlines()
        commits.append((sha, subject, sorted(set(f for f in files if f))))
    return commits


def is_lanes_only(files: list[str]) -> bool:
    return bool(files) and all(f == LANES or f.startswith(LANES + "/") for f in files)


def sync(root: Path, plan, member: str, include_code: bool = False) -> SyncResult:
    r = SyncResult()
    branch = _out(root, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:
        return r.fail("lanes sync: HEAD is detached. Check out your branch first.")
    busy = _in_progress(root)
    if busy:
        return r.fail(f"lanes sync: {busy} is in progress. Finish or abort it first.")

    # 1. plan notice for hand edits made outside Claude
    plan_dirty = _out(root, "status", "--porcelain", "--", f"{LANES}/plan.yaml")
    if plan_dirty and member == plan.owner:
        from .plandiff import record_plan_change

        notice, created = record_plan_change(root, plan, member)
        if notice and created:
            r.say(f"Wrote plan notice {notice.id} for {', '.join(notice.to_members)}.")

    # 2. commit .lanes/ only
    _git(root, "add", "-A", "--", LANES)
    staged = _out(root, "diff", "--cached", "--name-only", "--", LANES)
    if staged:
        p = _git(root, "commit", "-q", "-m", f"lanes: sync {member}", "--", LANES, timeout=60)
        if p.returncode != 0:
            return r.fail("Commit of .lanes/ failed (the lane check may have blocked it):\n" + _tail(p, 20))
        r.say(f"Committed {len(staged.splitlines())} .lanes/ file(s).")
    else:
        r.say("No .lanes/ changes to commit.")

    upstream = _out(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not upstream:
        return r.fail(
            f"Branch {branch} has no upstream, so nothing was pulled or pushed. "
            f"Push it once with `git push -u origin {branch}`, then use `lanes sync`."
        )
    remote = upstream.split("/", 1)[0]
    default = _out(root, "symbolic-ref", "--short", "-q", f"refs/remotes/{remote}/HEAD")
    if default and default != upstream:
        r.say(
            f"Warning: you're syncing {upstream}, but the team branch is {default}. In Phase 0, notices only "
            "reach teammates on the same branch."
        )

    # 3. pull, rebasing local commits; uncommitted work is stashed and restored
    p = _git(root, "pull", "--rebase", "--autostash", "--quiet", timeout=NET_TIMEOUT)
    if p.returncode != 0:
        conflicts = (_out(root, "diff", "--name-only", "--diff-filter=U") or "").splitlines()
        if _in_progress(root):
            _git(root, "rebase", "--abort")
        if conflicts:
            return r.fail(
                "Pull stopped on a conflict, so it was undone and your branch is as it was. Conflicting files:\n"
                + "\n".join(f"    {c}" for c in conflicts)
                + f"\n  Resolve with `git pull --rebase --autostash` and fix those files, or ask whoever changed them, then run `lanes sync` again."
            )
        return r.fail("git pull failed:\n" + _tail(p))
    r.say(f"Pulled {upstream}.")

    # 4. push only .lanes/-only commits unless told otherwise
    pending = unpushed(root, upstream)
    if not pending:
        r.say("Nothing to push. Up to date.")
        return r
    code = [c for c in pending if not is_lanes_only(c[2])]
    if code and not include_code:
        r.say(f"Not pushed: {len(code)} of {len(pending)} unpushed commit(s) contain code:")
        for sha, subject, files in code:
            r.say(f"    {sha[:8]} {subject} ({len(files)} file(s))")
        r.say("  Run `lanes sync --include-code` to push them along with .lanes/, or `git push` yourself.")
        r.code = 3
        return r
    p = _git(root, "push", "--quiet", timeout=NET_TIMEOUT)
    if p.returncode != 0:
        return r.fail("git push failed (if someone pushed meanwhile, run `lanes sync` again):\n" + _tail(p))
    kinds = "including code" if code else ".lanes/ only"
    r.say(f"Pushed {len(pending)} commit(s) to {upstream} ({kinds}).")
    return r
