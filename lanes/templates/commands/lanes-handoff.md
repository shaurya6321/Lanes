---
description: Write a Lanes handoff note so the next session (anyone's) can continue without re-explaining
argument-hint: "[task-id]"
allowed-tools: Bash($lanes handoff:*), Bash($lanes whoami:*), Bash(git status:*), Bash(git log:*), Bash(git diff:*)
---
Write a handoff note for task $ARGUMENTS. If no task id was given, use my in-progress task.

1. Run `$lanes handoff $ARGUMENTS`. It creates `.lanes/handoffs/<task>-<timestamp>.md` from the template, fills in the task, branch and changed files, and prints the path.
2. To ground yourself, run `git status --short` and `git log --oneline -5`. If the test suite is quick, run it so the "Failing tests" section is accurate.
3. Fill in each section of the new file, replacing the HTML comments:
   - **State:** what works now and what is half-done.
   - **Next step:** the single next thing to do.
   - **Failing tests:** test names plus a one-line cause each, or "none".
   - **Gotchas:** surprises, decisions made, and things not to touch.
4. Keep it under 25 lines, facts only. No secrets, tokens or `.env` values.
5. Reply with the file path and remind me to run `$lanes sync` so my teammates see it.
