"""PostToolUse hook (Edit|Write|MultiEdit|NotebookEdit): record touched files; notify downstream.

1. Every edited path goes into this session's local state, which the Stop summary uses.
2. If the file is a contract or hub file that I own, write (or extend) a change notice
   addressed ONLY to higher-rank tasks, and ask Claude to refine its summary line.
3. If the file is .lanes/plan.yaml and I'm the plan owner, write (or update) a plan
   notice for every task whose ownership changed (see lanes/plandiff.py).
"""

from __future__ import annotations

from .. import gitutil
from ..notices import describe_change, record_change
from ..paths import PLAN_FILE, repo_relative
from ..plandiff import ownership_changed, record_plan_change
from ..redact import is_env_file
from .adapters import HookInput, add_context
from .common import is_shared_lanes_state, load_ctx, load_state, run_hook, save_state


def main() -> int:
    return run_hook(handle)


def handle(inp: HookInput) -> int:
    if not inp.paths:
        return 0
    ctx = load_ctx(inp)
    if ctx is None or ctx.plan is None:
        return 0

    rels = [r for r in (repo_relative(p, ctx.root) for p in inp.paths) if r is not None]
    _record_touched(ctx.root, inp.session_id, rels)
    if ctx.member is None:
        return 0

    messages: list[str] = []
    for rel in rels:
        if is_env_file(rel):
            continue
        if rel.lower() == PLAN_FILE:
            messages += _plan_messages(ctx, inp.session_id)
            continue
        own = ctx.plan.owner_of(rel)
        if own.kind not in ("contract", "hub") or own.owner != ctx.member:
            continue
        notice, created = record_change(ctx.root, ctx.plan, ctx.member, rel, own, change_lines(inp, ctx.root, rel), session=inp.session_id)
        if notice is None:
            continue
        where = notice.path.relative_to(ctx.root).as_posix()
        recipients = ", ".join(f"{t} ({ctx.plan.task(t).owner})" for t in notice.to_tasks if ctx.plan.task(t))
        if created:
            messages.append(
                f"Lanes: you changed {notice.topic}, so a change notice for {recipients} was written to {where}. "
                "Now replace its auto-generated summary (don't edit the file; Lanes blocks that). Run:\n"
                f'  lanes notices amend {notice.id} --summary "<one precise sentence>" --body "<line 1>\\n<line 2>..."\n'
                "The body is 3–6 lines naming exactly what changed (renamed symbols, added or removed args, changed types), "
                "under ~150 tokens, no secrets. The notice is for your teammates: don't mark it read yourself. "
                "They see it after you commit and push."
            )
        else:
            messages.append(
                f"Lanes: notice {where} was updated with this edit (to {recipients}). If its summary no longer matches, "
                f'run `lanes notices amend {notice.id} --summary "..."`.'
            )
    if messages:
        add_context("PostToolUse", "\n".join(messages), agent=inp.agent)
    return 0


def _plan_messages(ctx, session_id: str | None) -> list[str]:
    plan, member = ctx.plan, ctx.member
    if member != plan.owner:
        if ownership_changed(ctx.root, plan, member):
            return [
                f"Lanes: you changed other people's tasks in {PLAN_FILE}, but only the plan owner ({plan.owner}) "
                "sends plan notices, so nobody was told. Undo it unless your human and the plan owner agreed."
            ]
        return []
    notice, created = record_plan_change(ctx.root, plan, member, session=session_id)
    if notice is None:
        return []
    where = notice.path.relative_to(ctx.root).as_posix()
    who = ", ".join(notice.to_members)
    verb = "written to" if created else "updated in"
    return [
        f"Lanes: you changed task ownership in the plan, so a plan notice for {who} was {verb} {where}. "
        f"It lists every change since the last commit and goes out when you commit and push. "
        f'To replace its auto-generated summary, run `lanes notices amend {notice.id} --summary "..."`.'
    ]


def change_lines(inp: HookInput, root, rel: str) -> list[str]:
    ti = inp.tool_input
    if inp.tool_name == "Edit":
        return describe_change(str(ti.get("old_string", "")), str(ti.get("new_string", "")))
    if inp.tool_name == "MultiEdit":
        lines: list[str] = []
        for e in ti.get("edits") or []:
            if isinstance(e, dict):
                lines += describe_change(str(e.get("old_string", "")), str(e.get("new_string", "")))
        return lines[:6]
    if inp.tool_name == "Write":
        before = gitutil.show_head(root, rel) or ""
        return describe_change(before, str(ti.get("content", ""))) or [f"~ rewrote {rel} (no line changes vs HEAD)"]
    if inp.tool_name == "NotebookEdit":
        return [f"~ notebook cell {ti.get('cell_id', '?')} ({ti.get('edit_mode', 'replace')})"]
    return []


def _record_touched(root, session_id: str | None, rels: list[str]) -> None:
    keep = [r for r in rels if not is_shared_lanes_state(r)]
    if not session_id or not keep:
        return
    state = load_state(root, session_id) or {"touched": []}
    touched = list(dict.fromkeys([*state.get("touched", []), *keep]))
    state["touched"] = touched
    save_state(root, session_id, state)


if __name__ == "__main__":
    raise SystemExit(main())
