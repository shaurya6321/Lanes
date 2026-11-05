---
id: 20261105T232545Z-t1-lanes-interface
kind: change
from_member: shaurya
from_task: T1
from_rank: 1
to_tasks:
- T2
to_members:
- friend
contract: lanes-interface
created: '2026-11-05T23:25:45Z'
session: 7943c629-d7d7-4526-8ab4-295c6add4cce
summary: 'New `lanes init --local` (repo-only: hooks run `uv run --project ${CLAUDE_PROJECT_DIR} lanes hook NAME`, messages say `uv run lanes ...`) and `--global`; plain `lanes init` keeps the repo''s current mode.'
---
+ lanes init [--local|--global]
+ local hooks: uv run --quiet --project ${CLAUDE_PROJECT_DIR} lanes hook NAME (exec form, one arg per path)
+ local git hook: uv run --project "$top" lanes hook pre-commit; skips (fail-open) if the env is not synced
+ example plan: pyproject.toml and uv.lock are hub files of the initializer
