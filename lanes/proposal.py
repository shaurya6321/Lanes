"""Plan proposals: `/lanes-plan` drafts, `lanes plan check|diff|accept` review and apply.

The planner (Claude, run by the plan owner) never edits `.lanes/plan.yaml`. It writes:

- `.lanes/plan.proposed.yaml`: a complete plan in the normal schema, plus a top-level
  `proposal:` block (`based_on`, `touches`, `rationale`) that `accept` strips;
- `.lanes/proposal/contracts/<name>.md`: drafts of new contracts, moved by `accept`
  to the `file:` the proposal gives them (always under `.lanes/contracts/`).

Only the plan owner writes these (see `Plan.owner_of`). `accept` keeps every existing
task's current status (statuses belong to task owners), then sends the normal plan
notices, exactly as if the plan owner had edited plan.yaml by hand.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from . import gitutil
from .paths import PLAN_FILE, glob_match, globs_overlap, to_posix
from .plan import Ownership, Plan, PlanError, Task, load_plan, parse_plan

PROPOSAL_FILE = ".lanes/plan.proposed.yaml"
PROPOSAL_DIR = ".lanes/proposal"
DRAFT_CONTRACTS = ".lanes/proposal/contracts"
CONTRACTS_DIR = ".lanes/contracts"
PLAN_MD = ".lanes/PLAN.md"
MAX_LIST = 10


def is_proposal_path(rel: str) -> bool:
    low = to_posix(rel).lower()
    return low == PROPOSAL_FILE or low == PROPOSAL_DIR or low.startswith(PROPOSAL_DIR + "/")


def plan_fingerprint(root: Path) -> str:
    """Short hash of the current plan.yaml (line endings normalized), or "none". Written as `based_on`."""
    try:
        raw = (root / PLAN_FILE).read_bytes()
    except OSError:
        return "none"
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()[:12]


class ProposalError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Proposal:
    plan: Plan
    data: dict
    text: str
    based_on: str | None
    touches: tuple[str, ...]


def load_proposal(root: Path) -> Proposal:
    path = root / PROPOSAL_FILE
    if not path.is_file():
        raise ProposalError([f"{PROPOSAL_FILE} doesn't exist. The plan owner creates it by running /lanes-plan in Claude Code."])
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProposalError([f"{PROPOSAL_FILE} is not valid YAML: {exc}"]) from exc
    errors: list[str] = []
    meta = data.get("proposal") if isinstance(data, dict) else None
    if meta is None:
        meta = {}
    elif not isinstance(meta, dict):
        errors.append("`proposal` must be a mapping (based_on, touches, rationale)")
        meta = {}
    touches = meta.get("touches") or []
    if not isinstance(touches, list) or not all(isinstance(t, str) for t in touches):
        errors.append("`proposal.touches` must be a list of paths or globs")
        touches = []
    based_on = meta.get("based_on")
    try:
        plan = parse_plan(data, root)
    except PlanError as exc:
        raise ProposalError(errors + exc.errors) from exc
    if errors:
        raise ProposalError(errors)
    return Proposal(plan, data, text, str(based_on) if based_on is not None else None, tuple(to_posix(t) for t in touches))


def current_plan(root: Path) -> Plan | None:
    try:
        return load_plan(root)
    except PlanError:
        return None


# ---- check -----------------------------------------------------------------------------


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    proposal: Proposal | None = None
    stale: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def check_proposal(root: Path) -> CheckResult:
    res = CheckResult()
    try:
        prop = load_proposal(root)
    except ProposalError as exc:
        res.errors += exc.errors
        return res
    res.proposal = prop
    plan = prop.plan
    files = [f for f in gitutil.tracked_files(root) if not f.startswith(".lanes/")]

    _check_overlaps(plan, res)
    _check_contracts(root, plan, res)
    _check_touches(root, plan, prop.touches, files, res)
    _check_hubs(plan, res)
    _check_members(root, plan, res)

    unowned = [f for f in files if plan.owner_of(f).kind == "unowned"]
    if unowned:
        res.warnings.append(f"{len(unowned)} file(s) in the repo have no owner (fine if nobody will touch them): {_group(unowned)}")

    if prop.based_on is None:
        res.warnings.append("`proposal.based_on` is missing, so Lanes can't tell whether plan.yaml changed since this was drafted")
    elif prop.based_on != plan_fingerprint(root):
        res.stale = True
        res.warnings.append(
            "plan.yaml changed after this proposal was drafted (`based_on` doesn't match). Re-run /lanes-plan, "
            "or review `lanes plan diff` carefully and accept with --force"
        )
    return res


def _check_overlaps(plan: Plan, res: CheckResult) -> None:
    for o in plan.owns_overlaps():
        if not o.why:
            res.errors.append(
                f"{o.a.id} `{o.a_glob}` and {o.b.id} `{o.b_glob}` overlap ({o.winner.id} would win). Narrow one of them, "
                "or if it's intended, explain it under `overlaps:` ({globs: [a, b], why: ...})"
            )
    res.warnings += plan.stale_overlaps()


def _ancestors(plan: Plan, task: Task) -> set[str]:
    seen: set[str] = set()
    stack = list(task.depends_on)
    while stack:
        tid = stack.pop()
        if tid in seen:
            continue
        seen.add(tid)
        dep = plan.task(tid)
        if dep:
            stack += dep.depends_on
    return seen


def _check_contracts(root: Path, plan: Plan, res: CheckResult) -> None:
    used_drafts: set[str] = set()
    for c in plan.contracts:
        impl = [t for t in plan.tasks if c.id in t.implements]
        users = [t for t in plan.tasks if c.id in t.uses]
        if not impl:
            res.errors.append(f"contract {c.id}: no task implements it (add it to the upstream task's `implements`)")
        elif len(impl) > 1:
            res.errors.append(f"contract {c.id}: implemented by {', '.join(t.id for t in impl)}; exactly one task implements a contract")
        if not users:
            res.errors.append(f"contract {c.id}: no task uses it. A contract describes an interface between tasks; drop it or add the task that uses it")
        for u in users:
            for i in impl:
                if u.id == i.id:
                    res.errors.append(f"task {u.id} both implements and uses contract {c.id}")
                elif i.rank >= u.rank:
                    res.errors.append(
                        f"task {u.id} (rank {u.rank}) uses contract {c.id}, implemented by {i.id} (rank {i.rank}); "
                        "the implementer is upstream, so it needs the lower rank"
                    )
                elif i.id not in _ancestors(plan, u):
                    res.warnings.append(f"task {u.id} uses contract {c.id} from {i.id} but doesn't depend on it; add {i.id} to its `depends_on`")
        if not c.file.startswith(CONTRACTS_DIR + "/"):
            res.errors.append(f"contract {c.id}: `file` must be under {CONTRACTS_DIR}/ (got {c.file})")
            continue
        name = PurePosixPath(c.file).name
        final, draft = (root / c.file).is_file(), (root / DRAFT_CONTRACTS / name).is_file()
        if draft:
            used_drafts.add(name)
        if final and draft:
            res.errors.append(
                f"contract {c.id}: a draft at {DRAFT_CONTRACTS}/{name} would replace the existing {c.file}. "
                "Reuse the existing contract (delete the draft), or give the new one its own id and file"
            )
        elif not final and not draft:
            res.errors.append(f"contract {c.id}: {c.file} doesn't exist; write its draft at {DRAFT_CONTRACTS}/{name}")
    drafts_dir = root / DRAFT_CONTRACTS
    if drafts_dir.is_dir():
        for f in sorted(drafts_dir.iterdir()):
            if f.is_file() and f.name not in used_drafts and not f.name.startswith("."):
                res.warnings.append(f"{DRAFT_CONTRACTS}/{f.name} isn't used by any contract in the proposal")


_WILD = re.compile(r"\*\*|\*|\?")


def _sample(glob: str) -> str:
    """A concrete path a glob matches, for globs that match no existing file ("src/new/**" -> "src/new/x")."""
    return _WILD.sub("x", to_posix(glob).rstrip("/") + ("/x" if glob.endswith("/") else ""))


def _check_touches(root: Path, plan: Plan, touches: tuple[str, ...], files: list[str], res: CheckResult) -> None:
    if not touches:
        res.warnings.append("`proposal.touches` is empty, so Lanes can't check that every file the work touches has an owner")
        return
    unowned: list[str] = []
    for entry in touches:
        if entry.startswith(".lanes/"):
            continue
        if _WILD.search(entry) or (root / entry).is_dir():
            matched = [f for f in files if glob_match(entry, f)] or [_sample(entry)]
        else:
            matched = [entry]
        unowned += [f for f in matched if plan.owner_of(f).kind == "unowned"]
    if unowned:
        res.errors.append(f"{len(unowned)} path(s) the work touches have no owner: {_group(sorted(set(unowned)))}")


def _check_hubs(plan: Plan, res: CheckResult) -> None:
    for h in plan.hub_files:
        for t in plan.tasks:
            if t.owner != h.owner and any(globs_overlap(h.path, g) for g in t.owns):
                res.warnings.append(
                    f"hub file `{h.path}` (owner {h.owner}) is inside {t.id}'s `owns` ({t.owner}); the hub owner wins, so {t.owner} can't edit it"
                )


_TEAM_LINE = re.compile(r"^\s*[-*]\s+\**([A-Za-z0-9][A-Za-z0-9_.-]*)\**\s*:")


def plan_md_members(root: Path) -> list[str]:
    """Member ids named in PLAN.md's `## Team` section (`- id: ...` lines)."""
    try:
        text = (root / PLAN_MD).read_text(encoding="utf-8")
    except OSError:
        return []
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    names: list[str] = []
    in_team = False
    for line in text.splitlines():
        if line.startswith("#"):
            in_team = line.lstrip("#").strip().lower() == "team"
            continue
        m = _TEAM_LINE.match(line) if in_team else None
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def _check_members(root: Path, plan: Plan, res: CheckResult) -> None:
    ids = {m.id for m in plan.members}
    for name in plan_md_members(root):
        if name not in ids:
            res.warnings.append(f"PLAN.md's Team section names {name!r}, who isn't a member in the proposal")
    for m in plan.members:
        if not plan.tasks_of(m.id):
            res.warnings.append(f"member {m.id} has no task in the proposal")


