"""SessionStart hook: inject a compact Lanes briefing into Claude's context.

Contents: feature, my tasks + owned globs + contracts, teammates' active tasks,
unread notices for me, the latest handoff for my tasks, and the last 24h of
session summaries. Capped at ~1,500 tokens; the oldest items are dropped first.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import gitutil
from ..notices import unread_for
from ..paths import PROPOSAL_FILE
from ..plan import Plan
from ..runner import lanes_cmd
from ..summaries import read_sections
from .adapters import HookInput, add_context
from .common import is_shared_lanes_state, load_ctx, load_state, run_hook, save_state

CAP_CHARS = 6000  # ~1,500 tokens at ~4 chars/token (Claude Code's own cap is 10,000 chars)
HANDOFFS_DIR = Path(".lanes") / "handoffs"
_HANDOFF_NAME = re.compile(r"^(?P<task>.+)-(?P<ts>\d{8}T\d{4,6}Z)\.md$")


def main() -> int:
    return run_hook(handle)


def handle(inp: HookInput) -> int:
    ctx = load_ctx(inp)
    if ctx is None:
        return 0
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if ctx.plan is None:
        text = (
            "# Lanes briefing\n"
            f"WARNING: .lanes/plan.yaml is invalid, so the Lanes lane guard is OFF (fail-open): {ctx.plan_error}\n"
            "Tell the user before making changes, and don't edit other people's work."
        )
        add_context("SessionStart", text, system_message=f"Lanes: plan.yaml is invalid, lane guard OFF. {ctx.plan_error}", agent=inp.agent)
        return 0

    _start_session_state(ctx.root, inp, now)
    text, stats = build_briefing(ctx.root, ctx.plan, ctx.member, ctx.identity_detail, now, exclude_session=inp.session_id)
    if ctx.member:
        tasks = ", ".join(t.id for t in ctx.plan.tasks_of(ctx.member)) or "no tasks"
        msg = f"Lanes: briefing loaded for {ctx.member} ({tasks}); {stats['notices']} unread notice(s)."
    else:
        msg = f"Lanes: can't tell who you are, so the lane guard is OFF. {ctx.identity_detail}"
    add_context("SessionStart", text, system_message=msg, agent=inp.agent)
    return 0


def _start_session_state(root: Path, inp: HookInput, now: datetime) -> None:
    """Remember which files were already dirty, so Stop can tell what this session touched."""
    state = load_state(root, inp.session_id)
    if state and inp.source in ("resume", "compact"):
        return
    dirty = [p for p in gitutil.dirty_paths(root) if not is_shared_lanes_state(p)]
    save_state(root, inp.session_id, {"started": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "dirty_at_start": dirty, "touched": []})


# ---- briefing ---------------------------------------------------------------------------


def build_briefing(
    root: Path,
    plan: Plan,
    member: str | None,
    identity_detail: str,
    now: datetime,
    exclude_session: str | None = None,
    cap: int = CAP_CHARS,
) -> tuple[str, dict]:
    L = lanes_cmd(root)
    fixed = _fixed_part(plan, member, identity_detail, L)
    if (root / PROPOSAL_FILE).is_file():
        who = "You are the plan owner: review" if member == plan.owner else f"The plan owner ({plan.owner}) reviews"
        fixed += f"\nA plan proposal is waiting in {PROPOSAL_FILE}. {who} it with `{L} plan diff`, then `{L} plan accept`.\n"

    # Optional, time-stamped items: (timestamp, section, text). Newest are kept first.
    items: list[tuple[datetime, str, str]] = []
    notices = unread_for(root, plan, member) if member else []
    for n in notices:
        ts = _parse_iso(n.created) or now
        body = "\n".join(f"    {ln}" for ln in n.body.splitlines()[:6])
        items.append((ts, "notices", f"- [{n.id}] {n.kind} from {n.from_task or '-'}/{n.from_member} (rank {n.from_rank}) about {n.topic}: {n.summary}" + (f"\n{body}" if body else "")))
    handoff = _latest_handoff(root, plan, member) if member else None
    if handoff:
        items.append(handoff)
    cutoff = now - timedelta(hours=24)
    for s in read_sections(root):
        if s.updated >= cutoff and s.session_id != exclude_session:
            items.append((s.updated, "summaries", "\n".join(s.lines[:5]).replace("## ", "- ", 1)))

    footer = (
        f"\nAfter acting on notices, run `{L} notices --mark-read`. Notices, summaries and handoffs reach teammates "
        f"only through git: when you finish, suggest your human run `{L} sync` (commits .lanes/ only, pulls, pushes). "
        f"Run `{L} status` any time to see who owns what."
    )
    budget = cap - len(fixed) - len(footer) - 200
    kept: list[tuple[datetime, str, str]] = []
    used = 0
    for item in sorted(items, key=lambda x: x[0], reverse=True):
        cost = len(item[2]) + 1
        if used + cost <= budget:
            kept.append(item)
            used += cost
    omitted = len(items) - len(kept)

    titles = {
        "notices": f"## Unread notices for you ({len(notices)})",
        "handoff": "## Latest handoff for your task",
        "summaries": "## Recent session summaries (last 24h)",
    }
    parts = [fixed]
    for section in ("notices", "handoff", "summaries"):
        chosen = [i for i in kept if i[1] == section]
        if chosen:
            parts.append(titles[section])
            # notices newest-first; summaries oldest-first so they read as a timeline
            ordered = sorted(chosen, key=lambda x: x[0], reverse=(section == "notices"))
            parts.extend(i[2] for i in ordered)
    if omitted:
        parts.append(f"({omitted} older item(s) omitted to stay short. See `{L} notices` and .lanes/summaries/.)")
    text = "\n".join(parts) + footer
    return text[:cap], {"notices": len(notices), "omitted": omitted}


def _fixed_part(plan: Plan, member: str | None, identity_detail: str, L: str = "lanes") -> str:
    lines = [f"# Lanes briefing · feature: {plan.feature}"]
    if member is None:
        lines += [
            f"WARNING: Lanes can't tell who you are ({identity_detail}).",
            f"The lane guard is OFF until this is fixed. Tell the user, and don't edit files without checking `{L} status`.",
        ]
    else:
        lines.append(f"You are **{member}** ({identity_detail}). Stay inside your lane (see 'Working with Lanes' in CLAUDE.md).")
        lines.append("\n## Your lane")
        mine = plan.tasks_of(member)
        if not mine:
            lines.append("- You have no tasks in the plan.")
        for t in mine:
            lines.append(f"- {t.id} [rank {t.rank}, {t.status}] {t.title}")
            lines.append(f"  owns: {', '.join(t.owns) or '-'}")
            impl = ", ".join(f"{c} ({plan.contract(c).file})" for c in t.implements if plan.contract(c)) or "-"
            uses = ", ".join(f"{c} ({plan.contract(c).file})" for c in t.uses if plan.contract(c)) or "-"
            lines.append(f"  implements: {impl} · uses: {uses}")
            if t.depends_on:
                lines.append(f"  depends on: {', '.join(t.depends_on)}")
        hubs = [h.path for h in plan.hub_files if h.owner == member]
        if hubs:
            lines.append(f"- Hub files you own: {', '.join(hubs)}")
        lines.append(f'Need a change outside these paths? Run `{L} request --file <path> "<what and why>"`; don\'t edit it.')

    others = [t for t in plan.tasks_by_rank() if t.owner != member and t.status != "done"]
    if others:
        lines.append("\n## Teammates")
        for t in others:
            owns = ", ".join(t.owns[:2]) + (", ..." if len(t.owns) > 2 else "")
            lines.append(f"- {t.owner}: {t.id} [rank {t.rank}, {t.status}] {t.title} (owns {owns or '-'})")
    return "\n".join(lines) + "\n"


def _latest_handoff(root: Path, plan: Plan, member: str) -> tuple[datetime, str, str] | None:
    folder = root / HANDOFFS_DIR
    if not folder.is_dir():
        return None
    my_tasks = {t.id for t in plan.tasks_of(member)}
    best: tuple[datetime, Path] | None = None
    for path in folder.glob("*.md"):
        m = _HANDOFF_NAME.match(path.name)
        if not m or m.group("task") not in my_tasks:
            continue
        ts_text = m.group("ts")
        fmt = "%Y%m%dT%H%M%SZ" if len(ts_text) == 16 else "%Y%m%dT%H%MZ"
        try:
            ts = datetime.strptime(ts_text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if best is None or ts > best[0]:
            best = (ts, path)
    if best is None:
        return None
    text = best[1].read_text(encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = [ln for ln in text.splitlines() if ln.strip()][:15]
    rel = best[1].relative_to(root).as_posix()
    return best[0], "handoff", f"({rel})\n" + "\n".join(lines)


def _parse_iso(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
