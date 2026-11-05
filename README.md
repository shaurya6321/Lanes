# Lanes

**Shared plan, separate lanes.** Lanes lets 2–6 people each run Claude Code on their own machine against the same repo, without overwriting or breaking each other's work. It works in Cursor or VS Code, on macOS or Windows. Codex support is planned.

## The 30-second version

When two people point coding agents at one repo, neither agent knows what the other is doing. Lanes gives every session the same picture:

- **One shared plan** (`.lanes/plan.yaml`). The feature is split into ranked tasks, and each task has an owner and a set of owned files (its *lane*).
- **A briefing at session start.** Claude is told who you are, what your lane is, what teammates are doing, and what changed since your last session.
- **A lane guard.** If Claude tries to edit a file outside your lane, a hook stops it and tells it who to ask instead.
- **One-way change notices.** When you change a contract or shared file you own, a short notice goes to downstream tasks only (lower rank to higher rank), so two agents never ping-pong.
- **Summaries and handoffs.** Each session leaves a 3–5 line summary, and `/lanes-handoff` writes a handoff note. The next session can continue without anyone re-explaining.

Phase 0 has no servers. Everything is files in your repo, shared through git with `lanes sync`.

## Quickstart

You need [uv](https://docs.astral.sh/uv/), git and Claude Code. Teammates on Windows also need Git for Windows. You don't need to install Python, because uv fetches it. [docs/SETUP.md](docs/SETUP.md) has the full steps for both operating systems.

**For teams, the default is repo-only.** Lanes is a dev dependency of your project, and every command is `uv run lanes ...`. Nothing is installed globally, and Lanes only runs inside this repo.

```bash
# 1. One person sets up the repo
cd path/to/your-project
uv init --bare                                    # only if the repo has no pyproject.toml yet (e.g. a JS repo)
uv add --dev "lanes @ git+https://github.com/shaurya6321/Lanes@v0.1.0"
uv run lanes init --local                         # .lanes/, CLAUDE.md, AGENTS.md, .claude/settings.json, git hook
#    then edit .lanes/plan.yaml: members (with their git emails), tasks, owned globs, contracts
git add -A && git commit -m "Set up Lanes" && git push

# 2. Each teammate, after cloning
uv sync                                           # installs Lanes into the repo's own .venv
uv run lanes init                                 # installs the commit check (git hooks aren't cloned); changes nothing else

# 3. Work as usual
uv run lanes sync          # receive teammates' notices and summaries
claude                     # the Lanes briefing appears at the top of the session
uv run lanes sync          # share yours (commits .lanes/ only; never pushes code without --include-code)
```

Lanes knows who you are from `git config user.email` in the repo, matched against `members[].email` in the plan. To override it, set `LANES_USER` to your member id.

To check it's working, run `uv run lanes whoami` (your tasks and owned files) and `uv run lanes status` (everyone's tasks and unread notices). The command tables below write `lanes ...`; in a repo-only project, type `uv run lanes ...`. Claude is given the right spelling automatically.

**Optional: global install.** If you'd rather have `lanes` on your PATH for every repo, run `uv tool install git+https://github.com/shaurya6321/Lanes` and `lanes init` without `--local`. Update with `uv tool upgrade lanes`. To develop Lanes itself, clone it and run `uv tool install --editable .`.

**https blocked?** If https to GitHub doesn't work for you but SSH does, use `git+ssh://git@github.com/shaurya6321/Lanes.git` in place of the https URL.

## Commands

| Command | What it does |
|---|---|
| `lanes init` | Creates `.lanes/`, adds the agent instructions, registers the Claude Code hooks, and installs the git pre-commit lane check. It's safe to re-run. |
| `lanes whoami` | Shows your member id, tasks, owned globs and contracts. |
| `lanes status` | Shows a table of tasks, owners and statuses, unread notices per person, and warnings for tasks whose `owns` globs overlap and for any uncommitted change outside your lane. |
| `lanes check PATH…` | Exits 0 if the path is in your lane and 2 if not, with the reason. `--staged` checks the files a commit would touch. |
| `lanes notices` | Lists unread notices addressed to you. Use `--mark-read` once you've acted on them, or `--all` to include ones already read. |
| `lanes notices amend ID --summary "…"` | Rewrites the summary (and `--body`) of a notice you wrote, as long as nobody has read it yet. Files in `.lanes/notices/` are never edited directly; the guard blocks that. |
| `lanes request --file PATH "msg"` | Asks a path's owner for a change. |
| `lanes task status TASK STATUS` | Sets the status of a task you own. Only the plan owner edits `plan.yaml` directly; this is how everyone else updates status, and the commit check accepts it. Status changes never send notices. |
| `lanes handoff [TASK]` | Creates a handoff note from the template and prints its path. |
| `lanes sync` | Shares `.lanes/` with the team: commits `.lanes/` only, runs `git pull --rebase --autostash`, then pushes. It pushes on its own only when every unpushed commit is `.lanes/`-only; otherwise it lists your code commits and stops (exit 3) unless you pass `--include-code`. |

In Claude Code, `/lanes-status` explains the current status, and `/lanes-handoff` writes a handoff note.

## How it works

| Hook | When it runs | What it does |
|---|---|---|
| `SessionStart` | When a session starts, resumes, is cleared or is compacted | Adds a briefing of about 1,500 tokens or less: your lane, teammates, unread notices, your latest handoff, and the last 24 hours of summaries. |
| `PreToolUse` | Before Edit, Write or NotebookEdit | Blocks edits outside your lane and tells Claude who owns the file and how to ask them. |
| `PostToolUse` | After those same tools | If you changed a contract or hub file you own, writes a notice for higher-rank tasks only. If the plan owner changed who owns what in `plan.yaml`, writes a plan notice for every affected task. |
| `Stop` | At the end of each turn | Keeps a 3–5 line summary of the session in `.lanes/summaries/`. Turns with no edits leave it alone, so chatting doesn't keep dirtying the file. |
| git `pre-commit` | On `git commit` | Runs the same lane check on staged files. This catches edits made through Bash, by other agents, or by hand. |

The hooks **fail open**. A broken plan or an unknown identity never blocks your session; you see a warning instead. Notices and summaries are passed through a secret filter before they're written, and Lanes never reads `.env` files.

The plan format is in [docs/PLAN_FORMAT.md](docs/PLAN_FORMAT.md). Hook details, and where they differ from the brief, are in [docs/HOOKS_NOTES.md](docs/HOOKS_NOTES.md). What's planned next is in [docs/BACKLOG.md](docs/BACKLOG.md).

## Developing Lanes

```bash
uv sync
uv run pytest
```

This repo uses Lanes on itself: see `.lanes/plan.yaml`. Its hooks run the wrappers in `hooks/` through `uv run`, so changes take effect without reinstalling.

## License

MIT