def _group(paths: list[str]) -> str:
    """Compact list of paths: directories with a count, at most MAX_LIST entries."""
    by_dir: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        parent = str(PurePosixPath(p).parent)
        by_dir["" if parent == "." else parent].append(p)
    parts: list[str] = []
    for d, items in sorted(by_dir.items()):
        parts += items if len(items) <= 3 else [f"{d or '(repo root)'}/ ({len(items)} files)"]
    more = len(parts) - MAX_LIST
    return ", ".join(parts[:MAX_LIST]) + (f", and {more} more" if more > 0 else "")


# ---- diff ------------------------------------------------------------------------------


def describe_owner(own: Ownership) -> str:
    if own.kind == "task" and own.task:
        return f"{own.task.id} ({own.owner})"
    if own.kind == "hub":
        return f"hub file ({own.owner})"
    if own.kind == "contract" and own.contract:
        return f"contract {own.contract.id} ({own.owner})"
    if own.kind == "plan":
        return f"plan owner ({own.owner})"
    return own.kind


def diff_proposal(root: Path) -> list[str]:
    """Readable lines describing what accepting the proposal would change."""
    prop = load_proposal(root)
    old, new = current_plan(root), prop.plan
    out: list[str] = []

    def section(title: str, lines: list[str]) -> None:
        if lines:
            out.append(f"{title}:")
            out.extend(f"  {ln}" for ln in lines)

    if old is None:
        out.append(f"{PLAN_FILE} is missing or invalid, so everything below is new.")
    if old is None or old.owner != new.owner:
        section("Plan owner", [f"{old.owner if old else '-'} -> {new.owner}"])
    if old is None or old.feature != new.feature:
        section("Feature", [f"{old.feature if old else '-'} -> {new.feature}"])

    old_m = {m.id: m for m in (old.members if old else [])}
    new_m = {m.id: m for m in new.members}
    section("Members", [f"+ {i} ({new_m[i].email or 'no email'})" for i in new_m if i not in old_m]
            + [f"- {i}" for i in old_m if i not in new_m]
            + [f"~ {i} email: {old_m[i].email} -> {new_m[i].email}" for i in new_m if i in old_m and old_m[i].email != new_m[i].email])

    old_h = {h.path: h.owner for h in (old.hub_files if old else [])}
    new_h = {h.path: h.owner for h in new.hub_files}
    section("Hub files", [f"+ {p} ({o})" for p, o in new_h.items() if p not in old_h]
            + [f"- {p} (was {o})" for p, o in old_h.items() if p not in new_h]
            + [f"~ {p} owner: {old_h[p]} -> {o}" for p, o in new_h.items() if p in old_h and old_h[p] != o])

    old_c = {c.id: c for c in (old.contracts if old else [])}
    lines = []
    for c in new.contracts:
        draft = (root / DRAFT_CONTRACTS / PurePosixPath(c.file).name).is_file()
        if c.id not in old_c:
            lines.append(f"+ {c.id} (owner {c.owner}, {c.file}{', new draft' if draft else ', existing file'})")
        else:
            was = old_c[c.id]
            if was.owner != c.owner:
                lines.append(f"~ {c.id} owner: {was.owner} -> {c.owner}")
            if was.file != c.file:
                lines.append(f"~ {c.id} file: {was.file} -> {c.file}")
    lines += [f"- {cid}" for cid in old_c if new.contract(cid) is None]
    section("Contracts", lines)

    section("Tasks", _task_changes(old, new))

    old_o = {frozenset(o.globs): o for o in (old.overlaps if old else [])}
    new_o = {frozenset(o.globs): o for o in new.overlaps}
    section("Intended overlaps", [f"+ {' and '.join(o.globs)}: {o.why}" for k, o in new_o.items() if k not in old_o]
            + [f"- {' and '.join(o.globs)}" for k, o in old_o.items() if k not in new_o])

    section("What moves (files whose owner changes)", _moves(root, old, new, prop.touches))

    if old is not None:
        from .plandiff import diff_plans

        change = diff_plans(old, new, old.owner)
        if change.members:
            out.append(f"Accepting sends a plan notice to: {', '.join(change.members)}.")
    return out or ["No changes: the proposal matches plan.yaml."]


