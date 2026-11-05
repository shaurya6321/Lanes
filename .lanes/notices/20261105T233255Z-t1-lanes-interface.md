---
id: 20261105T233255Z-t1-lanes-interface
kind: change
from_member: shaurya
from_task: T1
from_rank: 1
to_tasks:
- T2
to_members:
- friend
contract: lanes-interface
created: '2026-11-05T23:32:55Z'
session: 7943c629-d7d7-4526-8ab4-295c6add4cce
summary: '`.lanes/plan.yaml` now belongs to the plan owner (guard + commit check); task owners change their own tasks'' status with the new `lanes task status TASK STATUS`.'
---
+ lanes task status TASK {todo,in_progress,blocked,review,done}  (task owner only; Lanes edits plan.yaml)
+ guard: non-owner edits to .lanes/plan.yaml are denied
+ commit check: non-owner plan change allowed only if it is just their own tasks status vs HEAD (HEAD owner: is used)
Status-only changes never create plan notices.
