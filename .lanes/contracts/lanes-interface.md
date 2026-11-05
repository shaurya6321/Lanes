# Contract: lanes-interface

Owner: shaurya · Implemented by: T1 · Used by: T2

## Interface
- **CLI:** `lanes init | whoami | status | check PATH...|--staged | notices [--all] [--mark-read [ID...]] | notices amend ID [--summary S] [--body B] | request (--file PATH|--to MEMBER) MSG | handoff [TASK] | sync [--include-code] | hook NAME`
- **Exit codes:** `check` returns 0 when the path is in your lane and 2 when it isn't. `sync` returns 3 when it held back unpushed code commits (no `--include-code`). Any other error returns 1. The git pre-commit hook returns 1 when it blocks a commit.
- **Identity:** `LANES_USER`, or else `git config user.email` matched against `members[].email`.
- **Plan schema and ownership precedence:** see `docs/PLAN_FORMAT.md`.
- **Files under `.lanes/`:** `notices/<UTC>-<from>-<topic>.md` (YAML front matter), `notices/read-by/<member>.txt`, `handoffs/<task>-<UTC>.md`, `summaries/<member>-<date>.md`.

## Rules
- Hooks fail open, and the guard never returns "allow".
- Notices go only to tasks with a higher rank.
- Plan notices (`kind: plan`, with `base: <commit>`) go to every task whose `owns`/`uses`/`implements`/`owner`/`rank` the plan owner changed, whatever the rank. The plan owner is the top-level `owner:` (optional; default: the rank-1 task's owner).
- Files in `.lanes/notices/` are written only by `lanes` commands and the hooks. The guard denies Edit/Write/NotebookEdit there; use `lanes notices amend` (author only, while unread).

## Change log
<!-- Newest first, one line per change. Each edit to this file automatically notifies T2. -->
- 2026-11-05: `lanes sync [--include-code]` (exit 3 when code commits are held back).
- 2026-11-05: plan notices (`kind: plan`) and the optional plan `owner:` field.
- 2026-11-05: added `lanes notices amend`; direct edits to `.lanes/notices/` are blocked.
- 2026-11-05: first version (Phase 0).
