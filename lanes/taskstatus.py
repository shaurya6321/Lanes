"""`lanes task status TASK STATUS`: a task's owner updates its status without owning plan.yaml.

Only the plan owner edits .lanes/plan.yaml directly (the guard and the commit
check enforce it). Everyone else changes the status of their own tasks through
this command. Lanes rewrites just that task's `status:` line, keeping comments
and formatting, then re-reads the file to prove nothing else changed. The commit
check accepts the result because the only difference is that status. Status-only
changes never create plan notices.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .paths import PLAN_FILE
from .plan import VALID_STATUS, Plan, PlanError, parse_plan


def _task_block(lines: list[str], task_id: str) -> tuple[int, int, int] | None:
    """(id line index, end index, key column) of `- id: TASK` inside the top-level `tasks:` list."""
    start = next((i for i, ln in enumerate(lines) if re.match(r"^tasks:\s*(#.*)?$", ln)), None)
    if start is None:
        return None
    item = re.compile(r"^(\s*)-\s+id:\s*(['\"]?)" + re.escape(task_id) + r"\2\s*(#.*)?$")
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln[0].isspace() and not ln.startswith(("-", "#")):
            return None  # next top-level key: the tasks list ended
        m = item.match(ln)
        if not m:
            continue
        dash = len(m.group(1))
        col = ln.index("id:")
        end = i + 1
        while end < len(lines):
            nxt = lines[end]
            if nxt.strip() and not nxt.lstrip().startswith("#"):
                indent = len(nxt) - len(nxt.lstrip())
                if indent <= dash:
                    break
            end += 1
        return i, end, col
    return None


def _without(data: dict, task_id: str) -> dict:
    from .plandiff import _without_status

    return _without_status(data, {task_id})


def set_status(root: Path, plan: Plan, member: str, task_id: str, status: str) -> tuple[str, str]:
    """Set `task_id`'s status in plan.yaml. Returns (old, new). Raises ValueError with a readable reason."""
    task = plan.task(task_id)
    if task is None:
        raise ValueError(f"no task {task_id!r} in {PLAN_FILE} (tasks: {', '.join(t.id for t in plan.tasks)})")
    if status not in VALID_STATUS:
        raise ValueError(f"status must be one of: {', '.join(VALID_STATUS)}")
    if task.owner != member:
        raise ValueError(f"{task_id} belongs to {task.owner}; only its owner can change its status")
    if task.status == status:
        return status, status

    path = root / PLAN_FILE
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    found = _task_block(lines, task_id)
    if found is None:
        raise ValueError(f"couldn't find `- id: {task_id}` under `tasks:` in {PLAN_FILE}; ask the plan owner ({plan.owner}) to update it")
    first, end, col = found
    pat = re.compile(r"^(\s{" + str(col) + r"}status:\s*)([^#\s]+)(\s*(#.*)?)$")
    for i in range(first, end):
        m = pat.match(lines[i].rstrip("\r\n"))
        if m:
            eol = lines[i][len(lines[i].rstrip("\r\n")):]
            lines[i] = m.group(1) + status + m.group(3) + eol
            break
    else:
        eol = "\r\n" if lines[first].endswith("\r\n") else "\n"
        lines.insert(first + 1, " " * col + f"status: {status}{eol}")
    new_text = "".join(lines)

    # Prove the edit changed exactly one field before writing it.
    old_data, new_data = yaml.safe_load(text), yaml.safe_load(new_text)
    try:
        parse_plan(new_data, root)
    except PlanError as exc:  # pragma: no cover - the edit only touches a valid status
        raise ValueError(f"refusing to write an invalid plan: {exc}") from exc
    new_task = next((t for t in new_data.get("tasks") or [] if isinstance(t, dict) and t.get("id") == task_id), {})
    if new_task.get("status") != status or _without(old_data, task_id) != _without(new_data, task_id):
        raise ValueError(f"couldn't update {task_id} safely (unusual YAML layout); ask the plan owner ({plan.owner}) to update it")
    path.write_text(new_text, encoding="utf-8", newline="")
    return task.status, status
