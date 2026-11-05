# Teammate setup

This takes about 15 minutes. Do it once on each machine. Every command is given for both macOS (zsh) and Windows (PowerShell).

## 1. Install the tools

| Tool | macOS | Windows |
|---|---|---|
| Git | `xcode-select --install` or `brew install git` | Install [Git for Windows](https://git-scm.com/download/win). Claude Code and the git hook both need it. |
| uv | `brew install uv` | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Claude Code | `curl -fsSL https://claude.ai/install.sh \| bash` | `winget install Anthropic.ClaudeCode` |
| Editor | Cursor or VS Code | Cursor or VS Code |

You don't need to install Python yourself, because uv downloads it. Then check that everything is there:

```
git --version
uv --version
claude --version      # 2.1.318 or newer; update with `claude update`
```

## 2. Get access to the repo

1. Ask Shaurya to add your GitHub account as a collaborator on `shaurya6321/Lanes`, then accept the invite email.
2. Make sure git can reach GitHub. With https (the default on Windows), Git for Windows signs you in through the browser the first time. With SSH, run `ssh -T git@github.com`; it should say "Hi <your-username>!". If it doesn't, follow [GitHub's SSH key guide](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent).

## 3. Get Lanes (nothing global)

In a team project, Lanes is a **dev dependency of the project**, so there's nothing to install on your machine beyond uv. `uv sync` (step 5) puts it in the project's own `.venv`, and you run it as `uv run lanes ...`. Nothing goes on your PATH, and Lanes doesn't run in your other projects.

While the Lanes repo is private, `uv sync` downloads it through git as you. On Windows, Git for Windows opens a browser sign-in the first time. If https fails but `ssh -T git@github.com` works, ask the project owner to switch the dependency URL to `git+ssh://git@github.com/shaurya6321/Lanes.git`.

**Optional: global install.** If you want `lanes` on your PATH for every repo, run `uv tool install git+https://github.com/shaurya6321/Lanes` (update with `uv tool upgrade lanes`). If `lanes` isn't found afterwards, run `uv tool update-shell` and open a new terminal. Only if you're developing Lanes itself: clone it and run `uv tool install --editable .` in the clone.

**Commands in this guide** are written `lanes ...`. In a repo-only project, type `uv run lanes ...` instead. Claude is told the right spelling automatically.

## 4. Tell Lanes who you are

Lanes matches `git config user.email` (in that repo) against `members[].email` in the project's `.lanes/plan.yaml`. If your email is in the plan, there's nothing to do. Check with `lanes whoami` from inside the project.

If it doesn't match, either ask the plan owner to put your git email in the plan, or set `LANES_USER` to your member `id`:

- macOS: run `echo 'export LANES_USER=friend' >> ~/.zshrc`, then open a new terminal.
- Windows: run `setx LANES_USER friend`, then open a new terminal. Restart Cursor or VS Code too, so their built-in terminals pick up the variable.

## 5. Open the project and start Claude Code

```
cd path/to/the-project
uv sync                 # repo-only projects: installs Lanes into the project's .venv
uv run lanes init       # once per clone: installs the git commit check (git hooks aren't cloned); changes nothing else
uv run lanes sync
claude
```

(With a global install, drop `uv sync` and the `uv run` prefix.)

The first time you open a repo, Claude Code asks whether you trust it. Say yes, or the project hooks won't run. The session should begin with a **Lanes briefing** that shows your tasks and owned files, and a status line saying `Lanes: briefing loaded for <you>`.

## Daily loop

1. **Sync** at the start: `lanes sync`. In Phase 0, notices, summaries and handoffs travel through git, so this is how you receive them.
2. **Work** in your lane. If Claude needs something outside it, it runs `lanes request` instead of editing. Update your task's status with `lanes task status <TASK> in_progress` (later `review` or `done`); only the plan owner edits `plan.yaml` directly.
3. **Commit your code** as usual with `git commit`.
4. **Sync** when you finish a chunk of work and before you stop: `lanes sync`. This is how teammates receive your notices, requests, read marks and summaries.
5. **Before you stop for the day**, run `/lanes-handoff` if someone else might pick up your task, then `lanes sync`.

### What `lanes sync` does

1. Commits `.lanes/` **only** (`git commit -- .lanes`). Code you've staged stays staged, and the lane check still runs on the commit.
2. Runs `git pull --rebase --autostash`. Uncommitted work is stashed and restored, so it never blocks the pull. That matters because Lanes rewrites your session summary after every Claude reply. If the pull hits a conflict, the rebase is undone, your branch stays as it was, and the conflicting files are listed.
3. Pushes, **only if every unpushed commit touches `.lanes/` alone**. If you have unpushed code commits, it lists them and stops (exit code 3). Run `lanes sync --include-code` to push them too, or `git push` yourself when the code is ready.

Phase 0 assumes the whole team works on **one shared branch** (usually `main`). Notices only reach teammates who pull the same branch, and `lanes sync` warns if you're on a different branch from the remote's default.

If you run `git pull --rebase` yourself instead of `lanes sync`, it refuses whenever your working tree is dirty, which with Lanes is after almost every Claude reply. Either use `lanes sync`, or turn on autostash for this repo with `git config rebase.autoStash true`. A plain `git pull` (merge) isn't affected.

## Troubleshooting

| Symptom | What to check |
|---|---|
| No briefing at session start | Run `/hooks` inside Claude Code to confirm the four Lanes hooks are listed. Make sure `uv run lanes --version` (repo-only) or `lanes --version` (global) works in the same folder, and check that you trusted the folder. |
| `uv run lanes`: "Failed to spawn: `lanes`" | Run `uv sync` in the project first. Until you do, the hooks and the commit check are skipped (fail-open) rather than blocking you. |
| "only its owner can change its status" or a blocked edit of `plan.yaml` | Only the plan owner edits `.lanes/plan.yaml`. Change your own task's status with `lanes task status <TASK> <status>`, and ask the plan owner for anything else with `lanes request --file .lanes/plan.yaml "..."`. |
| "can't tell who you are" or "doesn't match any member email" | Your `git config user.email` in this repo isn't in `members` in `.lanes/plan.yaml`, and `LANES_USER` isn't set. Run `lanes whoami`; the message says which email it saw and how to fix it. |
| "plan.yaml is invalid" | Run `lanes status` to see every error. Fix the plan, then `lanes sync`. |
| A teammate didn't get your notice | You haven't run `lanes sync` since writing it, they haven't synced since, or you're on different branches. |
| `lanes sync` says "Not pushed: … contain code" | You have unpushed code commits. Push them when ready with `lanes sync --include-code` (or `git push`). The `.lanes/` commit is already made and will go with them. |
| `lanes sync` stops on a conflict | Nothing was changed. Run `git pull --rebase --autostash`, fix the listed files, `git rebase --continue`, then `lanes sync` again. |
| "cannot pull with rebase: You have unstaged changes" | You ran `git pull --rebase` directly. Use `lanes sync`, or `git config rebase.autoStash true`. |
| A commit is blocked by the lane check | The commit touches someone else's files. Unstage them with `git restore --staged <path>` and ask the owner with `lanes request --file <path> "..."`. If the owner has agreed, bypass the check once with `git commit --no-verify`. |
| `lanes` works in one terminal but not in your editor | Restart the editor so it picks up the new `PATH` and `LANES_USER`. |
| Windows: the hook reports `/bin/sh` not found | Install Git for Windows. git uses its `sh.exe` to run the pre-commit hook. |

To debug a hook, run `claude --debug`. Hook input and output appear in the debug log.
