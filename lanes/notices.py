"""Change notices and requests, stored as markdown files with YAML front matter.

    .lanes/notices/<created>-<from>-<topic>.md      one file per notice (shared via git)
    .lanes/notices/read-by/<member>.txt             ids that member has read (only they append)

Routing rule (the anti-livelock rule): an automatic change notice goes ONLY to
tasks with a strictly HIGHER rank than the task that made the change. Requests
(`lanes request`) are explicit asks from a human/agent to an owner and are not
rank-filtered; the owner decides what to do.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .plan import Contract, Ownership, Plan, Task
from .redact import redact

NOTICES_DIR = Path(".lanes") / "notices"
READ_DIR = NOTICES_DIR / "read-by"
MAX_BODY_CHARS = 600  # ~150 tokens
MAX_BODY_LINES = 6

_FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Notice:
    id: str
    kind: str  # "change" | "request" | "plan"
    from_member: str
    from_task: str | None
    from_rank: int
    to_tasks: list[str]
    to_members: list[str]
    created: str
    summary: str
    body: str = ""
    contract: str | None = None
    file: str | None = None
    session: str | None = None
    base: str | None = None  # plan notices: the commit the plan was compared against
    path: Path | None = field(default=None, compare=False)

    def front_matter(self) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "from_member": self.from_member,
            "from_task": self.from_task,
            "from_rank": self.from_rank,
            "to_tasks": self.to_tasks,
            "to_members": self.to_members,
            "contract": self.contract,
            "file": self.file,
            "created": self.created,
            "session": self.session,
            "base": self.base,
            "summary": self.summary,
        }
        return {k: v for k, v in data.items() if v is not None}

    def render(self) -> str:
        fm = yaml.safe_dump(self.front_matter(), sort_keys=False, allow_unicode=True, width=1000).strip()
        return f"---\n{fm}\n---\n{self.body.strip()}\n"

    @property
    def topic(self) -> str:
        return self.contract or self.file or "-"


# ---- routing ------------------------------------------------------------------


def route_change(plan: Plan, from_task: Task | None, contract: Contract | None = None) -> list[str]:
    """Tasks to notify about a change made by `from_task`, lowest rank first.

    Candidates: tasks that `use` the changed contract, plus every task that
    (transitively) depends on `from_task`. Only strictly higher ranks survive.
    """
    rank = from_task.rank if from_task else 0
    candidates: set[str] = set()
    if contract:
        candidates |= {t.id for t in plan.tasks if contract.id in t.uses}
    if from_task:
        candidates |= plan.dependents(from_task.id)
        candidates.discard(from_task.id)
    targets = [plan.task(tid) for tid in candidates]
    return [t.id for t in sorted((t for t in targets if t and t.rank > rank), key=lambda t: (t.rank, t.id))]


def source_task(plan: Plan, member_id: str, rel: str, ownership: Ownership) -> Task | None:
    """Which of my tasks a change to `rel` comes from."""
    if ownership.kind == "contract" and ownership.task and ownership.task.owner == member_id:
        return ownership.task
    t = plan.task_for(rel)
    if t and t.owner == member_id:
        return t
    mine = plan.tasks_of(member_id)
    active = [t for t in mine if t.status != "done"]
    return (active or mine or [None])[0]


def owners_of(plan: Plan, task_ids: list[str]) -> list[str]:
    seen: list[str] = []
    for tid in task_ids:
        t = plan.task(tid)
        if t and t.owner not in seen:
            seen.append(t.owner)
    return seen


# ---- describing a change --------------------------------------------------------


def describe_change(old: str, new: str) -> list[str]:
    """Up to MAX_BODY_LINES '-'/'+' lines describing how `old` became `new`."""
    lines: list[str] = []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        text = line[1:].strip()
        if text:
            lines.append(f"{line[0]} {_clip(text, 100)}")
    if len(lines) > MAX_BODY_LINES:
        extra = len(lines) - (MAX_BODY_LINES - 1)
        lines = lines[: MAX_BODY_LINES - 1] + [f"... (+{extra} more changed lines)"]
    return lines


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 3] + "..."


def cap_body(body: str) -> str:
    body = redact(body)
    lines = body.strip().splitlines()[: MAX_BODY_LINES + 2]
    out = "\n".join(lines)
    return out if len(out) <= MAX_BODY_CHARS else out[: MAX_BODY_CHARS - 3] + "..."


# ---- storage ------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:40] or "notice"


def new_id(root: Path, created: datetime, origin: str, topic: str) -> str:
    base = f"{created.strftime('%Y%m%dT%H%M%SZ')}-{_slug(origin)}-{_slug(topic)}"
    candidate, n = base, 2
    while (root / NOTICES_DIR / f"{candidate}.md").exists():
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def write_notice(root: Path, notice: Notice) -> Path:
    notice.summary = _clip(redact(notice.summary).replace("\n", " ").strip(), 300)
    notice.body = cap_body(notice.body)
    folder = root / NOTICES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = notice.path or folder / f"{notice.id}.md"
    path.write_text(notice.render(), encoding="utf-8", newline="\n")
    notice.path = path
    return path


def _lenient_front_matter(text: str) -> dict:
    """Fallback for hand-edited front matter that isn't valid YAML.

    Agents rewrite the `summary:` line, and an unquoted value containing ': '
    (for example `getItem(id: str) -> Item`) breaks strict YAML. Notices must
    never be dropped silently, so read `key: value` and `- item` lines directly.
    """
    data: dict = {}
    key = None
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_]+):(?:\s+(.*))?$", line)
        if m:
            key, val = m.group(1), (m.group(2) or "").strip()
            if not val:
                data[key] = []
            elif val.startswith("[") and val.endswith("]"):
                data[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif len(val) >= 2 and val[0] in "'\"" and val[-1] == val[0]:
                data[key] = val[1:-1]
            else:
                data[key] = val
        elif key and line.lstrip().startswith("- "):
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(line.lstrip()[2:].strip().strip("'\""))
    return data


def parse_notice(path: Path) -> Notice | None:
    try:
        m = _FRONT.match(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
        if not m:
            return None
        try:
            fm = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            fm = None
        if not isinstance(fm, dict):
            fm = _lenient_front_matter(m.group(1))
        for k in ("from_task", "contract", "file", "session", "base"):
            if fm.get(k) == []:  # lenient parser: "key:" with nothing after it
                fm[k] = None
        return Notice(
            id=str(fm.get("id") or path.stem),
            kind=str(fm.get("kind", "change")),
            from_member=str(fm.get("from_member", "?")),
            from_task=fm.get("from_task"),
            from_rank=int(fm.get("from_rank") or 0),
            to_tasks=[str(t) for t in fm.get("to_tasks") or []],
            to_members=[str(t) for t in fm.get("to_members") or []],
            created=str(fm.get("created", "")),
            summary=str(fm.get("summary", "")),
            body=m.group(2).strip(),
            contract=fm.get("contract"),
            file=fm.get("file"),
            session=fm.get("session"),
            base=fm.get("base"),
            path=path,
        )
    except (OSError, ValueError, yaml.YAMLError):
        return None


def _notice_files(root: Path) -> list[Path]:
    folder = root / NOTICES_DIR
    return [p for p in folder.glob("*.md") if not p.name.startswith("_")] if folder.is_dir() else []


def list_notices(root: Path) -> list[Notice]:
    found = [parse_notice(p) for p in _notice_files(root)]
    return sorted((n for n in found if n), key=lambda n: (n.created, n.id))


def unreadable_notices(root: Path) -> list[str]:
    """Notice files that couldn't be parsed at all, so `lanes status` can warn instead of hiding them."""
    return sorted(p.relative_to(root).as_posix() for p in _notice_files(root) if parse_notice(p) is None)


