"""PostToolUse hook (Edit|Write|MultiEdit|NotebookEdit): record touched files; notify downstream.

1. Every edited path goes into this session's local state, which the Stop summary uses.
2. If the file is a contract or hub file that I own, write (or extend) a change notice
   addressed ONLY to higher-rank tasks, and ask Claude to refine its summary line.
"""

from __future__ import annotations

from .. import gitutil
from ..notices import describe_change, record_change
from ..paths import repo_relative
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
                "Now edit that file. Replace the auto-generated `summary:` line with one precise sentence wrapped in "
                "double quotes (it is YAML), and make the "
                "body 3–6 lines naming exactly what changed (renamed symbols, added or removed args, changed types). "
                "Keep it under ~150 tokens with no secrets. The notice is for your teammates: don't mark it read yourself. "
                "They see it after you commit and push."
            )
        else:
            messages.append(f"Lanes: notice {where} was updated with this edit (to {recipients}). Make sure its summary still matches.")
    if messages:
        add_context("PostToolUse", "\n".join(messages), agent=inp.agent)
    return 0


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
