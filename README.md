# Lanes

**Shared plan, separate lanes.** Lanes lets 2–6 people each run Claude Code on their own machine against the same repo, without overwriting or breaking each other's work. It works in Cursor or VS Code, on macOS or Windows. Codex support is planned.

## The 30-second version

When two people point coding agents at one repo, neither agent knows what the other is doing. Lanes gives every session the same picture:

- **One shared plan** (`.lanes/plan.yaml`). The feature is split into ranked tasks, and each task has an owner and a set of owned files (its *lane*).
- **A briefing at session start.** Claude is told who you are, what your lane is, what teammates are doing, and what changed since your last session.
- **A lane guard.** If Claude tries to edit a file outside your lane, a hook stops it and tells it who to ask instead.
- **One-way change notices.** When you change a contract or shared file you own, a short notice goes to downstream tasks only (lower rank to higher rank), so two agents never ping-pong.
- **Summaries and handoffs.** Each session leaves a 3–5 line summary, and `/lanes-handoff` writes a handoff note. The next session can continue without anyone re-explaining.

Phase 0 has no servers. Everything is files in your repo, synced with `git push` and `git pull`.

## Quickstart

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), git and Claude Code. Teammates on Windows also need Git for Windows. [docs/SETUP.md](docs/SETUP.md) has the full steps for both operating systems.

```bash
# 1. Install the lanes CLI (once per machine)
git clone git@github.com:shaurya6321/Lanes.git
cd Lanes
uv tool install --editable .
lanes --version            # if not found: run `uv tool update-shell` and open a new terminal

# 2. Set up the repo you want to build in
cd path/to/your-project
lanes init                 # creates .lanes/, CLAUDE.md, AGENTS.md, .claude/settings.json, git hook
#    then edit .lanes/plan.yaml: members, tasks, owned globs, contracts

# 3. Tell Lanes who you are (use your member id from plan.yaml)
echo 'export LANES_USER=shaurya' >> ~/.zshrc && source ~/.zshrc     # macOS
#   Windows PowerShell:  setx LANES_USER friend   (then open a new terminal)

# 4. Share the setup with your team
git add .lanes CLAUDE.md AGENTS.md .claude .gitignore .gitattributes
git commit -m "Set up Lanes"
git push

# 5. Work as usual
claude                     # the Lanes briefing appears at the top of the session
```

To check it's working, run `lanes whoami` (your tasks and owned files) and `lanes status` (everyone's tasks and unread notices).

## Commands

| Command | What it does |
|---|---|
| `lanes init` | Creates `.lanes/`, adds the agent instructions, registers the Claude Code hooks, and installs the git pre-commit lane check. It's safe to re-run. |
| `lanes whoami` | Shows your member id, tasks, owned globs and contracts. |
| `lanes status` | Shows a table of tasks, owners and statuses, unread notices per person, and a warning for any uncommitted change outside your lane. |
| `lanes check PATH…` | Exits 0 if the path is in your lane and 2 if not, with the reason. `--staged` checks the files a commit would touch. |
| `lanes notices` | Lists unread notices addressed to you. Use `--mark-read` once you've acted on them, or `--all` to include ones already read. |
| `lanes notices amend ID --summary "…"` | Rewrites the summary (and `--body`) of a notice you wrote, as long as nobody has read it yet. Files in `.lanes/notices/` are never edited directly; the guard blocks that. |
| `lanes request --file PATH "msg"` | Asks a path's owner for a change. |
| `lanes handoff [TASK]` | Creates a handoff note from the template and prints its path. |

In Claude Code, `/lanes-status` explains the current status, and `/lanes-handoff` writes a handoff note.

## How it works

| Hook | When it runs | What it does |
|---|---|---|
| `SessionStart` | When a session starts, resumes, is cleared or is compacted | Adds a briefing of about 1,500 tokens or less: your lane, teammates, unread notices, your latest handoff, and the last 24 hours of summaries. |
| `PreToolUse` | Before Edit, Write or NotebookEdit | Blocks edits outside your lane and tells Claude who owns the file and how to ask them. |
| `PostToolUse` | After those same tools | If you changed a contract or hub file you own, writes a notice for higher-rank tasks only. If the plan owner changed who owns what in `plan.yaml`, writes a plan notice for every affected task. |
| `Stop` | At the end of each turn | Keeps a 3–5 line summary of the session in `.lanes/summaries/`. |
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
