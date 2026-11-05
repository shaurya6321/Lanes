"""The lane rule, shared by the PreToolUse guard, `lanes check` and the pre-commit hook."""

from __future__ import annotations

from dataclasses import dataclass

from .plan import Ownership, Plan
from .runner import lanes_cmd


@dataclass(frozen=True)
class LaneDecision:
    allowed: bool
    ownership: Ownership
    reason: str  # always set; explains allow or deny


def check_lane(plan: Plan, member_id: str, rel_path: str) -> LaneDecision:
    own = plan.owner_of(rel_path)
    L = lanes_cmd(plan.root)
    mine = ", ".join(t.id for t in plan.tasks_of(member_id)) or "no tasks"

    if own.kind == "lanes":
        return LaneDecision(True, own, f"{rel_path} is Lanes coordination state (.lanes/), which anyone may write")
    if own.owner == member_id:
        return LaneDecision(True, own, f"{rel_path} is in your lane ({_describe(own)})")

    if own.kind == "plan":
        reason = (
            f"Lanes lane guard: `{rel_path}` belongs to the plan owner, {own.owner}. Only they edit it. "
            f"To change the status of one of your own tasks, run:\n"
            f"  {L} task status <TASK> <todo|in_progress|blocked|review|done>\n"
            f"For anything else (owned files, contracts, new tasks), ask the plan owner:\n"
            f'  {L} request --file "{rel_path}" "<what you need changed and why>"'
        )
    elif own.kind == "unowned":
        reason = (
            f"Lanes lane guard: no task in .lanes/plan.yaml owns `{rel_path}`, so it is outside your lane "
            f"({member_id}: {mine}). Do not edit it yet. Ask your human whether it should be added to one of "
            f"your tasks' `owns` globs in .lanes/plan.yaml (do not change the plan without their OK), "
            f"then continue with work inside your lane."
        )
    else:
        reason = (
            f"Lanes lane guard: `{rel_path}` belongs to {own.owner} ({_describe(own)}). It is outside your lane "
            f"({member_id}: {mine}). Do not edit it. Instead ask the owner by running:\n"
            f'  {L} request --file "{rel_path}" "<what you need changed and why>"\n'
            f"then continue with the parts of your task you can do inside your lane."
        )
    return LaneDecision(False, own, reason)


NOTICES_PREFIX = ".lanes/notices/"


def is_notice_path(rel_path: str) -> bool:
    # lower(): macOS and Windows file systems are case-insensitive by default
    return rel_path.lower().startswith(NOTICES_PREFIX)


def check_edit(plan: Plan, member_id: str, rel_path: str) -> LaneDecision:
    """The lane rule for an agent's Edit/Write tools: `check_lane` plus "notices are Lanes-only".

    Notices and read-by files may be committed by anyone (so `check_lane`, used by the
    commit check, allows them), but only Lanes itself writes them, so a teammate's
    notice can't be rewritten, deleted or marked read behind their back.
    """
    if is_notice_path(rel_path):
        L = lanes_cmd(plan.root)
        return LaneDecision(
            False,
            plan.owner_of(rel_path),
            f"Lanes: `{rel_path}` is written only by Lanes, never edited directly. Use instead:\n"
            f'  {L} request --file <path> "<what and why>"   ask an owner for a change\n'
            f'  {L} notices amend <id> --summary "<one sentence>" [--body "<3-6 lines>"]   fix a notice you wrote\n'
            f"  {L} notices --mark-read                       mark your notices read",
        )
    return check_lane(plan, member_id, rel_path)


def check_commit_path(root, plan: Plan, member_id: str, rel_path: str, staged: bool = True) -> LaneDecision:
    """The lane rule for a commit (or uncommitted change) to `rel_path`.

    Same as `check_lane`, except for plan.yaml from someone other than the plan owner:
    that's allowed only when, compared with the last committed plan, the sole
    difference is the `status` of tasks they own (what `lanes task status` writes).
    The plan owner is taken from the COMMITTED plan, so nobody can make themselves
    owner and commit it in one go.
    """
    if rel_path.lower() != ".lanes/plan.yaml":
        return check_lane(plan, member_id, rel_path)
    from .plandiff import committed_plan, status_only_change

    ok, why = status_only_change(root, member_id, staged=staged)
    if ok is None:  # no committed plan to compare with (e.g. the first commit)
        return check_lane(plan, member_id, rel_path)
    if ok:
        return LaneDecision(True, plan.owner_of(rel_path), why)
    committed, _ = committed_plan(root)  # explain with the committed owner, not an edited `owner:`
    base = committed or plan
    return LaneDecision(False, base.owner_of(rel_path), check_lane(base, member_id, rel_path).reason + f"\n({why})")


def _describe(own: Ownership) -> str:
    if own.kind == "plan":
        return "the plan"
    if own.kind == "contract" and own.contract:
        return f"contract `{own.contract.id}`"
    if own.kind == "hub" and own.hub:
        return f"hub file `{own.hub.path}`"
    if own.kind == "task" and own.task:
        return f"task {own.task.id} '{own.task.title}'"
    return own.kind
