# `.lanes/plan.yaml` format

The plan is the single source of truth for who does what. It lives in git, and every teammate's agent reads it at the start of each session. Run `lanes status` to check it: an invalid plan prints every problem at once.

You can write it by hand, or describe the work in plain words in `.lanes/PLAN.md` and let `/lanes-plan` propose it (see [Planning with `/lanes-plan`](#planning-with-lanes-plan)).

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
| `overlaps[].globs` | no | Two `owns` globs, from different tasks, that overlap on purpose. |
| `overlaps[].why` | yes, per entry | Why the overlap is intended. `lanes status` lists explained overlaps as intended and warns about the rest. |

For example, a task that owns `tests/**` and another that owns `tests/e2e_results/**` overlap. The nested glob wins for files under `tests/e2e_results/`. To mark that as intended:

```yaml
overlaps:
  - globs: ["tests/**", "tests/e2e_results/**"]
    why: T2 records the Windows gate results inside T1's tests folder.
```

## Globs

- Paths are relative to the repo root and use forward slashes. Windows paths are converted before matching, so `src\api\cart\x.py` matches `src/api/cart/**`.
- `*` matches within one folder, and `**` matches across folders. `**/*.md` matches markdown files at any depth, including the root.
- `?` matches one character, but not `/`.
- A pattern with no wildcards also matches everything below it, so `src/api` is the same as `src/api/**`.
- A pattern ending in `/` means everything under that folder.
- Character classes such as `[abc]` aren't supported; the brackets are treated as literal characters.

## Who owns a path

Lanes checks these in order, and the first match decides:

1. **A contract file:** the contract's owner. This check comes before rule 4 because contracts live in `.lanes/`.
2. **`.lanes/plan.yaml`:** the plan owner (`owner:`, or else the rank-1 task's owner). The guard blocks everyone else's edits. The commit check blocks their commits too, with one exception: a change whose only difference from the last committed plan is the `status` of tasks they own. That is what `lanes task status` writes. For commits, the plan owner is read from the **committed** plan, so editing `owner:` to yourself doesn't help. An invalid plan turns the guard off (fail-open), so anyone can repair it.
3. **A plan proposal** (`.lanes/plan.proposed.yaml` and anything under `.lanes/proposal/`): the plan owner, exactly like `plan.yaml`. The guard blocks everyone else's edits, and the commit check reads the plan owner from the committed plan.
4. **Anything else under `.lanes/`:** anyone may write it. This covers `PLAN.md`, handoffs, summaries and `decisions.md`. Notices in `.lanes/notices/` may be committed by anyone but are written only by `lanes` commands and the hooks; the guard blocks direct edits there.
5. **A hub file:** the hub file's owner. If several hub patterns match, the most specific one wins.
6. **A task's `owns` glob:** that task's owner. If several patterns match, the most specific wins, meaning the one with the longest literal prefix. For example, `tests/e2e_results/**` beats `tests/**`, so `tests/e2e_results/x.md` belongs to the task that owns the nested glob. If two globs are equally specific, the lower rank number wins. Nesting one task's glob inside another's is allowed, but `lanes status` warns about every overlapping pair that `overlaps:` doesn't explain, and says which task wins, so an accidental overlap doesn't go unnoticed.
7. **Nothing matched:** the path is unowned, and nobody may edit it until the plan gives it an owner.

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

- an `overlaps` entry without exactly two globs or without a `why`

When the plan is invalid, the lane guard **fails open**: it allows edits and shows a warning. A typo in the plan therefore never blocks anyone's session. Overlapping globs and stale `overlaps` entries are only warnings for the same reason; `lanes plan check` is stricter (below).

## Planning with `/lanes-plan`

Instead of writing `plan.yaml` by hand, the team describes the work and Claude proposes how to divide it. The same flow works for the first plan and for re-planning mid-project.

1. **Write `.lanes/PLAN.md`** together. `lanes init` creates it with four sections: the goal, what needs building, the team (one line per member id with their preferences, such as `- friend: the CLI`), and rules. Anyone may edit it.
2. **The plan owner runs `/lanes-plan`** in Claude Code. Claude runs `lanes plan context`, which prints PLAN.md, the current plan, the existing contracts, the repo's files and the import graph between them (Python and JS/TS), with hub candidates and clusters of coupled files. Claude then writes a proposal and never touches `plan.yaml`. It follows these rules:
   - Assignments and preferences in PLAN.md always win.
   - Tightly coupled files stay in one task, and shared hub files get one owner.
   - Every interface between tasks gets a contract, drafted before anyone codes.
   - Ranks follow dependencies: upstream tasks get the lower rank.
   - Every file the work touches has exactly one owner, and overlaps exist only when intended and explained.
   - Existing contracts are reused, never edited or duplicated.
3. **Review it.** `lanes plan check` validates it, and `lanes plan diff` shows what would change, including **what moves**: every file in the repo whose owner changes, grouped by folder.
4. **Accept it.** The plan owner runs `lanes plan accept`, then commits `.lanes/` and runs `lanes sync`.

### The proposal files

`.lanes/plan.proposed.yaml` is a complete plan in the format above, followed by a `proposal:` block that `accept` removes:

```yaml
proposal:
  based_on: 543c04ed0527          # printed by `lanes plan context`: a hash of the plan.yaml it started from
  touches: [notes/models.py, notes/export.py, "web/pages/**"]   # every path the work creates or changes
  rationale:
    T1: models, storage and search are imported by everything else; PLAN.md gives them to shaurya.
```

Each **new** contract is drafted at `.lanes/proposal/contracts/<name>.md`, and the proposal gives it its final `file:` under `.lanes/contracts/`. Only the plan owner may write any of these files.

### What `lanes plan check` rejects

Everything that makes a plan invalid (see Validation), plus:

- a path in `touches` that no task or hub file owns
- `owns` globs of two tasks that overlap without an `overlaps:` entry
- a contract that no task implements, that more than one task implements, or that no task uses
- a task using a contract implemented by a task of the same or a higher rank
- a contract file that's missing, or a draft that would overwrite an existing contract

It warns (without failing) about:

- a user of a contract that doesn't depend on the implementer
- a hub file inside another member's `owns`
- a PLAN.md team name that isn't a member, and a member with no task
- repo files nobody owns
- stale `overlaps` entries
- a proposal drafted from an older `plan.yaml` (`based_on` doesn't match)

### What `lanes plan accept` does

- **Owner only:** it runs only for the plan owner, as recorded in the committed plan, and only if `check` passes. If `plan.yaml` changed since the proposal was drafted, it refuses unless you pass `--force`.
- **Writes `plan.yaml`:** it replaces `plan.yaml` with the proposal, keeping the proposal's comments, removing the `proposal:` block and setting `updated` to today.
- **Keeps statuses:** every existing task keeps its **current** status, because statuses belong to task owners.
- **Moves drafts:** it moves the draft contracts into `.lanes/contracts/` and deletes the proposal.
- **Notifies:** it writes the normal plan notice to every task whose `owns`, `uses`, `implements`, `owner` or `rank` changed, and to former owners.

## Other files in `.lanes/`

| Path | What it holds |
|---|---|
| `PLAN.md` | The plan in plain words, for `/lanes-plan`. Anyone may edit it. |
| `plan.proposed.yaml` | A plan proposal waiting for `lanes plan accept`. Plan owner only. |
| `proposal/contracts/<id>.md` | Draft contracts for the proposal. Plan owner only. |
| `contracts/<id>.md` | Interface documents. Start from `contracts/_TEMPLATE.md`. |
| `notices/<timestamp>-<from>-<topic>.md` | Change notices and requests: YAML front matter plus a short body. |
| `notices/read-by/<member>.txt` | Ids of the notices that member has read. Only that member writes it, so it never conflicts in git. |
| `handoffs/<task>-<timestamp>.md` | Handoff notes. Create one with `lanes handoff` or `/lanes-handoff`. |
| `summaries/<member>-<YYYY-MM-DD>.md` | One section per session, written by the Stop hook. |
| `decisions.md` | Decision log, with the newest entry last. |
| `local/` | State for this machine only. It is gitignored and never shared. |