def _task_changes(old: Plan | None, new: Plan) -> list[str]:
    from .plandiff import _task_lines

    lines: list[str] = []
    ids = [t.id for t in (old.tasks_by_rank() if old else [])] + [t.id for t in new.tasks_by_rank()]
    for tid in dict.fromkeys(ids):
        before, after = old.task(tid) if old else None, new.task(tid)
        lines += _task_lines(before, after)
        if before and after:
            if before.title != after.title:
                lines.append(f"~ {tid} title: {before.title!r} -> {after.title!r}")
            if set(before.depends_on) != set(after.depends_on):
                lines.append(f"~ {tid} depends_on: {', '.join(before.depends_on) or '-'} -> {', '.join(after.depends_on) or '-'}")
            if before.status != after.status:
                lines.append(f"  ({tid} keeps its current status, {before.status}; statuses belong to task owners)")
    return lines


def _moves(root: Path, old: Plan | None, new: Plan, touches: tuple[str, ...]) -> list[str]:
    paths = set(f for f in gitutil.tracked_files(root) if not f.startswith(".lanes/"))
    paths |= {t for t in touches if not _WILD.search(t) and not t.startswith(".lanes/") and not (root / t).is_dir()}
    moved: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in sorted(paths):
        before = describe_owner(old.owner_of(p)) if old else "unowned"
        after = describe_owner(new.owner_of(p))
        if before != after:
            moved[(before, after)].append(p)
    return [f"{a} -> {b}: {_group(ps)}" for (a, b), ps in sorted(moved.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


# ---- accept ----------------------------------------------------------------------------


@dataclass
class AcceptResult:
    plan: Plan
    moved_contracts: list[str]
    notice: Any  # lanes.notices.Notice | None
    warnings: list[str]


def plan_owner_for_accept(root: Path) -> str | None:
    """The committed plan's owner (so nobody can promote themselves first), else the current plan's."""
    from .plandiff import committed_plan

    committed, _ = committed_plan(root)
    cur = committed or current_plan(root)
    return cur.owner if cur else None


def accept_proposal(root: Path, member: str, force: bool = False, session: str | None = None) -> AcceptResult:
    owner = plan_owner_for_accept(root)
    if owner is not None and member != owner:
        raise ValueError(f"only the plan owner ({owner}) can accept a proposal; you are {member}")
    res = check_proposal(root)
    if not res.ok:
        raise ValueError("the proposal has problems; fix them first (`lanes plan check`):\n  - " + "\n  - ".join(res.errors))
    if res.stale and not force:
        raise ValueError("plan.yaml changed after this proposal was drafted. Re-run /lanes-plan, or check `lanes plan diff` and use --force")
    prop = res.proposal
    assert prop is not None
    old = current_plan(root)

    expected = {k: v for k, v in prop.data.items() if k != "proposal"}
    expected["updated"] = date.today()
    text = _strip_top_level_key(prop.text, "proposal")
    text = _set_top_level(text, "updated", date.today().isoformat(), after="feature")
    from .taskstatus import replace_status

    for t in expected.get("tasks") or []:
        before = old.task(t["id"]) if old else None
        status = before.status if before else t.get("status", "todo")
        t["status"] = status
        text = replace_status(text, t["id"], status) or text
    if yaml.safe_load(text) != expected:  # unusual layout: fall back to a clean dump
        text = "# Lanes plan, accepted from a /lanes-plan proposal. Spec: docs/PLAN_FORMAT.md\n" + yaml.safe_dump(expected, sort_keys=False, allow_unicode=True)
    new_plan = parse_plan(yaml.safe_load(text), root)

    moved: list[str] = []
    for c in new_plan.contracts:
        draft = root / DRAFT_CONTRACTS / PurePosixPath(c.file).name
        if draft.is_file():
            target = root / c.file
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(draft, target)
            moved.append(c.file)
    (root / PLAN_FILE).write_text(text, encoding="utf-8", newline="\n")
    (root / PROPOSAL_FILE).unlink(missing_ok=True)
    _remove_empty_dirs(root / PROPOSAL_DIR)

    from .plandiff import record_plan_change

    notice, _ = record_plan_change(root, new_plan, member, session=session, require_owner=False)
    leftovers = [w for w in res.warnings if "isn't used by any contract" in w]
    return AcceptResult(new_plan, moved, notice, leftovers)


def _strip_top_level_key(text: str, key: str) -> str:
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}:", ln)), None)
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0] in " \t"):
        end += 1
    return "".join(lines[:start] + lines[end:])


def _set_top_level(text: str, key: str, value: str, after: str) -> str:
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:", ln):
            lines[i] = f"{key}: {value}\n"
            return "".join(lines)
    at = next((i + 1 for i, ln in enumerate(lines) if re.match(rf"^{re.escape(after)}:", ln)), 0)
    lines.insert(at, f"{key}: {value}\n")
    return "".join(lines)


def _remove_empty_dirs(path: Path) -> None:
    if not path.is_dir():
        return
    for d in sorted((p for p in path.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        for junk in d.glob(".gitkeep"):
            junk.unlink()
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass
