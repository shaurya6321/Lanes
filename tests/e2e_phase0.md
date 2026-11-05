# Phase 0 end-to-end test (two machines)

This is a manual script for the Phase 0 gate. **A** is the rank-1 member (for example shaurya on macOS) and **B** is the rank-2 member (for example friend on Windows). Tick each box as you go, and write down anything surprising at the bottom.

## 0. Prepare a throwaway project (A)

```
mkdir lanes-e2e && cd lanes-e2e && git init -b main
lanes init --member shaurya
```

Edit `.lanes/plan.yaml`:

- Rename the member `teammate` to B's id, for example `friend`.
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

- A: `export LANES_USER=shaurya`. B: `setx LANES_USER friend`, then open a new terminal.
- B: run `git clone ...` then `cd lanes-e2e`.
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
- [ ] After the edit, Claude says a notice was written to `.lanes/notices/<...>-t1-example-api.md`, and then rewrites its `summary:` line into one precise sentence.
- [ ] The notice's front matter has `to_tasks: [T2]` and `from_rank: 1`.
- A: end the session. A turn that only answers a question is fine.
- [ ] `.lanes/summaries/shaurya-<date>.md` exists, with one section listing `.lanes/contracts/example-api.md`.
- A: `git add -A && git commit -m "Contract: add getItem" && git push`.
- [ ] The commit goes through, because the pre-commit lane check allows A's own files.

## 5. B's next session shows the notice

- B: `git pull`, then start a **new** `claude` session.
- [ ] The briefing has "Unread notices for you (1)", with A's summary and the getItem change lines.
- [ ] The briefing has "Recent session summaries (last 24h)", with A's session.
- [ ] Ask Claude "What did my teammate change?" It answers from the briefing without opening any files.
- B: `lanes notices --mark-read`, then commit and push. Then on A, run `git pull` and `lanes status`.
- [ ] `lanes status` shows `friend 0` unread.

## 6. Notices never flow upstream

- B: in `.lanes/plan.yaml`, add a contract `ui-events` with `file: .lanes/contracts/ui-events.md` and `owner: friend`. Add `implements: [ui-events]` to T2, and `uses: [ui-events]` to T1. That last part is deliberately the wrong direction. Commit.
- B: ask Claude to "create `.lanes/contracts/ui-events.md` describing a Clicked event."
- [ ] **No notice** is created for T1, because rank 2 never notifies rank 1. `ls .lanes/notices` shows no new file.

## 7. Safety nets

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
