# Lanes: instructions for coding agents

Lanes is a Python CLI plus Claude Code hooks that let 2–6 people, each running their own coding agent, share one plan for a repo. `docs/PROJECT_BRIEF.md` is the source of truth for scope, and `README.md` gives the overview.

## Developing Lanes
- Setup: `uv sync`. Tests: `uv run pytest`. Run tests before every commit.
- Logic lives in `lanes/`. The files in `hooks/*.py` are thin wrappers, so don't put logic there.
- Hooks may use only the standard library and PyYAML. They must start in under 300 ms and **fail open**: an error or bad plan never blocks a session.
- Before changing any hook input or output, re-read `docs/HOOKS_NOTES.md`, and check the live docs if Claude Code has updated.
- Code must work on macOS and Windows. Use `pathlib` and `lanes.paths.to_posix` for any path you match. Don't add bash or PowerShell scripts.
- Never write secrets into notices, summaries or handoffs. Everything written goes through `lanes.redact.redact`.
- Current scope is Phase 0. Ideas for Phase 1 and later (servers, Agent Mail, Beads, the Codex adapter, the planner, the integrator) go in `docs/BACKLOG.md`; don't build them.

<!-- lanes:begin (managed by `lanes init`; edit lanes/templates/agent_instructions.md, not this block) -->
## Working with Lanes

This repo uses **Lanes**. Several people each run a coding agent on their own machine and share one plan in `.lanes/plan.yaml`. Each person's tasks own specific files, called their *lane*.

1. **Read the Lanes briefing first.** Run `lanes status` and `lanes notices` at the start of every session. Automatic briefings for Codex come in Phase 1. It tells you who you are, your tasks, the files you own, what teammates are doing, and any unread notices.
2. **Stay inside your lane.** Only edit files your tasks own (run `lanes whoami` to see them). You may also write anything in `.lanes/` except contracts you don't own and `.lanes/notices/` (only the `lanes` commands write notices).
3. **If you need something outside your lane, don't edit it and don't work around it.** Run `lanes request --file <path> "<what you need and why>"` to ask the owner, tell your human, and carry on with what you can do.
4. **Don't change who owns what.** Never edit `owns`, `hub_files` or `contracts` in `.lanes/plan.yaml` without your human's explicit OK.
5. **Changing a contract you own:** Lanes automatically writes a notice for downstream tasks. Replace its auto-generated summary with `lanes notices amend <id> --summary "<one precise sentence>" --body "<3–6 lines>"`, covering renamed symbols, added or removed arguments, and changed types, in under about 150 tokens. Never edit files in `.lanes/notices/` directly; Lanes blocks it.
6. **Unread notices:** act on any that affect your task, then run `lanes notices --mark-read`.
7. **Before you stop:** say in one or two sentences what you did and why in your final message. Lanes uses it for the session summary. To hand off, run `lanes handoff` and fill in the file it creates. Teammates only see `.lanes/` changes after a sync, so suggest your human run `lanes sync` (it commits `.lanes/` only, pulls and pushes, and never pushes code commits without `--include-code`). Don't run it yourself unless they ask.
8. **Unsure who owns something?** Run `lanes status` or `lanes check <path>`.

Never put secrets (keys, tokens, `.env` values) in notices, summaries or handoffs, and never read `.env` files.
<!-- lanes:end -->
