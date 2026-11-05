"""Load and validate `.lanes/plan.yaml` (spec: docs/PLAN_FORMAT.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import PLAN_FILE, glob_match, specificity, to_posix

try:  # the C loader is much faster when available
    _Loader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover
    _Loader = yaml.SafeLoader

VALID_STATUS = ("todo", "in_progress", "blocked", "review", "done")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class PlanError(Exception):
    """The plan is missing or invalid. `errors` lists every problem found."""

    def __init__(self, errors: list[str], missing: bool = False):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.missing = missing


@dataclass(frozen=True)
class Member:
    id: str
    email: str | None = None


@dataclass(frozen=True)
class HubFile:
    path: str
    owner: str


@dataclass(frozen=True)
class Contract:
    id: str
    file: str
    owner: str


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    rank: int
    owner: str
    owns: tuple[str, ...] = ()
    implements: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    status: str = "todo"


@dataclass(frozen=True)
class Ownership:
    """Who owns a path, and why."""

    kind: str  # "lanes" | "contract" | "hub" | "task" | "unowned"
    owner: str | None = None
    task: Task | None = None
    contract: Contract | None = None
    hub: HubFile | None = None


@dataclass
class Plan:
    feature: str
    updated: str | None
    members: list[Member]
    hub_files: list[HubFile] = field(default_factory=list)
    contracts: list[Contract] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    root: Path | None = None

    # ---- lookups -----------------------------------------------------------

    def member(self, member_id: str) -> Member | None:
        return next((m for m in self.members if m.id == member_id), None)

    def task(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def contract(self, contract_id: str) -> Contract | None:
        return next((c for c in self.contracts if c.id == contract_id), None)

    def tasks_of(self, member_id: str) -> list[Task]:
        return sorted((t for t in self.tasks if t.owner == member_id), key=lambda t: (t.rank, t.id))

    def tasks_by_rank(self) -> list[Task]:
        return sorted(self.tasks, key=lambda t: (t.rank, t.id))

    def contract_for_file(self, rel: str) -> Contract | None:
        rel = to_posix(rel)
        return next((c for c in self.contracts if to_posix(c.file) == rel), None)

    def hub_for(self, rel: str) -> HubFile | None:
        hits = [h for h in self.hub_files if glob_match(h.path, rel)]
        return max(hits, key=lambda h: specificity(h.path), default=None)

    def task_for(self, rel: str) -> Task | None:
        """The task whose `owns` pattern matches `rel` most specifically."""
        best: tuple[tuple[int, int], int, Task] | None = None
        for t in self.tasks:
            for pat in t.owns:
                if glob_match(pat, rel):
                    key = (specificity(pat), -t.rank, t)
                    if best is None or key[:2] > best[:2]:
                        best = key
        return best[2] if best else None

    def owner_of(self, rel: str) -> Ownership:
        """Precedence: contract file > anything else in .lanes/ > hub file > task."""
        rel = to_posix(rel)
        c = self.contract_for_file(rel)
        if c:
            return Ownership("contract", c.owner, contract=c, task=self.implementer(c.id))
        if rel == ".lanes" or rel.startswith(".lanes/"):
            return Ownership("lanes")
        h = self.hub_for(rel)
        if h:
            return Ownership("hub", h.owner, hub=h)
        t = self.task_for(rel)
        if t:
            return Ownership("task", t.owner, task=t)
        return Ownership("unowned")

    def implementer(self, contract_id: str) -> Task | None:
        return next((t for t in self.tasks_by_rank() if contract_id in t.implements), None)

    def dependents(self, task_id: str) -> set[str]:
        """All tasks that depend on `task_id`, directly or transitively."""
        found: set[str] = set()
        frontier = [task_id]
        while frontier:
            cur = frontier.pop()
            for t in self.tasks:
                if cur in t.depends_on and t.id not in found:
                    found.add(t.id)
                    frontier.append(t.id)
        return found


# ---- loading -------------------------------------------------------------------


def plan_path(root: Path | str) -> Path:
    return Path(root) / PLAN_FILE


def load_plan(root: Path | str) -> Plan:
    path = plan_path(root)
    if not path.is_file():
        raise PlanError([f"{PLAN_FILE} not found"], missing=True)
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
    except yaml.YAMLError as exc:
        raise PlanError([f"{PLAN_FILE} is not valid YAML: {exc}"]) from exc
    return parse_plan(data, Path(root))


def parse_plan(data: Any, root: Path | None = None) -> Plan:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise PlanError(["plan must be a YAML mapping"])

    feature = data.get("feature")
    if not isinstance(feature, str) or not feature.strip():
        errors.append("`feature` is required (a non-empty string)")
        feature = ""
    updated = data.get("updated")
    updated = str(updated) if updated is not None else None

    members = _parse_members(data.get("members"), errors)
    member_ids = {m.id for m in members}

    def check_owner(owner: Any, where: str) -> str:
        if not isinstance(owner, str) or owner not in member_ids:
            errors.append(f"{where}: owner {owner!r} is not in members")
        return str(owner)

    hubs: list[HubFile] = []
    for i, h in enumerate(_list(data, "hub_files", errors)):
        if not isinstance(h, dict) or not isinstance(h.get("path"), str):
            errors.append(f"hub_files[{i}]: needs `path` and `owner`")
            continue
        hubs.append(HubFile(to_posix(h["path"]), check_owner(h.get("owner"), f"hub_files[{i}]")))

    contracts: list[Contract] = []
    for i, c in enumerate(_list(data, "contracts", errors)):
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not isinstance(c.get("file"), str):
            errors.append(f"contracts[{i}]: needs `id`, `file` and `owner`")
            continue
        if any(x.id == c["id"] for x in contracts):
            errors.append(f"contracts: duplicate id {c['id']!r}")
        contracts.append(Contract(c["id"], to_posix(c["file"]), check_owner(c.get("owner"), f"contract {c['id']}")))
    contract_ids = {c.id for c in contracts}

    tasks: list[Task] = []
    for i, t in enumerate(_list(data, "tasks", errors)):
        task = _parse_task(t, i, errors, check_owner, contract_ids)
        if task:
            if any(x.id == task.id for x in tasks):
                errors.append(f"tasks: duplicate id {task.id!r}")
            tasks.append(task)

    _check_cross_refs(tasks, contracts, hubs, errors)
    if errors:
        raise PlanError(errors)
    return Plan(feature, updated, members, hubs, contracts, tasks, root)


def _list(data: dict, key: str, errors: list[str]) -> list:
    value = data.get(key) or []
    if not isinstance(value, list):
        errors.append(f"`{key}` must be a list")
        return []
    return value


def _str_list(value: Any, where: str, errors: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errors.append(f"{where} must be a list of strings")
        return ()
    return tuple(value)


def _parse_members(raw: Any, errors: list[str]) -> list[Member]:
    if not isinstance(raw, list) or not raw:
        errors.append("`members` must be a non-empty list")
        return []
    members: list[Member] = []
    for i, m in enumerate(raw):
        mid = m.get("id") if isinstance(m, dict) else None
        if not isinstance(mid, str) or not _ID.match(mid):
            errors.append(f"members[{i}]: `id` must be letters, digits, '.', '_' or '-'")
            continue
        if any(x.id == mid for x in members):
            errors.append(f"members: duplicate id {mid!r}")
        email = m.get("email")
        members.append(Member(mid, str(email) if email else None))
    return members


def _parse_task(t: Any, i: int, errors: list[str], check_owner, contract_ids: set[str]) -> Task | None:
    if not isinstance(t, dict) or not isinstance(t.get("id"), str) or not _ID.match(t["id"]):
        errors.append(f"tasks[{i}]: `id` is required (letters, digits, '.', '_' or '-')")
        return None
    tid = t["id"]
    rank = t.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        errors.append(f"task {tid}: `rank` must be an integer >= 1")
        rank = 0
    status = t.get("status", "todo")
    if status not in VALID_STATUS:
        errors.append(f"task {tid}: `status` must be one of {', '.join(VALID_STATUS)}")
    implements = _str_list(t.get("implements"), f"task {tid}: `implements`", errors)
    uses = _str_list(t.get("uses"), f"task {tid}: `uses`", errors)
    for cid in (*implements, *uses):
        if cid not in contract_ids:
            errors.append(f"task {tid}: unknown contract {cid!r}")
    return Task(
        id=tid,
        title=str(t.get("title", "")),
        rank=rank,
        owner=check_owner(t.get("owner"), f"task {tid}"),
        owns=tuple(to_posix(p) for p in _str_list(t.get("owns"), f"task {tid}: `owns`", errors)),
        implements=implements,
        uses=uses,
        depends_on=_str_list(t.get("depends_on"), f"task {tid}: `depends_on`", errors),
        status=str(status),
    )


def _check_cross_refs(tasks: list[Task], contracts: list[Contract], hubs: list[HubFile], errors: list[str]) -> None:
    by_id = {t.id: t for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep == t.id:
                errors.append(f"task {t.id}: cannot depend on itself")
            elif dep not in by_id:
                errors.append(f"task {t.id}: depends on unknown task {dep!r}")
            elif by_id[dep].rank >= t.rank:
                errors.append(
                    f"task {t.id} (rank {t.rank}) depends on {dep} (rank {by_id[dep].rank}); "
                    "a dependency must have a lower rank"
                )
        for cid in t.implements:
            c = next((c for c in contracts if c.id == cid), None)
            if c and c.owner != t.owner:
                errors.append(f"task {t.id} implements contract {cid}, but {cid} is owned by {c.owner}, not {t.owner}")

    claimed: dict[str, str] = {}
    for h in hubs:
        if claimed.setdefault(h.path, h.owner) != h.owner:
            errors.append(f"{h.path!r} is claimed by both {claimed[h.path]} and {h.owner}")
    for t in tasks:
        for pat in t.owns:
            if claimed.setdefault(pat, t.owner) != t.owner:
                errors.append(f"{pat!r} is claimed by both {claimed[pat]} and {t.owner} (task {t.id})")
