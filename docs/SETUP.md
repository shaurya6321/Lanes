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
2. Make sure git can reach GitHub over SSH. Run `ssh -T git@github.com`; it should say "Hi <your-username>!". If it doesn't, follow [GitHub's SSH key guide](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent).

## 3. Install the `lanes` CLI

```
git clone git@github.com:shaurya6321/Lanes.git
cd Lanes
uv tool install --editable .
lanes --version
```

If `lanes` isn't found, run `uv tool update-shell` and open a new terminal.

The install is "editable", so running `git pull` in the Lanes folder updates the `lanes` command too.

## 4. Tell Lanes who you are

Use your member `id` from the project's `.lanes/plan.yaml`.

- macOS: run `echo 'export LANES_USER=friend' >> ~/.zshrc`, then open a new terminal.
- Windows: run `setx LANES_USER friend`, then open a new terminal. Restart Cursor or VS Code too, so their built-in terminals pick up the variable.

Check it with `lanes whoami` from inside the project. If you skip this step, Lanes tries to match `git config user.email` against the member emails in the plan.

## 5. Open the project and start Claude Code

```
cd path/to/the-project
git pull
claude
```

The first time you open a repo, Claude Code asks whether you trust it. Say yes, or the project hooks won't run. The session should begin with a **Lanes briefing** that shows your tasks and owned files, and a status line saying `Lanes: briefing loaded for <you>`.

## Daily loop

1. **Pull** at the start: `git pull`. Notices and summaries arrive this way in Phase 0.
2. **Work** in your lane. If Claude needs something outside it, it runs `lanes request` instead of editing.
3. **Commit and push** often, including `.lanes/`. Your notices and summaries reach teammates when you push.
4. **Before you stop for the day**, run `/lanes-handoff` if someone else might pick up your task.

## Troubleshooting

| Symptom | What to check |
|---|---|
| No briefing at session start | Run `/hooks` inside Claude Code to confirm the four Lanes hooks are listed. Make sure `lanes --version` works in the same terminal, and check that you trusted the folder. |
| "can't tell who you are" | `LANES_USER` isn't set, or isn't a member id in `.lanes/plan.yaml`. Run `lanes whoami`. |
| "plan.yaml is invalid" | Run `lanes status` to see every error. Fix the plan, commit it and push. |
| A commit is blocked by the lane check | The commit touches someone else's files. Unstage them with `git restore --staged <path>` and ask the owner with `lanes request --file <path> "..."`. If the owner has agreed, bypass the check once with `git commit --no-verify`. |
| `lanes` works in one terminal but not in your editor | Restart the editor so it picks up the new `PATH` and `LANES_USER`. |
| Windows: the hook reports `/bin/sh` not found | Install Git for Windows. git uses its `sh.exe` to run the pre-commit hook. |

To debug a hook, run `claude --debug`. Hook input and output appear in the debug log.
