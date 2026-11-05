<!-- lanes:begin (managed by `lanes init`; edit lanes/templates/agent_instructions.md, not this block) -->
## Working with Lanes

This repo uses **Lanes**. Several people each run a coding agent on their own machine and share one plan in `.lanes/plan.yaml`. Each person's tasks own specific files, called their *lane*.

1. **Read the Lanes briefing first.** $briefing_hint It tells you who you are, your tasks, the files you own, what teammates are doing, and any unread notices.
2. **Stay inside your lane.** Only edit files your tasks own (run `lanes whoami` to see them). You may also write anything in `.lanes/` except contracts you don't own.
3. **If you need something outside your lane, don't edit it and don't work around it.** Run `lanes request --file <path> "<what you need and why>"` to ask the owner, tell your human, and carry on with what you can do.
4. **Don't change who owns what.** Never edit `owns`, `hub_files` or `contracts` in `.lanes/plan.yaml` without your human's explicit OK.
5. **Changing a contract you own:** Lanes automatically writes a notice for downstream tasks. Replace the notice's auto-generated `summary:` line with one precise sentence. Keep its body to 3–6 lines covering renamed symbols, added or removed arguments, and changed types, and keep it under about 150 tokens.
6. **Unread notices:** act on any that affect your task, then run `lanes notices --mark-read`.
7. **Before you stop:** say in one or two sentences what you did and why in your final message. Lanes uses it for the session summary. $handoff_hint
8. **Unsure who owns something?** Run `lanes status` or `lanes check <path>`.

Never put secrets (keys, tokens, `.env` values) in notices, summaries or handoffs, and never read `.env` files.
<!-- lanes:end -->
