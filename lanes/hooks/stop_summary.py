"""Stop hook: keep a 3–5 line summary of this session in .lanes/summaries/.

Deterministic. The task and files come from the plan, from this session's
recorded edits, and from files that became dirty since session start (which
catches edits made through Bash). The "why" and "open" lines come from Claude's
final reply (`last_assistant_message`). Stop fires after every turn, so the
session's section is rewritten in place. This hook never blocks stopping.

To keep churn low (a dirty summary file is what makes `git pull --rebase`
refuse), a turn that made no edits since the last write leaves the summary
alone, and a rewrite that would only change the timestamp is skipped.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .. import gitutil
from ..plan import Plan
from ..summaries import derive_open, derive_why, has_section, render_section, upsert
from .adapters import HookInput
from .common import is_shared_lanes_state, load_ctx, load_state, run_hook, save_state


def main() -> int:
    return run_hook(handle)


def handle(inp: HookInput) -> int:
    if not inp.session_id:
        return 0
    ctx = load_ctx(inp)
    if ctx is None or ctx.plan is None or ctx.member is None:
        return 0

    files = files_touched(ctx.root, inp.session_id)
    if not files and not has_section(ctx.root, inp.session_id):
        return 0  # a pure Q&A turn with nothing to report
    state = load_state(ctx.root, inp.session_id)
    fingerprint = [state.get("edits", 0), sorted(files)] if state is not None else None
    if fingerprint is not None and state.get("summarized") == fingerprint and has_section(ctx.root, inp.session_id):
        return 0  # no edits since the last summary: keep the "why" from the turn that did the work
    now = datetime.now(timezone.utc).replace(microsecond=0)
    section = render_section(
        member=ctx.member,
        session_id=inp.session_id,
        task=pick_task(ctx.plan, ctx.member, files),
        why=derive_why(inp.last_message),
        files=files,
        open_q=derive_open(inp.last_message),
        now=now,
    )
    upsert(ctx.root, ctx.member, inp.session_id, section, now)
    if fingerprint is not None:
        state["summarized"] = fingerprint
        save_state(ctx.root, inp.session_id, state)
    return 0


def files_touched(root, session_id: str) -> list[str]:
    state = load_state(root, session_id)
    if state is None:
        # No SessionStart record (for example, hooks were installed mid-session): fall back to git.
        return [p for p in gitutil.changed_since_head(root) if not is_shared_lanes_state(p)]
    before = set(state.get("dirty_at_start", []))
    now_dirty = [p for p in gitutil.dirty_paths(root) if p not in before and not is_shared_lanes_state(p)]
    return list(dict.fromkeys([*state.get("touched", []), *now_dirty]))


def pick_task(plan: Plan, member: str, files: list[str]) -> str | None:
    votes = Counter()
    for rel in files:
        t = plan.task_for(rel)
        if t and t.owner == member:
            votes[t.id] += 1
    if votes:
        return votes.most_common(1)[0][0]
    mine = plan.tasks_of(member)
    active = [t for t in mine if t.status == "in_progress"] or [t for t in mine if t.status != "done"] or mine
    return active[0].id if active else None


if __name__ == "__main__":
    raise SystemExit(main())
