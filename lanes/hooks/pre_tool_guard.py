"""PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit): block edits outside my lane.

- In my lane, or anywhere in .lanes/ except other people's contracts: no output.
  We never return "allow", because that would skip the user's own permission prompts.
- Another member's file, a hub file or an unowned file: deny, with a reason telling
  Claude whom to ask and how (`lanes request`).
- Missing/invalid plan or unknown identity: allow and warn once per session (fail open).
"""

from __future__ import annotations

from ..lane import check_lane
from ..paths import repo_relative
from .adapters import HookInput, deny
from .common import load_ctx, run_hook, warn_once


def main() -> int:
    return run_hook(handle)


def handle(inp: HookInput) -> int:
    if not inp.paths:
        return 0
    ctx = load_ctx(inp)
    if ctx is None:
        return 0
    if ctx.plan is None:
        warn_once(ctx.root, inp.session_id, "plan", f"Lanes: .lanes/plan.yaml is invalid, so the lane guard is OFF: {ctx.plan_error}", inp.agent)
        return 0
    if ctx.member is None:
        warn_once(ctx.root, inp.session_id, "identity", f"Lanes: lane guard is OFF because you aren't a plan member. {ctx.identity_detail}", inp.agent)
        return 0

    for path in inp.paths:
        rel = repo_relative(path, ctx.root)
        if rel is None:  # outside this repo: not ours to judge
            continue
        decision = check_lane(ctx.plan, ctx.member, rel)
        if not decision.allowed:
            deny(decision.reason, agent=inp.agent)
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
