---
id: 20261106T003734Z-t1-lanes-interface
kind: change
from_member: shaurya
from_task: T1
from_rank: 1
to_tasks:
- T2
to_members:
- friend
contract: lanes-interface
created: '2026-11-06T00:37:34Z'
session: 2ee26c0f-3ad2-4131-a2e0-61ea07d3587a
summary: 'New planner: `lanes plan context|check|diff|accept [--force]` and `/lanes-plan`; proposal files (.lanes/plan.proposed.yaml, .lanes/proposal/**) are plan-owner-only; optional plan field `overlaps:`.'
---
+ lanes plan context | check (exit 1 on problems) | diff | accept [--force] (plan owner only)
+ /lanes-plan reads .lanes/PLAN.md (anyone may edit) and writes .lanes/plan.proposed.yaml + .lanes/proposal/contracts/*.md
+ guard + commit check: proposal files belong to the committed plan owner
+ plan.yaml: optional overlaps: [{globs: [A, B], why: TEXT}]; status lists explained overlaps as intended
+ accept keeps current task statuses, moves drafts to .lanes/contracts/, sends plan notices
