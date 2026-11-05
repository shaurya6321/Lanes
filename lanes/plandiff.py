"""Plan-change notices: tell teammates when the plan owner changes who owns what.

When the plan owner edits `.lanes/plan.yaml`, the plan is compared with the last
committed version (git HEAD). Every task whose `owns`, `uses`, `implements`,
`owner` or `rank` changed gets one `kind: plan` notice, except the editor's own
tasks. Former owners of a reassigned or removed task are notified too.

Unlike contract change notices, plan notices are not rank-filtered. A rank-2
task losing files must hear about it even though the change came from rank 1.
This can't ping-pong, because only the plan owner's edits create plan notices.

Repeated edits against the same base commit rewrite one unread notice in place,
so the notice always describes the full change since the last commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import gitutil
from .notices import Notice, iso, list_notices, new_id, read_by_anyone, utc_now, write_notice
from .paths import PLAN_FILE
from .plan import Plan, PlanError, Task, parse_plan

AUTO_PREFIX = "Plan changed by "
_FIELDS = ("owns", "uses", "implements")


@dataclass
class PlanChange:
    lines: list[str] = field(default_factory=list)  # every change, for the body
    tasks: list[str] = field(default_factory=list)  # tasks (in the new plan) to notify
    members: list[str] = field(default_factory=list)  # people to notify, including former owners


def committed_plan(root: Path) -> tuple[Plan | None, str | None]:
    """The plan at HEAD and HEAD's sha, or (None, None) if there isn't a valid one."""
    sha = gitutil.run_git(root, "rev-parse", "HEAD")
    text = gitutil.show_head(root, PLAN_FILE)
    if not sha or text is None:
        return None, None
    try:
        return parse_plan(yaml.safe_load(text), root), sha.strip()
    except (PlanError, yaml.YAMLError):
        return None, None


def _task_lines(old: Task | None, new: Task | None) -> list[str]:
    if old is None and new is not None:
        return [f"+ {new.id} added (owner {new.owner}, rank {new.rank}, owns {', '.join(new.owns) or '-'})"]
    if new is None and old is not None:
        return [f"- {old.id} removed (was {old.owner}, owned {', '.join(old.owns) or '-'})"]
    lines: list[str] = []
    if old.owner != new.owner:
        lines.append(f"~ {new.id} owner: {old.owner} -> {new.owner}")
    if old.rank != new.rank:
        lines.append(f"~ {new.id} rank: {old.rank} -> {new.rank}")
    for name in _FIELDS:
        before, after = getattr(old, name), getattr(new, name)
        added = [x for x in after if x not in before]
        removed = [x for x in before if x not in after]
        if added or removed:
            parts = [f"+{x}" for x in added] + [f"-{x}" for x in removed]
            lines.append(f"~ {new.id} {name}: {' '.join(parts)}")
    return lines


def diff_plans(old: Plan, new: Plan, editor: str) -> PlanChange:
    change = PlanChange()
    ids = [t.id for t in old.tasks_by_rank()] + [t.id for t in new.tasks_by_rank() if old.task(t.id) is None]
    for tid in dict.fromkeys(ids):
        before, after = old.task(tid), new.task(tid)
        lines = _task_lines(before, after)
        if not lines:
            continue
        change.lines += lines
        owners = {t.owner for t in (before, after) if t}
        if owners <= {editor}:
            continue  # only my own task changed: nobody else to tell
        if after is not None and after.owner != editor:
            change.tasks.append(tid)
        for who in (after.owner if after else None, before.owner if before else None):
            if who and who != editor and who not in change.members:
                change.members.append(who)
    return change


def auto_summary(editor: str, change: PlanChange, new: Plan) -> str:
    who = ", ".join(f"{t} ({new.task(t).owner})" for t in change.tasks if new.task(t)) or ", ".join(change.members)
    return f"{AUTO_PREFIX}{editor}: task ownership changed for {who}. See the lines below."


def record_plan_change(root: Path, new: Plan, editor: str, session: str | None = None) -> tuple[Notice | None, bool]:
    """Write, update or withdraw the plan notice for the editor's uncommitted plan edits.

    Returns (notice, created_new). Returns (None, False) when the editor isn't the
    plan owner, there's no committed plan to compare with, or nobody else is affected.
    """
    if editor != new.owner:
        return None, False
    old, base = committed_plan(root)
    if old is None:
        return None, False
    change = diff_plans(old, new, editor)

    existing = next(
        (n for n in reversed(list_notices(root)) if n.kind == "plan" and n.from_member == editor and n.base == base and not read_by_anyone(root, n.id)),
        None,
    )
    if not change.members:
        if existing and existing.path:
            existing.path.unlink(missing_ok=True)  # the edit was undone before anyone saw it
        return None, False

    mine = [t for t in new.tasks_of(editor) if t.status != "done"] or new.tasks_of(editor)
    if existing:
        existing.to_tasks, existing.to_members = change.tasks, change.members
        existing.body = "\n".join(change.lines)
        if existing.summary.startswith(AUTO_PREFIX):
            existing.summary = auto_summary(editor, change, new)
        write_notice(root, existing)
        return existing, False

    created = utc_now()
    notice = Notice(
        id=new_id(root, created, mine[0].id if mine else editor, "plan"),
        kind="plan",
        from_member=editor,
        from_task=mine[0].id if mine else None,
        from_rank=mine[0].rank if mine else 0,
        to_tasks=change.tasks,
        to_members=change.members,
        created=iso(created),
        summary=auto_summary(editor, change, new),
        body="\n".join(change.lines),
        file=PLAN_FILE,
        session=session,
        base=base,
    )
    write_notice(root, notice)
    return notice, True


def ownership_changed(root: Path, new: Plan, editor: str) -> bool:
    """True when the uncommitted plan changes anyone else's tasks (used to warn non-owners)."""
    old, _ = committed_plan(root)
    return bool(old and diff_plans(old, new, editor).members)
