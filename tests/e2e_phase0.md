# Phase 0 end-to-end test (two machines)

This is a manual script for the Phase 0 gate. **A** is the rank-1 member (for example shaurya on macOS) and **B** is the rank-2 member (for example friend on Windows). Tick each box as you go, and write down anything surprising at the bottom.

The project uses the **repo-only** install: Lanes is a dev dependency, nothing is global. Commands below are written `lanes ...`; type `uv run lanes ...`.

## 0. Prepare a throwaway project (A)

```
mkdir lanes-e2e && cd lanes-e2e && git init -b main
git config user.email <A's email>
uv init --bare
uv add --dev "lanes @ git+https://github.com/shaurya6321/Lanes@v0.2.0"
uv run lanes init --local --member shaurya
```

Edit `.lanes/plan.yaml`:

- Rename the member `teammate` to B's id, for example `friend`, and set its `email` to B's git email.
- Change T2's `owner` to that id as well.
- Keep T1 (rank 1, owns `src/api/**` and `src/types/**`, implements `example-api`) and T2 (rank 2, owns `src/ui/**`, uses `example-api`) as they are.

Then commit and push:

```
git add -A && git commit -m "Lanes e2e setup"
# create an empty private GitHub repo, add B as a collaborator, then:
git remote add origin git@github.com:<you>/lanes-e2e.git && git push -u origin main
```

- [ ] `lanes status` shows T1 (shaurya) and T2 (friend) with no errors.

## 1. Both machines: identity

- No `LANES_USER` and nothing global: Lanes matches each person's repo-local `git config user.email` to the plan.
- B: run `git clone ...`, then `cd lanes-e2e`, `git config user.email <B's email in the plan>`, `uv sync` and `lanes init`. Git hooks aren't cloned, so this installs the commit check; it leaves the plan and other files alone.
- [ ] On B, `lanes` (without `uv run`) is **not** found, and `uv run lanes --version` works.
- [ ] On B, `git status` is clean after `lanes init`.
- [ ] On both machines, `lanes whoami` shows the right member and tasks.
- [ ] On both machines, `/hooks` inside `claude` lists SessionStart, PreToolUse, PostToolUse and Stop.

## 2. Session briefing

- Both machines: start `claude` in the repo.
- [ ] The first context contains "Lanes briefing · feature: my-feature", with **your** tasks under "Your lane" and the other person under "Teammates".
- [ ] The status line says `Lanes: briefing loaded for <you> (...)`.

## 3. The lane guard blocks out-of-lane edits

- B: ask Claude to "Create `src/api/hello.py` with a hello() function." That file is in A's lane.
- [ ] The edit is **blocked**, and the reason names `shaurya` and suggests `lanes request --file "src/api/hello.py" ...`.
- [ ] Claude then runs `lanes request` (or offers to) instead of working around the block.
- B: ask Claude to "Create `src/ui/page.txt` saying hi." That file is in B's own lane.
- [ ] It succeeds with no extra permission prompt from Lanes (normal Claude Code prompts still apply).

## 4. A contract change sends a notice only downstream

- A: ask Claude to "Add a `getItem(id: str) -> Item` function to the Interface section of `.lanes/contracts/example-api.md`."
- [ ] After the edit, Claude says a notice was written to `.lanes/notices/<...>-t1-example-api.md`, and then runs `lanes notices amend <id> --summary "..."` with one precise sentence. It does **not** edit the notice file (the guard would block it).
- [ ] The notice's front matter has `to_tasks: [T2]` and `from_rank: 1`.
- A: end the session. A turn that only answers a question is fine.
- [ ] `.lanes/summaries/shaurya-<date>.md` exists, with one section listing `.lanes/contracts/example-api.md`.
- A: `lanes sync`.
- [ ] It says it committed the `.lanes/` files and pushed 1 commit (`.lanes/ only`). The lane check ran on that commit and allowed it.

