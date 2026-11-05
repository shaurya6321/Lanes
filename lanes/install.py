"""`lanes init`: set up a repo to use Lanes. Every step is idempotent and never clobbers user content."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path
from string import Template

from . import gitutil
from .runner import DEV, GLOBAL, LOCAL, RUNNERS, prefix_for

HOOK_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
# (event, matcher or None, hook name, module file, timeout seconds)
HOOKS = [
    ("SessionStart", None, "session-start", "session_start.py", 15),
    ("PreToolUse", HOOK_MATCHER, "pre-tool-guard", "pre_tool_guard.py", 10),
    ("PostToolUse", HOOK_MATCHER, "post-tool-notice", "post_tool_notice.py", 10),
    ("Stop", None, "stop-summary", "stop_summary.py", 15),
]
BLOCK_BEGIN = "<!-- lanes:begin"
BLOCK_END = "<!-- lanes:end -->"
GIT_HOOK_MARKER = "# lanes:pre-commit"

AGENT_HINTS = {
    "claude": {
        "briefing_hint": "Lanes adds it to your context automatically when the session starts. If you don't see it, run `$lanes status` and `$lanes notices`.",
        "handoff_hint": "To hand off to whoever continues, run `/lanes-handoff`.",
    },
    "codex": {
        "briefing_hint": "Run `$lanes status` and `$lanes notices` at the start of every session. Automatic briefings for Codex come in Phase 1.",
        "handoff_hint": "To hand off, run `$lanes handoff` and fill in the file it creates.",
    },
}

GIT_HOOK = f"""#!/bin/sh
{GIT_HOOK_MARKER} (installed by `lanes init`): blocks commits that touch files outside your lane.
# Bypass once with: git commit --no-verify
if command -v lanes >/dev/null 2>&1; then
  exec lanes hook pre-commit
elif command -v uv >/dev/null 2>&1 && [ -f hooks/pre_commit.py ]; then
  exec uv run --quiet python hooks/pre_commit.py
else
  echo "lanes: 'lanes' is not on PATH, so the lane check was skipped (see docs/SETUP.md)" >&2
  exit 0
fi
"""

# Repo-only installs (`lanes init --local`): Lanes is a dev dependency, run through uv.
# The `--version` probe keeps the hook fail-open when the env isn't synced yet: a
# missing `lanes` must skip the check, not block the commit.
GIT_HOOK_LOCAL = f"""#!/bin/sh
{GIT_HOOK_MARKER} (installed by `uv run lanes init --local`): blocks commits that touch files outside your lane.
# Bypass once with: git commit --no-verify
top="$(git rev-parse --show-toplevel)"
if command -v uv >/dev/null 2>&1 && uv run --quiet --project "$top" lanes --version >/dev/null 2>&1; then
  exec uv run --quiet --project "$top" lanes hook pre-commit
elif command -v lanes >/dev/null 2>&1; then
  exec lanes hook pre-commit
else
  echo "lanes: can't run Lanes (run 'uv sync' first), so the lane check was skipped" >&2
  exit 0
fi
"""


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    runner: str = GLOBAL

    def add(self, status: str, what: str) -> None:
        {"created": self.created, "updated": self.updated}.get(status, self.unchanged).append(what)


def template(name: str) -> str:
    return resources.files("lanes").joinpath("templates", *name.split("/")).read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    return Template(template(name)).safe_substitute(values)


def _write_new(path: Path, text: str, report: Report, rel: str, force: bool = False) -> None:
    if path.exists() and not force:
        report.add("unchanged", rel)
        return
    status = "updated" if path.exists() else "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    report.add(status, rel)


# ---- agent instruction files ---------------------------------------------------------


def agent_block(agent: str, runner: str = GLOBAL) -> str:
    hints = {k: Template(v).safe_substitute(lanes=prefix_for(runner)) for k, v in AGENT_HINTS[agent].items()}
    return render("agent_instructions.md", lanes=prefix_for(runner), **hints).strip() + "\n"


def upsert_block(path: Path, block: str) -> str:
    """Insert or replace the managed Lanes block in CLAUDE.md / AGENTS.md."""
    if not path.exists():
        path.write_text(f"# Project instructions\n\n{block}", encoding="utf-8", newline="\n")
        return "created"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)
    new = pattern.sub(lambda _m: block, text, count=1) if pattern.search(text) else text.rstrip("\n") + "\n\n" + block
    if new == text:
        return "unchanged"
    path.write_text(new, encoding="utf-8", newline="\n")
    return "updated"


# ---- Claude Code settings -------------------------------------------------------------


def hook_handler(name: str, module_file: str, timeout: int, runner: str) -> dict:
    # Exec form (`command` + `args`, no shell): Claude Code substitutes ${CLAUDE_PROJECT_DIR}
    # inside an arg and passes it as ONE argv entry, so a path with spaces needs no quoting
    # (shell quotes here would be passed literally). See docs/HOOKS_NOTES.md.
    if runner == DEV:  # only for the Lanes repo itself: run the in-repo wrappers
        cmd, args = "uv", ["run", "--quiet", "--project", "${CLAUDE_PROJECT_DIR}", "python", f"${{CLAUDE_PROJECT_DIR}}/hooks/{module_file}"]
    elif runner == LOCAL:  # Lanes is a dev dependency of the repo; nothing on PATH
        cmd, args = "uv", ["run", "--quiet", "--project", "${CLAUDE_PROJECT_DIR}", "lanes", "hook", name]
    else:
        cmd, args = "lanes", ["hook", name]
    return {"type": "command", "command": cmd, "args": args, "timeout": timeout}


def _is_ours(handler: dict, name: str, module_file: str) -> bool:
    args = handler.get("args") or []
    joined = " ".join([str(handler.get("command", "")), *map(str, args)])
    return f"hook {name}" in joined or joined.endswith(f"hooks/{module_file}")


def detect_runner(root: Path) -> str | None:
    """Which runner the repo's committed .claude/settings.json already uses (None if no Lanes hooks)."""
    try:
        settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return None
    for groups in (settings.get("hooks") or {}).values():
        for group in groups if isinstance(groups, list) else []:
            for h in group.get("hooks", []) if isinstance(group, dict) else []:
                for _event, _m, name, module_file, _t in HOOKS:
                    if isinstance(h, dict) and _is_ours(h, name, module_file):
                        args = [str(a) for a in h.get("args") or []]
                        if h.get("command") == "uv" and any(a.endswith(f"hooks/{module_file}") for a in args):
                            return DEV
                        return LOCAL if h.get("command") == "uv" else GLOBAL
    return None


def merge_settings(path: Path, runner: str = GLOBAL) -> str:
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON ({exc}); fix it and re-run `lanes init`") from exc
    else:
        settings = {}
    before = json.dumps(settings, sort_keys=True)
    hooks = settings.setdefault("hooks", {})
    for event, matcher, name, module_file, timeout in HOOKS:
        groups = hooks.setdefault(event, [])
        handler = hook_handler(name, module_file, timeout, runner)
        found = False
        for group in groups:
            for i, h in enumerate(group.get("hooks", [])):
                if _is_ours(h, name, module_file):
                    group["hooks"][i] = handler
                    found = True
        if not found:
            group = {"hooks": [handler]}
            if matcher:
                group = {"matcher": matcher, **group}
            groups.append(group)
    if json.dumps(settings, sort_keys=True) == before:
        return "unchanged"
    status = "updated" if path.exists() else "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n")
    return status


# ---- git -----------------------------------------------------------------------------


def install_git_hook(root: Path, runner: str = GLOBAL) -> tuple[str, str | None]:
    hooks_dir = gitutil.git_path(root, "hooks")
    if hooks_dir is None:
        return "skipped", "not a git repository, so the pre-commit lane check was not installed"
    path = hooks_dir / "pre-commit"
    if path.exists() and GIT_HOOK_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        return "skipped", (
            f"{path} already exists and isn't from Lanes. Add this line to it to enable the lane check: "
            "lanes hook pre-commit"
        )
    text = GIT_HOOK_LOCAL if runner == LOCAL else GIT_HOOK
    status = "unchanged" if path.exists() and path.read_text(encoding="utf-8") == text else ("updated" if path.exists() else "created")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return status, None


def ensure_line(path: Path, line: str) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if line in text.splitlines():
        return "unchanged"
    status = "updated" if path.exists() else "created"
    sep = "" if not text or text.endswith("\n") else "\n"
    path.write_text(f"{text}{sep}{line}\n", encoding="utf-8", newline="\n")
    return status


# ---- entry point -----------------------------------------------------------------------


def default_member() -> tuple[str, str | None]:
    email = gitutil.run_git(None, "config", "user.email")
    email = email.strip() if email else None
    wanted = os.environ.get("LANES_USER", "").strip()
    if not wanted and email:
        wanted = email.split("@")[0].split("+")[-1]
    member = re.sub(r"[^A-Za-z0-9_.-]", "-", wanted).strip("-.").lower() or "me"
    return member, email


def init_repo(
    root: Path,
    member: str | None = None,
    email: str | None = None,
    force_plan: bool = False,
    git_hook: bool = True,
    runner: str | None = None,
) -> Report:
    """Set up (or re-check) a repo. `runner=None` keeps whatever the repo already uses, else global."""
    report = Report()
    existing = detect_runner(root)
    if runner is None:
        runner = existing or GLOBAL
    elif runner not in RUNNERS:
        raise ValueError(f"unknown runner {runner!r}")
    elif existing and existing != runner:
        report.warnings.append(f"switching this repo's hooks from {existing!r} to {runner!r}; commit .claude/settings.json and CLAUDE.md")
    report.runner = runner
    L = prefix_for(runner)
    if member is None:
        member, email = default_member()
    lanes = root / ".lanes"
    for sub in ("contracts", "notices", "handoffs", "summaries"):
        d = lanes / sub
        d.mkdir(parents=True, exist_ok=True)
        if not any(d.iterdir()):
            (d / ".gitkeep").write_text("", encoding="utf-8")

    plan_text = render("plan.yaml", member=member, email=email or f"{member}@example.com", today=date.today().isoformat())
    _write_new(lanes / "plan.yaml", plan_text, report, ".lanes/plan.yaml", force=force_plan)
    _write_new(
        lanes / "contracts" / "example-api.md",
        render("contract.md", contract_id="example-api", owner=member, implementer="T1", users="T2"),
        report,
        ".lanes/contracts/example-api.md",
    )
    _write_new(lanes / "contracts" / "_TEMPLATE.md", template("contract.md"), report, ".lanes/contracts/_TEMPLATE.md")
    _write_new(lanes / "handoffs" / "_TEMPLATE.md", template("handoff.md"), report, ".lanes/handoffs/_TEMPLATE.md")
    _write_new(lanes / "decisions.md", template("decisions.md"), report, ".lanes/decisions.md")

    report.add(ensure_line(root / ".gitignore", ".lanes/local/"), ".gitignore (.lanes/local/)")
    report.add(ensure_line(root / ".gitattributes", ".lanes/** text eol=lf"), ".gitattributes (.lanes/** eol=lf)")

    for agent, fname in (("claude", "CLAUDE.md"), ("codex", "AGENTS.md")):
        report.add(upsert_block(root / fname, agent_block(agent, runner)), fname)

    try:
        report.add(merge_settings(root / ".claude" / "settings.json", runner), ".claude/settings.json (hooks)")
    except ValueError as exc:
        report.warnings.append(str(exc))
    for cmd in ("lanes-status.md", "lanes-handoff.md"):
        _write_new(root / ".claude" / "commands" / cmd, render(f"commands/{cmd}", lanes=L), report, f".claude/commands/{cmd}")

    if runner == LOCAL and not _declares_lanes(root / "pyproject.toml"):
        report.warnings.append(
            "pyproject.toml doesn't list Lanes as a dependency, so `uv run lanes` won't work for teammates. Add it with:\n"
            '              uv add --dev "lanes @ git+https://github.com/shaurya6321/Lanes"'
        )

    if git_hook:
        status, warning = install_git_hook(root, runner)
        if warning:
            report.warnings.append(warning)
        else:
            report.add(status, ".git/hooks/pre-commit (lane check)")
    return report


def _declares_lanes(pyproject: Path) -> bool:
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"""["']lanes\s*(@|[<>=~!\[;"']|$)""", text, re.M) is not None
