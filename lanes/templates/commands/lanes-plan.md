---
description: Propose how to split the work in .lanes/PLAN.md into lanes (writes a proposal, never plan.yaml)
argument-hint: "[extra instructions]"
allowed-tools: Bash($lanes plan context:*), Bash($lanes plan check:*), Bash($lanes plan diff:*), Bash($lanes whoami:*), Read, Glob, Grep, Edit(.lanes/plan.proposed.yaml), Edit(.lanes/proposal/**)
---
Propose a Lanes plan from the team's plain-words plan. Extra instructions from my human: $ARGUMENTS

You write a **proposal** only. The plan owner reviews it and runs `$lanes plan accept`; you never do.

## 1. Gather
Run `$lanes plan context`. It prints `.lanes/PLAN.md`, the current `.lanes/plan.yaml`, the existing contracts, the repo's files, the import graph, hub candidates and clusters. Read more source files if you need to understand how code is coupled. Don't change any of them.

Stop and tell me, without writing anything, if:
- the context says you aren't the plan owner (only the plan owner may write a proposal; teammates edit `.lanes/PLAN.md` instead), or
- `.lanes/PLAN.md` is missing, or still only has the template's examples. Ask the team to fill it in first.

## 2. Design the split. These rules are not optional
1. **PLAN.md wins.** Assignments, preferences and rules written in PLAN.md ("friend: the CLI") always win over anything below. If one conflicts with a rule below, follow PLAN.md and say so in `rationale`.
2. **Cohesion.** Keep tightly coupled files in the same task: use the clusters, and keep each test with the code it tests. Shared files (the hub candidates, plus manifests, lockfiles and shared config such as `package.json`, `pyproject.toml`, `uv.lock`) go in `hub_files`, each with exactly one owner, usually the most upstream task's owner.
3. **Contracts first.** Every interface between tasks needs a contract, whenever one task calls, imports, renders or consumes another's code, API, events, schema or data format. The upstream task `implements` it; each downstream task lists it in `uses`. Write each new contract's draft now, before anyone codes: exact names, signatures, types, errors, units.
4. **Ranks follow dependencies.** Upstream means a lower rank number. `depends_on` lists only lower-ranked tasks, and a task that uses a contract depends, directly or indirectly, on the task that implements it.
5. **One owner per file.** Every file the work will create or change is owned by exactly one task or hub entry. List them all in `proposal.touches`: existing files to change, new files to create, or directory globs for new areas. `owns` globs of different tasks must not overlap. If an overlap is intended, add it to `overlaps:` with a `why`.
6. **Reuse contracts.** If an existing contract already covers an interface, reference it by its id. Never edit an existing contract file, and don't invent a new contract for the same thing.

If the current plan is still the `lanes init` example (feature `my-feature`, tasks owning `src/api/**` and `src/ui/**`, contract `example-api`), this is a first plan: name `feature` after the goal and replace the example tasks and contract (keep the members, `owner:` and the init hub files).

Changing `owns`, `hub_files` and `contracts` is what a proposal is for. It needs no separate OK, because the plan owner reviews the diff and accepting is the OK.

When re-planning a real plan, keep task ids, owners, `owns` globs and members stable unless PLAN.md asks for a change. Avoid moving files away from an `in_progress` task. Keep the current `owner:` (plan owner) and members' emails. A new member from PLAN.md's Team section gets `email: null`; say in the rationale that they must add their git email.

## 3. Write the proposal (only these paths)
- `.lanes/plan.proposed.yaml`: a complete plan in the same schema as `.lanes/plan.yaml` (spec: docs/PLAN_FORMAT.md in the Lanes repo), followed by:
  ```yaml
  proposal:
    based_on: <the based_on value printed by `lanes plan context`>
    touches: [<every path or glob the work will create or change>]
    rationale:
      T1: <one line: why these files belong together; which PLAN.md line it honours>
  ```
  A new contract's `file:` is `.lanes/contracts/<id>.md`.
- `.lanes/proposal/contracts/<id>.md`: one draft per **new** contract, with the sections of `.lanes/contracts/_TEMPLATE.md` (Interface, Rules, Change log). `lanes plan accept` moves it into place.

Never write `.lanes/plan.yaml`, an existing contract, a notice or any source file.

## 4. Check, then report
Run `$lanes plan check`. Fix every error in the proposal and run it again until it passes. Resolve each warning or explain why it's fine. Then run `$lanes plan diff`.

Reply with:
- a table of tasks: id, owner, rank, `owns`, implements/uses
- the hub files and contracts (marking which are new drafts)
- any intended overlaps and anything from PLAN.md you couldn't satisfy
- the diff's "What moves" section, if any

End with: "Review with `$lanes plan diff`. If it looks right, the plan owner runs `$lanes plan accept`, then `$lanes sync`."
