"""`lanes` command-line interface (argparse keeps startup fast for hooks)."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

EXIT_OK, EXIT_ERROR, EXIT_OUT_OF_LANE = 0, 1, 2  # `sync` also returns 3: code commits held back

HOOK_MODULES = {
    "session-start": "session_start",
    "pre-tool-guard": "pre_tool_guard",
    "post-tool-notice": "post_tool_notice",
    "stop-summary": "stop_summary",
    "pre-commit": "pre_commit",
}


class CliError(Exception):
    pass


@dataclass
class Ctx:
    root: Path
    plan: object  # lanes.plan.Plan
    member: str | None
    identity_detail: str


def load_ctx(need_member: bool = True) -> Ctx:
    from .identity import resolve
    from .paths import find_root
    from .plan import PlanError, load_plan

    root = find_root()
    if root is None:
        raise CliError("no .lanes/ directory found here or in any parent. Run `lanes init` at the repo root first.")
    try:
        plan = load_plan(root)
    except PlanError as exc:
        raise CliError("invalid .lanes/plan.yaml:\n  - " + "\n  - ".join(exc.errors)) from exc
    ident = resolve(plan, root)
    if need_member and ident.member_id is None:
        raise CliError(ident.detail)
    return Ctx(root, plan, ident.member_id, ident.detail)


def to_rel(ctx: Ctx, path: str) -> str | None:
    from .paths import is_absolute, repo_relative

    absolute = path if is_absolute(path) else os.path.join(os.getcwd(), path)
    return repo_relative(absolute, ctx.root)


# ---- commands ------------------------------------------------------------------------


def cmd_init(args) -> int:
    from . import gitutil
    from .install import init_repo

    root = gitutil.toplevel(Path.cwd()) or Path.cwd()
    report = init_repo(root, member=args.member, email=args.email, force_plan=args.force, git_hook=not args.no_git_hook)
    print(f"Lanes initialized in {root}")
    for label, items in (("created", report.created), ("updated", report.updated), ("unchanged", report.unchanged)):
        for item in items:
            print(f"  {label:9} {item}")
    for w in report.warnings:
        print(f"  warning   {w}")
    print(
        "\nNext:\n"
        "  1. Edit .lanes/plan.yaml: real members, tasks, owned globs, contracts.\n"
        "  2. Each teammate sets LANES_USER to their member id (see docs/SETUP.md).\n"
        "  3. Commit and push .lanes/, CLAUDE.md, AGENTS.md and .claude/. After that, `lanes sync` shares .lanes/.\n"
        "  4. Start a new Claude Code session; the Lanes briefing appears at the top."
    )
    return EXIT_OK


def cmd_whoami(args) -> int:
    ctx = load_ctx()
    plan = ctx.plan
    print(f"You are: {ctx.member} ({ctx.identity_detail})")
    tasks = plan.tasks_of(ctx.member)
    if not tasks:
        print("You have no tasks in the plan.")
    for t in tasks:
        print(f"\n{t.id} [rank {t.rank}, {t.status}] {t.title}")
        print(f"  owns:       {', '.join(t.owns) or '-'}")
        print(f"  implements: {', '.join(t.implements) or '-'}")
        print(f"  uses:       {', '.join(t.uses) or '-'}")
        print(f"  depends on: {', '.join(t.depends_on) or '-'}")
    hubs = [h.path for h in plan.hub_files if h.owner == ctx.member]
    contracts = [f"{c.id} ({c.file})" for c in plan.contracts if c.owner == ctx.member]
    if hubs:
        print(f"\nHub files you own: {', '.join(hubs)}")
    if contracts:
        print(f"Contracts you own: {', '.join(contracts)}")
    return EXIT_OK


def cmd_status(args) -> int:
    from . import gitutil
    from .lane import check_lane
    from .notices import unread_for

    ctx = load_ctx(need_member=False)
    plan = ctx.plan
    print(f"Feature: {plan.feature}" + (f" (updated {plan.updated})" if plan.updated else ""))
    print(f"You: {ctx.member or 'unknown'} ({ctx.identity_detail})\n")
    rows = [("RANK", "TASK", "OWNER", "STATUS", "TITLE")]
    rows += [(str(t.rank), t.id, t.owner, t.status, t.title) for t in plan.tasks_by_rank()]
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r[:4])) + "  " + r[4])

    counts = [f"{m.id} {len(unread_for(ctx.root, plan, m.id))}" for m in plan.members]
    print(f"\nUnread notices: {' · '.join(counts)}")
    from .notices import unreadable_notices

    broken = unreadable_notices(ctx.root)
    if broken:
        print(f"Warning: {len(broken)} notice file(s) could not be read (fix the front matter): {', '.join(broken)}")

    if ctx.member:
        outside = []
        for rel in gitutil.dirty_paths(ctx.root):
            d = check_lane(plan, ctx.member, rel)
            if not d.allowed:
                outside.append(f"{rel} ({'owned by ' + d.ownership.owner if d.ownership.owner else 'unowned'})")
        if outside:
            print("\nWarning: uncommitted changes outside your lane:")
            for line in outside:
                print(f"  {line}")
            print("  Ask the owner (`lanes request --file <path> ...`) or move the change to your lane.")
    return EXIT_OK


def cmd_check(args) -> int:
    from . import gitutil
    from .lane import check_lane

    ctx = load_ctx()
    if args.staged:
        paths = gitutil.staged_paths(ctx.root)
        rels = paths
    else:
        if not args.paths:
            raise CliError("give one or more paths, or --staged")
        rels = []
        for p in args.paths:
            rel = to_rel(ctx, p)
            if rel is None:
                print(f"skip  {p}: outside the repo")
                continue
            rels.append(rel)
    worst = EXIT_OK
    for rel in rels:
        d = check_lane(ctx.plan, ctx.member, rel)
        if d.allowed:
            if not args.quiet:
                print(f"ok    {rel}: {d.reason}")
        else:
            worst = EXIT_OUT_OF_LANE
            if args.quiet:
                print(d.reason)
            else:
                print(f"BLOCK {rel}")
                print("\n".join("      " + line for line in d.reason.splitlines()))
    return worst


def cmd_notices(args) -> int:
    from .notices import addressed_to, amend, list_notices, mark_read, read_ids, unread_for

    ctx = load_ctx()
    if args.action == "amend":
        if not args.notice_id:
            raise CliError('usage: lanes notices amend ID --summary "..." [--body "..."]')
        try:
            n = amend(ctx.root, ctx.member, args.notice_id, summary=args.summary, body=args.body)
        except ValueError as exc:
            raise CliError(str(exc)) from exc
        print(f"Amended {n.path.relative_to(ctx.root).as_posix()}\n  summary: {n.summary}")
        for line in n.body.splitlines():
            print(f"    {line}")
        return EXIT_OK
    if args.summary or args.body or args.notice_id:
        raise CliError("--summary/--body only work with `lanes notices amend ID`")
    if args.all:
        seen = read_ids(ctx.root, ctx.member)
        shown = [n for n in list_notices(ctx.root) if addressed_to(n, ctx.plan, ctx.member)]
    else:
        seen = set()
        shown = unread_for(ctx.root, ctx.plan, ctx.member)

    if args.mark_read is not None:
        ids = args.mark_read or [n.id for n in shown]
        n = mark_read(ctx.root, ctx.member, ids)
        print(f"Marked {n} notice(s) read for {ctx.member}. Run `lanes sync` to share it.")
        return EXIT_OK

    if not shown:
        print(f"No {'' if args.all else 'unread '}notices for {ctx.member}.")
        return EXIT_OK
    for n in shown:
        flag = "  " if n.id in seen else "* "
        origin = f"{n.from_task or '-'}/{n.from_member} (rank {n.from_rank})"
        print(f"{flag}{n.id}\n  {n.kind} from {origin} → {', '.join(n.to_tasks) or ', '.join(n.to_members)} · {n.topic}")
        print(f"  {n.summary}")
        for line in n.body.splitlines():
            print(f"    {line}")
    print(f"\nAfter acting on these: lanes notices --mark-read")
    return EXIT_OK


def cmd_request(args) -> int:
    from .notices import make_request

    ctx = load_ctx()
    rel = to_rel(ctx, args.file) if args.file else None
    if args.file and rel is None:
        raise CliError(f"{args.file} is outside the repo")
    try:
        notice = make_request(ctx.root, ctx.plan, ctx.member, args.message, rel=rel, to_member=args.to)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    print(f"Request written: {notice.path.relative_to(ctx.root).as_posix()} (to {', '.join(notice.to_members)})")
    print("Run `lanes sync` so the owner sees it in their next session.")
    return EXIT_OK


def cmd_handoff(args) -> int:
    from . import gitutil
    from .install import render

    ctx = load_ctx()
    plan = ctx.plan
    task = plan.task(args.task) if args.task else None
    if args.task and task is None:
        raise CliError(f"unknown task {args.task!r}")
    if task is None:
        mine = plan.tasks_of(ctx.member)
        active = [t for t in mine if t.status == "in_progress"] or [t for t in mine if t.status != "done"] or mine
        if not active:
            raise CliError("you have no tasks; pass --task <id>")
        task = active[0]
    now = datetime.now(timezone.utc)
    files = [p for p in gitutil.dirty_paths(ctx.root) if not p.startswith(".lanes/")]
    text = render(
        "handoff.md",
        task=task.id,
        title=task.title,
        member=ctx.member,
        created=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        branch=gitutil.branch(ctx.root) or "-",
        files="\n".join(f"- {f}" for f in files[:20]) or "- (no uncommitted changes)",
    )
    path = ctx.root / ".lanes" / "handoffs" / f"{task.id}-{now.strftime('%Y%m%dT%H%M%SZ')}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(path.relative_to(ctx.root).as_posix())
    return EXIT_OK


def cmd_sync(args) -> int:
    from .sync import sync

    ctx = load_ctx()
    result = sync(ctx.root, ctx.plan, ctx.member, include_code=args.include_code)
    print("\n".join(result.lines), file=sys.stderr if result.code == EXIT_ERROR else sys.stdout)
    return result.code


def cmd_hook(args) -> int:
    module = importlib.import_module(f"lanes.hooks.{HOOK_MODULES[args.name]}")
    return module.main()


# ---- parser ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lanes", description="Shared plan, separate lanes.")
    p.add_argument("--version", action="version", version=f"lanes {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="set up .lanes/, agent instructions, Claude Code hooks and the git hook")
    s.add_argument("--member", help="your member id for the example plan (default: LANES_USER or git email)")
    s.add_argument("--email", help="your email for the example plan (default: git user.email)")
    s.add_argument("--force", action="store_true", help="overwrite an existing .lanes/plan.yaml with the example")
    s.add_argument("--no-git-hook", action="store_true", help="don't install the git pre-commit lane check")
    s.set_defaults(func=cmd_init)

    sub.add_parser("whoami", help="your member id, tasks and owned globs").set_defaults(func=cmd_whoami)
    sub.add_parser("status", help="tasks, owners, status and unread notices per person").set_defaults(func=cmd_status)

    s = sub.add_parser("check", help="exit 0 if PATH is in your lane, 2 if not")
    s.add_argument("paths", nargs="*", metavar="PATH")
    s.add_argument("--staged", action="store_true", help="check every staged file (used by the git hook)")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("notices", help="list unread notices addressed to you, or amend one you wrote")
    s.add_argument("action", nargs="?", choices=["amend"], help="amend ID: rewrite your own unread notice")
    s.add_argument("notice_id", nargs="?", metavar="ID", help=argparse.SUPPRESS)
    s.add_argument("--summary", help="amend: the new one-sentence summary")
    s.add_argument("--body", help="amend: the new body, 3-6 lines (\\n separates lines)")
    s.add_argument("--all", action="store_true", help="include notices you've already read")
    s.add_argument("--mark-read", nargs="*", metavar="ID", help="mark the listed (or given) notices read")
    s.set_defaults(func=cmd_notices)

    s = sub.add_parser("request", help="ask the owner of a file (or a member) for a change")
    target = s.add_mutually_exclusive_group(required=True)
    target.add_argument("--file", help="the out-of-lane path you need changed")
    target.add_argument("--to", help="member id to ask directly")
    s.add_argument("message", help="what you need and why (first line becomes the summary)")
    s.set_defaults(func=cmd_request)

    s = sub.add_parser("handoff", help="create a handoff note for your task and print its path")
    s.add_argument("--task", help="task id (default: your in-progress task)")
    s.add_argument("task_pos", nargs="?", metavar="TASK", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_handoff)

    s = sub.add_parser(
        "sync",
        help="share .lanes/ with teammates: commit .lanes/ only, pull --rebase --autostash, push",
        description="Commit .lanes/ only, then `git pull --rebase --autostash`, then push. If any unpushed "
        "commit contains code, it lists them and stops (exit 3) unless --include-code.",
    )
    s.add_argument("--include-code", action="store_true", help="also push unpushed commits that contain code")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("hook", help="run a hook (called by Claude Code / git, not by hand)")
    s.add_argument("name", choices=sorted(HOOK_MODULES))
    s.set_defaults(func=cmd_hook)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "task_pos", None) and not args.task:
        args.task = args.task_pos
    try:
        return args.func(args)
    except CliError as exc:
        print(f"lanes: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