def addressed_to(notice: Notice, plan: Plan, member_id: str) -> bool:
    if member_id in notice.to_members:
        return True
    return any(t.id in notice.to_tasks for t in plan.tasks_of(member_id))


def read_ids(root: Path, member_id: str) -> set[str]:
    path = root / READ_DIR / f"{member_id}.txt"
    try:
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        return set()


def mark_read(root: Path, member_id: str, ids: list[str]) -> int:
    already = read_ids(root, member_id)
    fresh = [i for i in ids if i not in already]
    if fresh:
        path = root / READ_DIR / f"{member_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.writelines(f"{i}\n" for i in fresh)
    return len(fresh)


def unread_for(root: Path, plan: Plan, member_id: str) -> list[Notice]:
    seen = read_ids(root, member_id)
    return [n for n in list_notices(root) if n.id not in seen and addressed_to(n, plan, member_id)]


def read_by_anyone(root: Path, notice_id: str) -> bool:
    folder = root / READ_DIR
    if not folder.is_dir():
        return False
    return any(notice_id in read_ids(root, p.stem) for p in folder.glob("*.txt"))


def find_notice(root: Path, notice_id: str) -> Notice | None:
    return next((n for n in list_notices(root) if n.id == notice_id), None)


def amend(root: Path, member_id: str, notice_id: str, summary: str | None = None, body: str | None = None) -> Notice:
    """Rewrite the summary and/or body of a notice I wrote that nobody has read yet.

    This is the only supported way to change a notice: the lane guard blocks direct
    edits to .lanes/notices/, and writing through here always produces valid YAML.
    """
    n = find_notice(root, notice_id)
    if n is None:
        raise ValueError(f"no notice with id {notice_id!r} (see `lanes notices --all`)")
    if n.from_member != member_id:
        raise ValueError(f"notice {notice_id} was written by {n.from_member}; only its author can amend it")
    if read_by_anyone(root, n.id):
        raise ValueError(f"notice {notice_id} has already been read; send a new one with `lanes request --to <member>` instead")
    if not (summary or "").strip() and not (body or "").strip():
        raise ValueError("give --summary and/or --body")
    if summary and summary.strip():
        n.summary = summary.strip()
    if body and body.strip():
        n.body = body.replace("\\n", "\n")
    write_notice(root, n)
    return n


