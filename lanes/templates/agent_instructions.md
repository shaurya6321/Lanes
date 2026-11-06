<!-- lanes:begin (managed by `$lanes init`; edit lanes/templates/agent_instructions.md, not this block) -->
## Working with Lanes

This repo uses **Lanes**. Several people each run a coding agent on their own machine and share one plan in `.lanes/plan.yaml`. Each person's tasks own specific files, called their *lane*.

1. **Read the Lanes briefing first.** $briefing_hint It tells you who you are, your tasks, the files you own, what teammates are doing, and any unread notices.
2. **Stay inside your lane.** Only edit files your tasks own (run `$lanes whoami` to see them). You may also write anything in `.lanes/` except contracts you don't own, `.lanes/notices/` (only Lanes commands write notices) and `.lanes/plan.yaml` (only the plan owner edits it).
3. **If you need something outside your lane, don't edit it and don't work around it.** Run `$lanes request --file <path> "<what you need and why>"` to ask the owner, tell your human, and carry on with what you can do.
4. **The plan belongs to the plan owner.** To change the status of one of your own tasks, run `$lanes task status <TASK> <todo|in_progress|blocked|review|done>`; never edit `.lanes/plan.yaml` for that. For any other plan change, run `$lanes request --file .lanes/plan.yaml "<what and why>"`. Even as the plan owner, never change `owns`, `hub_files` or `contracts` without your human's explicit OK. To re-divide the work, the plan owner runs `/lanes-plan`: it only writes a proposal, and the human's `$lanes plan accept` is the OK.
5. **Changing a contract you own:** Lanes automatically writes a notice for downstream tasks. Replace its auto-generated summary with `$lanes notices amend <id> --summary "<one precise sentence>" --body "<3–6 lines>"`, covering renamed symbols, added or removed arguments, and changed types, in under about 150 tokens. Never edit files in `.lanes/notices/` directly; Lanes blocks it.
6. **Unread notices:** act on any that affect your task, then run `$lanes notices --mark-read`.
7. **Before you stop:** say in one or two sentences what you did and why in your final message. Lanes uses it for the session summary. $handoff_hint Teammates only see `.lanes/` changes after a sync, so suggest your human run `$lanes sync` (it commits `.lanes/` only, pulls and pushes, and never pushes code commits without `--include-code`). Don't run it yourself unless they ask.
8. **Unsure who owns something?** Run `$lanes status` or `$lanes check <path>`.

Never put secrets (keys, tokens, `.env` values) in notices, summaries or handoffs, and never read `.env` files.
<!-- lanes:end -->
