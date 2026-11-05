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
summary: New command `lanes notices amend ID --summary S [--body B]`; the guard now denies direct edits to .lanes/notices/.
---
+ lanes notices amend ID [--summary S] [--body B]  (author only, while unread)
+ Rule: Edit/Write/NotebookEdit under .lanes/notices/ are denied by the guard
Notices are still created only by the hooks and `lanes request`.
