# Contract: lanes-interface

Owner: shaurya · Implemented by: T1 · Used by: T2

## Interface
- **Install modes:** global (`lanes ...` on PATH) or repo-only (`lanes init --local`: Lanes is a dev dependency, hooks run `uv run --project ${CLAUDE_PROJECT_DIR} lanes hook NAME`, and every message says `uv run lanes ...`). `lanes init` without a flag keeps the repo's current mode.
- **CLI:** `lanes init [--local|--global] | whoami | status | check PATH...|--staged | notices [--all] [--mark-read [ID...]] | notices amend ID [--summary S] [--body B] | request (--file PATH|--to MEMBER) MSG | handoff [TASK] | task status TASK STATUS | plan context|check|diff | plan accept [--force] | sync [--include-code] | hook NAME`
- **Slash commands:** `/lanes-status`, `/lanes-handoff`, `/lanes-plan` (writes only the proposal files below).
- **Exit codes:** `check` returns 0 when the path is in your lane and 2 when it isn't. `plan check` returns 1 when the proposal has problems. `sync` returns 3 when it held back unpushed code commits (no `--include-code`). Any other error returns 1. The git pre-commit hook returns 1 when it blocks a commit.
- **Identity:** `LANES_USER`, or else `git config user.email` matched against `members[].email`.
- **Plan schema and ownership precedence:** see `docs/PLAN_FORMAT.md`. New optional field: `overlaps: [{globs: [A, B], why: TEXT}]`.
- **Files under `.lanes/`:** `notices/<UTC>-<from>-<topic>.md` (YAML front matter), `notices/read-by/<member>.txt`, `handoffs/<task>-<UTC>.md`, `summaries/<member>-<date>.md`, `PLAN.md`, `plan.proposed.yaml` (a full plan plus a `proposal:` block: `based_on`, `touches`, `rationale`), `proposal/contracts/<name>.md`.

## Rules
- Hooks fail open, and the guard never returns "allow".
- Notices go only to tasks with a higher rank.
- Plan notices (`kind: plan`, with `base: <commit>`) go to every task whose `owns`/`uses`/`implements`/`owner`/`rank` the plan owner changed, whatever the rank. The plan owner is the top-level `owner:` (optional; default: the rank-1 task's owner).
- Files in `.lanes/notices/` are written only by `lanes` commands and the hooks. The guard denies Edit/Write/NotebookEdit there; use `lanes notices amend` (author only, while unread).
- `.lanes/plan.yaml` is owned by the plan owner. Others change only their own tasks' `status`, via `lanes task status`; the commit check accepts a non-owner's plan change only if that is the sole difference from the committed plan (whose `owner:` is the one used). Status-only changes never create notices.
- `.lanes/plan.proposed.yaml` and `.lanes/proposal/**` are owned by the plan owner (the guard, and the commit check using the committed `owner:`). `.lanes/PLAN.md` is writable by anyone.
- `lanes plan accept` runs only for the committed plan's owner and only when `plan check` passes. It keeps each existing task's current `status`, moves drafts into `.lanes/contracts/`, deletes the proposal and sends the normal plan notices.

## Change log
<!-- Newest first, one line per change. Each edit to this file automatically notifies T2. -->
- 2026-11-05: planner: `.lanes/PLAN.md`, `/lanes-plan`, `lanes plan context|check|diff|accept`, proposal files (plan owner only), the plan's `overlaps:` field.
- 2026-11-05: `.lanes/plan.yaml` belongs to the plan owner; new `lanes task status TASK STATUS` for task owners.
- 2026-11-05: `lanes init --local` (repo-only installs) and `--global`; messages use the matching command spelling.
- 2026-11-05: `lanes sync [--include-code]` (exit 3 when code commits are held back).
- 2026-11-05: plan notices (`kind: plan`) and the optional plan `owner:` field.
- 2026-11-05: added `lanes notices amend`; direct edits to `.lanes/notices/` are blocked.
- 2026-11-05: first version (Phase 0).
