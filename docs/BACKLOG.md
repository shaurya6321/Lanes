# Backlog

Phase 0 deliberately leaves these out. Each line says which phase it belongs to and why it was deferred.

## Phase 1
- **Codex adapter.** Fill in `from_codex()` in `lanes/hooks/adapters.py`, add `.codex/hooks.json` and `.codex/config.toml`, and generate `AGENTS.md`. The template already renders `AGENTS.md`. Re-check whether Codex PreToolUse sees file-patch edits; if it doesn't, the pre-commit check is the guard.
- **Agent Mail.** Notices should arrive without a `git pull`. The `.lanes/notices/` file format stays, so Agent Mail can serve as an extra delivery path.
- **Beads** for atomic task claims. In Phase 0, `status` in `plan.yaml` is edited by hand.
- **Plan-change notices.** In Phase 0 anyone can edit `.lanes/plan.yaml`; the guard always allows `.lanes/`. Phase 1 should limit ownership edits to a plan owner, or send a notice whenever the plan changes.

## Phase 2 and later
- `/lanes-plan`: the cohesion planner.
- `/lanes-integrate`: ordered merges, Mergiraf, running the combined tests.

## Known gaps in Phase 0
- **Writes made through Bash aren't guarded before they happen.** Only the pre-commit check catches them. A future option is a PreToolUse hook on Bash that parses common write patterns. It would be best-effort.
- **Overlapping globs between different owners** (for example `src/**` and `src/api/**`) aren't rejected when the plan is validated. At lookup time the most specific pattern wins. Phase 2's planner should flag overlaps.
- **Read state for notices** is kept in one append-only file per member, `.lanes/notices/read-by/<member>.txt`. That avoids git conflicts but grows forever. Prune it once the plan is archived.
- **The "why" line in summaries** is taken from Claude's last message, so a turn that ends with a question gives a weak "why".
- **The PyPI name `lanes` is probably taken.** Before publishing, check it and fall back to `lanes-dev` or `lanesync`.