# ---- high-level constructors ----------------------------------------------------------


def record_change(
    root: Path,
    plan: Plan,
    member_id: str,
    rel: str,
    ownership: Ownership,
    change_lines: list[str],
    session: str | None = None,
) -> tuple[Notice | None, bool]:
    """Create (or, within one session, extend) a change notice for a contract/hub edit.

    Returns (notice, created_new). Returns (None, False) when nobody downstream needs to know.
    """
    task = source_task(plan, member_id, rel, ownership)
    contract = ownership.contract if ownership.kind == "contract" else None
    targets = route_change(plan, task, contract)
    if not targets:
        return None, False

    topic_kw = {"contract": contract.id} if contract else {"file": rel}
    label = f"contract `{contract.id}`" if contract else f"hub file `{rel}`"

    # Coalesce repeated edits in one session into one notice, until someone reads it.
    if session:
        for n in reversed(list_notices(root)):
            if n.session == session and n.kind == "change" and n.topic == (contract.id if contract else rel):
                if not read_by_anyone(root, n.id):
                    merged = [ln for ln in n.body.splitlines() if ln.strip()] + change_lines
                    n.body = "\n".join(merged[-MAX_BODY_LINES:])
                    n.to_tasks = sorted(set(n.to_tasks) | set(targets), key=lambda t: plan.task(t).rank if plan.task(t) else 0)
                    n.to_members = owners_of(plan, n.to_tasks)
                    write_notice(root, n)
                    return n, False
                break

    created = utc_now()
    origin = task.id if task else member_id
    notice = Notice(
        id=new_id(root, created, origin, contract.id if contract else rel),
        kind="change",
        from_member=member_id,
        from_task=task.id if task else None,
        from_rank=task.rank if task else 0,
        to_tasks=targets,
        to_members=owners_of(plan, targets),
        created=iso(created),
        summary=f"{label} changed (auto-generated; the author should replace this line with a precise summary)",
        body="\n".join(change_lines) or f"{rel} was rewritten.",
        session=session,
        **topic_kw,
    )
    write_notice(root, notice)
    return notice, True


def make_request(
    root: Path,
    plan: Plan,
    member_id: str,
    message: str,
    rel: str | None = None,
    to_member: str | None = None,
) -> Notice:
    """An explicit ask to the owner of `rel` (or to `to_member`)."""
    to_tasks: list[str] = []
    if rel:
        own = plan.owner_of(rel)
        to_member = to_member or own.owner
        if own.task:
            to_tasks = [own.task.id]
    if not to_member or not plan.member(to_member):
        raise ValueError(f"cannot find an owner to ask (path={rel!r}, to={to_member!r}); use --to <member>")
    if not to_tasks:
        to_tasks = [t.id for t in plan.tasks_of(to_member) if t.status != "done"][:1]

    mine = [t for t in plan.tasks_of(member_id) if t.status != "done"] or plan.tasks_of(member_id)
    task = mine[0] if mine else None
    created = utc_now()
    first, _, rest = message.strip().partition("\n")
    notice = Notice(
        id=new_id(root, created, task.id if task else member_id, f"request-{rel or to_member}"),
        kind="request",
        from_member=member_id,
        from_task=task.id if task else None,
        from_rank=task.rank if task else 0,
        to_tasks=to_tasks,
        to_members=[to_member],
        created=iso(created),
        summary=first,
        body=(rest.strip() or first),
        file=rel,
    )
    write_notice(root, notice)
    return notice
