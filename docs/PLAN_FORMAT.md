# `.lanes/plan.yaml` format

The plan is the single source of truth for who does what. It lives in git, and every teammate's agent reads it at the start of each session. Run `lanes status` to check it: an invalid plan prints every problem at once.

## Example

```yaml
feature: checkout-v1
updated: 2026-11-05
owner: shaurya        # the plan owner (optional; defaults to the rank-1 task's owner)
members:
  - id: shaurya
    email: shaurya@example.com
  - id: friend
    email: friend@example.com
hub_files:            # shared files with exactly one owner
  - path: package.json
    owner: shaurya
  - path: src/types/**
    owner: shaurya
contracts:
  - id: cart-api
    file: .lanes/contracts/cart-api.md
    owner: shaurya
tasks:
  - id: T1
    title: Cart API + types
    rank: 1            # lower rank = upstream; notices flow 1 → 2 → 3
    owner: shaurya
    owns: ["src/api/cart/**", "src/types/**"]
    implements: [cart-api]
    depends_on: []
    status: in_progress
  - id: T2
    title: Checkout page UI
    rank: 2
    owner: friend
    owns: ["src/pages/checkout/**", "src/components/checkout/**"]
    uses: [cart-api]
    depends_on: [T1]
    status: todo
```

## Fields

| Field | Required | Meaning |
|---|---|---|
| `feature` | yes | Name of the feature this plan covers. |
| `updated` | no | Date the plan last changed. Shown in `lanes status`. |
| `owner` | no | The member who changes who owns what. Their ownership edits send plan notices. Defaults to the owner of the lowest-rank task. |
| `members[].id` | yes | Short id made of letters, digits, `.`, `_` and `-`. Each person sets `LANES_USER` to their id. |
| `members[].email` | no | Used when `LANES_USER` isn't set: Lanes matches it against `git config user.email`. The match ignores case. |
| `hub_files[].path` | yes | A path or glob for a shared file that has exactly one owner, such as `package.json` or a types folder. |
| `hub_files[].owner` | yes | A member id. |
| `contracts[].id` | yes | Unique id that tasks refer to in `implements` and `uses`. |
| `contracts[].file` | yes | Path to the contract document, usually in `.lanes/contracts/`. |
| `contracts[].owner` | yes | The only member allowed to edit the contract file. |
| `tasks[].id` | yes | Unique id, such as `T1`. |
| `tasks[].title` | no | One line. |
| `tasks[].rank` | yes | Integer of 1 or more. A lower rank is upstream. Ranks may repeat when tasks are independent. |
| `tasks[].owner` | yes | A member id. |
| `tasks[].owns` | no | Globs for the files this task may write. |
| `tasks[].implements` | no | Contract ids this task provides. The task's owner must also own the contract. |
| `tasks[].uses` | no | Contract ids this task relies on. The task gets a notice when one of them changes. |
| `tasks[].depends_on` | no | Task ids that must come first. Each must have a **lower** rank. |
| `tasks[].status` | no | One of `todo` (the default), `in_progress`, `blocked`, `review`, `done`. The task's owner changes it with `lanes task status TASK STATUS`. |

## Globs

- Paths are relative to the repo root and use forward slashes. Windows paths are converted before matching, so `src\api\cart\x.py` matches `src/api/cart/**`.
- `*` matches within one folder, and `**` matches across folders. `**/*.md` matches markdown files at any depth, including the root.
- `?` matches one character, but not `/`.
- A pattern with no wildcards also matches everything below it, so `src/api` is the same as `src/api/**`.
- A pattern ending in `/` means everything under that folder.
- Character classes such as `[abc]` aren't supported; the brackets are treated as literal characters.

## Who owns a path

Lanes checks these in order, and the first match decides:

1. **A contract file:** the contract's owner. This check comes before rule 3 because contracts live in `.lanes/`.
2. **`.lanes/plan.yaml`:** the plan owner (`owner:`, or else the rank-1 task's owner). The guard blocks everyone else's edits. The commit check blocks their commits too, with one exception: a change whose only difference from the last committed plan is the `status` of tasks they own. That is what `lanes task status` writes. For commits, the plan owner is read from the **committed** plan, so editing `owner:` to yourself doesn't help. An invalid plan turns the guard off (fail-open), so anyone can repair it.
3. **Anything else under `.lanes/`:** anyone may write it. This covers handoffs, summaries and `decisions.md`. Notices in `.lanes/notices/` may be committed by anyone but are written only by `lanes` commands and the hooks; the guard blocks direct edits there.
4. **A hub file:** the hub file's owner. If several hub patterns match, the most specific one wins.
5. **A task's `owns` glob:** that task's owner. If several patterns match, the most specific wins, meaning the one with the longest literal prefix. For example, `tests/e2e_phase0.md` beats `tests/**`.
6. **Nothing matched:** the path is unowned, and nobody may edit it until the plan gives it an owner.

You may edit a path when you are its owner through any of your tasks, hub files or contracts.

## Rules

- Every file a task writes must match its `owns` globs. Anything else is a hub file or another owner's file.
- A contract is changed only by its owner. Every change creates a notice for tasks with a **higher rank** that `use` the contract or depend on the changing task, directly or indirectly.
- A notice never goes to a task of the same or a lower rank. This prevents two agents from reacting to each other in a loop.
- Requests made with `lanes request` go straight to the owner whatever the rank, because they are explicit asks rather than automatic reactions.
- **Plan changes:** when the plan owner edits `plan.yaml`, Lanes compares it with the last commit and sends one `kind: plan` notice to every task whose `owns`, `uses`, `implements`, `owner` or `rank` changed (and to a reassigned task's former owner). Plan notices skip the rank rule, because a task losing files must hear about it. They can't loop, because only the plan owner's edits create them. Only the plan owner can edit the plan (see rule 2 above). Status-only changes, by anyone, never send a notice.
- Merge order equals rank order.

## Validation

`lanes status`, the hooks and `lanes check` all reject a plan that has any of these problems:

- an owner who isn't in `members`
- a duplicate member, task or contract id
- a `uses` or `implements` entry naming an unknown contract
- a `depends_on` entry naming an unknown task, the task itself, or a task with the same or a higher rank
- a task that implements a contract owned by someone else
- the same glob claimed by two different owners
- a bad `rank` or `status`

When the plan is invalid, the lane guard **fails open**: it allows edits and shows a warning. A typo in the plan therefore never blocks anyone's session.

## Other files in `.lanes/`

| Path | What it holds |
|---|---|
| `contracts/<id>.md` | Interface documents. Start from `contracts/_TEMPLATE.md`. |
| `notices/<timestamp>-<from>-<topic>.md` | Change notices and requests: YAML front matter plus a short body. |
| `notices/read-by/<member>.txt` | Ids of the notices that member has read. Only that member writes it, so it never conflicts in git. |
| `handoffs/<task>-<timestamp>.md` | Handoff notes. Create one with `lanes handoff` or `/lanes-handoff`. |
| `summaries/<member>-<YYYY-MM-DD>.md` | One section per session, written by the Stop hook. |
| `decisions.md` | Decision log, with the newest entry last. |
| `local/` | State for this machine only. It is gitignored and never shared. |
