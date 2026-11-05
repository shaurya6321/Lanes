"""The lane rule, shared by the PreToolUse guard, `lanes check` and the pre-commit hook."""

from __future__ import annotations

from dataclasses import dataclass

from .plan import Ownership, Plan


@dataclass(frozen=True)
class LaneDecision:
    allowed: bool
    ownership: Ownership
    reason: str  # always set; explains allow or deny


def check_lane(plan: Plan, member_id: str, rel_path: str) -> LaneDecision:
    own = plan.owner_of(rel_path)
    mine = ", ".join(t.id for t in plan.tasks_of(member_id)) or "no tasks"

    if own.kind == "lanes":
        return LaneDecision(True, own, f"{rel_path} is Lanes coordination state (.lanes/), which anyone may write")
    if own.owner == member_id:
        return LaneDecision(True, own, f"{rel_path} is in your lane ({_describe(own)})")

    if own.kind == "unowned":
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
            f'  lanes request --file "{rel_path}" "<what you need changed and why>"\n'
            f"then continue with the parts of your task you can do inside your lane."
        )
    return LaneDecision(False, own, reason)


def _describe(own: Ownership) -> str:
    if own.kind == "contract" and own.contract:
        return f"contract `{own.contract.id}`"
    if own.kind == "hub" and own.hub:
        return f"hub file `{own.hub.path}`"
    if own.kind == "task" and own.task:
        return f"task {own.task.id} '{own.task.title}'"
    return own.kind
