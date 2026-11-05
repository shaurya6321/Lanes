---
id: 20261105T225344Z-t1-lanes-interface
kind: change
from_member: shaurya
from_task: T1
from_rank: 1
to_tasks:
- T2
to_members:
- friend
contract: lanes-interface
created: '2026-11-05T22:53:44Z'
session: 7943c629-d7d7-4526-8ab4-295c6add4cce
summary: 'Added `lanes notices amend` (direct edits to .lanes/notices/ are now blocked) and plan notices (kind: plan) for ownership changes by the plan owner, plus an optional top-level plan `owner:`.'
---
+ lanes notices amend ID [--summary S] [--body B]  (author only, while unread)
+ guard denies Edit/Write/NotebookEdit under .lanes/notices/
+ plan.yaml: optional `owner:` (default: rank-1 task owner)
+ notice kind "plan" with `base: <sha>`; sent to every task whose owns/uses/implements/owner/rank changed, ignoring rank
