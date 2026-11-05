"""git pre-commit hook: block commits that stage files outside the committer's lane.

Agent-neutral safety net. It catches anything the PreToolUse guard can't see:
Bash edits, Codex file patches, and edits made by hand. It uses the same lane
rule and message as the guard. It fails open on a missing/invalid plan or an
unknown identity, and it skips merge commits, whose staged changes include
teammates' work.
"""

from __future__ import annotations

import sys

from .. import gitutil
from ..identity import resolve
from ..lane import check_commit_path
from ..plan import PlanError, load_plan


def main() -> int:
    root = gitutil.toplevel()
    if root is None or not (root / ".lanes").is_dir():
        return 0
    if gitutil.in_merge(root):
        print("lanes: merge commit, so the lane check was skipped.", file=sys.stderr)
        return 0
    try:
        plan = load_plan(root)
    except PlanError as exc:
        print(f"lanes: WARNING: plan.yaml is invalid, so the lane check was skipped: {'; '.join(exc.errors)}", file=sys.stderr)
        return 0
    ident = resolve(plan, root)
    if ident.member_id is None:
        print(f"lanes: WARNING: lane check skipped. {ident.detail}", file=sys.stderr)
        return 0

    blocked = [(rel, d) for rel in gitutil.staged_paths(root) if not (d := check_commit_path(root, plan, ident.member_id, rel)).allowed]
    if not blocked:
        return 0
    print(f"Lanes: this commit touches {len(blocked)} file(s) outside your lane ({ident.member_id}):\n", file=sys.stderr)
    for rel, d in blocked:
        print(f"  {rel}\n    " + d.reason.replace("\n", "\n    ") + "\n", file=sys.stderr)
    print(
        "Unstage them with `git restore --staged <path>`, or ask the owner.\n"
        "To bypass once (for example, when the owner has agreed): git commit --no-verify",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