## 5. B's next session shows the notice

- B: `lanes sync`, then start a **new** `claude` session.
- [ ] The briefing has "Unread notices for you (1)", with A's summary and the getItem change lines.
- [ ] The briefing has "Recent session summaries (last 24h)", with A's session.
- [ ] Ask Claude "What did my teammate change?" It answers from the briefing without opening any files.
- B: `lanes notices --mark-read`, then `lanes sync`. Then on A, run `lanes sync` and `lanes status`.
- [ ] `lanes status` shows `friend 0` unread.

## 6. Notices never flow upstream

- B: ask Claude to "add a contract `ui-events` to `.lanes/plan.yaml`".
- [ ] The edit is **blocked**: the plan belongs to the plan owner (A). Claude suggests `lanes request --file .lanes/plan.yaml ...` instead.
- A (plan owner): in `.lanes/plan.yaml`, add a contract `ui-events` with `file: .lanes/contracts/ui-events.md` and `owner: friend`. Add `implements: [ui-events]` to T2, and `uses: [ui-events]` to T1. That last part is deliberately the wrong direction. Run `lanes sync`. B: `lanes sync`.
- B: ask Claude to "create `.lanes/contracts/ui-events.md` describing a Clicked event."
- [ ] **No notice** is created for T1, because rank 2 never notifies rank 1. `ls .lanes/notices` shows no new file.

## 6a. Task owners update their own status

- B: ask Claude to "mark T2 as in progress".
- [ ] Claude runs `lanes task status T2 in_progress` (it doesn't edit `plan.yaml`). Only T2's `status:` line changes (`git diff .lanes/plan.yaml`).
- B: `lanes sync`.
- [ ] The commit goes through the lane check, and **no** plan notice is written. On A, `lanes sync` and then `lanes status` show T2 `in_progress`.
- B: `lanes task status T1 done`.
- [ ] It refuses: T1 belongs to A.

## 6b. Plan changes notify the affected task

- A: `lanes sync`, then ask Claude to "move `src/ui/shared/**` into T1's `owns` in `.lanes/plan.yaml`" (add the glob to T1 and, if T2 has it, remove it there).
- [ ] Claude says a **plan notice** for friend was written. `lanes notices --all` on A doesn't show it (it isn't for A).
- A: `lanes sync`. B: `lanes sync`, then `lanes notices`.
- [ ] B sees a `plan` notice listing `~ T1 owns: +src/ui/shared/**`.

## 7. Safety nets

- B: ask Claude to "fix the typo in the newest file in `.lanes/notices/`".
- [ ] The edit is **blocked** with "written only by Lanes", and Claude suggests `lanes notices amend` (which only works for notices B wrote) or `lanes request`.
- B: make a code commit in B's lane (`src/ui/x.txt`), don't push it, then mark a notice read and run `lanes sync`.
- [ ] `lanes sync` lists the code commit and says "Not pushed". `lanes sync --include-code` then pushes both.

- B: from a terminal, without Claude, run `echo x > src/api/sneaky.py && git add -A && git commit -m test`.
- [ ] The commit is **blocked** by the pre-commit lane check, with the same message the guard gives. Clean up with `git restore --staged src/api/sneaky.py`, then delete the file.
- Either machine: break the plan on purpose (for example, delete `feature:`) and start `claude`.
- [ ] The session still works. There is a warning that the plan is invalid and the guard is OFF, and nothing is blocked.
- Restore the plan.

## 8. Handoff

- A: in a session, run `/lanes-handoff`.
- [ ] `.lanes/handoffs/T1-<timestamp>.md` is created with State, Next step, Failing tests and Gotchas filled in.
- [ ] A's next session (or anyone's session that owns T1) shows it under "Latest handoff for your task".

## Gate result

- [ ] Zero overwrites of each other's files during the whole run.
- [ ] A fresh session on each side could say what the other did without being told.

Notes and surprises:
