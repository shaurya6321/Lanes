# Claude Code hooks: notes for Lanes

- **Source:** https://code.claude.com/docs/en/hooks (https://docs.claude.com/en/docs/claude-code/hooks redirects there with a 301)
- **Read on:** 2026-11-05
- **Claude Code version tested against:** 2.1.318 (updated from 2.1.205 on 2026-11-05)

Re-check this page after every Claude Code update, then run `/hooks` in a session to confirm the hooks are still registered.

## Config shape

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [ { "type": "command", "command": "uv", "args": ["run", "..."], "timeout": 10 } ] }
    ]
  }
}
```

- The config nests three levels: event, then matcher group, then a list of handlers.
- **Command handlers:** `command` (required), plus optional `args`. When `args` is present, the command runs directly with no shell, so the same config works on macOS and Windows. `${CLAUDE_PROJECT_DIR}` is substituted, and it is also exported as an environment variable.
- **Matchers:** a string made only of letters, digits, `_`, `-`, spaces, `,` and `|` is matched as exact names separated by `|` or `,`. Any other character turns it into an unanchored JavaScript regex, so `Edit.*` would also match `NotebookEdit`.
- **SessionStart matchers:** `startup`, `resume`, `clear`, `compact`, `fork`. Lanes omits the matcher so it runs on all of them; after a compaction the briefing has to be added again.
- **Stop has no matcher.** A matcher on Stop is silently ignored.
- **`timeout` is in seconds.** The default is 600 for command hooks.
- **Parallel runs:** matching hooks for one event run in parallel, and identical handlers that appear in several settings files run only once.

## Input on stdin (JSON)

| Field(s) | Present on |
|---|---|
| `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode` (not on every event) | All events. Inside subagents, `agent_id` and `agent_type` are added. |
| `source` (`startup`, `resume`, `clear`, `compact`, `fork`), `model` (optional) | SessionStart |
| `tool_name`, `tool_input`, `tool_use_id` | PreToolUse |
| The PreToolUse fields, plus `tool_response` and `duration_ms` (optional) | PostToolUse |
| `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons` | Stop |

`tool_input` for the file-writing tools:

- **Write:** `file_path`, `content`
- **Edit:** `file_path`, `old_string`, `new_string`, `replace_all`
- **NotebookEdit:** `notebook_path`, `new_source`, `cell_id`, `cell_type`, `edit_mode`. The hooks page doesn't document this tool; these fields come from the tool's own schema in 2.1.318.
- **MultiEdit:** not documented anymore. Lanes still matches it and reads `file_path`, in case older versions send it.
- For Write, Edit and Read, `file_path` is always an absolute, normalized path. On Windows it uses backslashes.

## Exit codes and output

- **Exit 0:** stdout is parsed as JSON if it is valid JSON.
  - SessionStart is an exception: its plain-text stdout is added to Claude's context.
  - Claude never sees stderr from a hook that exits 0.
- **Exit 2:** blocks the action, and stderr becomes the reason.
  - PreToolUse: the tool call is blocked.
  - PostToolUse: stderr is shown to Claude; the tool has already run.
  - Stop: Claude is prevented from stopping.
  - SessionStart: stderr is shown to the user only.
- **Any other exit code:** a non-blocking error.
- **Universal JSON fields:** `continue`, `stopReason`, `systemMessage` (a warning shown to the user).
- **PreToolUse:** `hookSpecificOutput.permissionDecision` is `allow`, `deny`, `ask` or `defer`, with `permissionDecisionReason`.
  - With `deny`, the reason is shown to Claude.
  - **`allow` skips the normal permission prompt.** The lane guard therefore never returns `allow`. To allow an edit it exits 0 with no output, so the user's own permission settings still apply.
- **PostToolUse:** `hookSpecificOutput.additionalContext`, which is shown to Claude after the tool result.
- **SessionStart:** `hookSpecificOutput.additionalContext`.
- **Stop:** `decision: "block"` plus `reason` keeps Claude working. Lanes never blocks Stop.
- **Size cap:** `additionalContext`, `systemMessage` and plain stdout are each capped at 10,000 characters. Anything longer is replaced by a file path and a 2,000-character preview. The Lanes briefing is capped at about 1,500 tokens (6,000 characters), which fits.

## Differences from the brief

1. **Stop runs at the end of every turn, not once per session.**
   - The brief says to append a session summary on Stop. Appending every time would duplicate it.
   - Instead, `stop_summary` keeps one section per `session_id` in `.lanes/summaries/<member>-<date>.md` and rewrites that section on each Stop.
2. **Stop provides `last_assistant_message`.**
   - The "why" line is taken from the first lines of Claude's final reply, so no extra model call is needed and the hook stays deterministic.
   - There is no TODO left for a model-written summary.
3. **"Files touched" isn't taken from `git diff --name-only` alone.**
   - That would include changes that were already uncommitted before the session, and miss files committed during it.
   - Lanes records every path the edit tools touch, in `.lanes/local/sessions/<id>.json`. It adds files that became dirty after the session started, which catches files changed through Bash.
4. **`MultiEdit` is no longer documented** (see above). It is still matched, which does no harm.
5. **The brief says Claude Code hook timeouts are in milliseconds (section 3b). They are in seconds.**
6. **The brief says to register hooks as `uv run python hooks/<name>.py`.**
   - A relative path breaks when Claude's working directory is a subfolder.
   - This repo uses the no-shell form, which works on macOS and Windows: `"command": "uv", "args": ["run", "--quiet", "--project", "${CLAUDE_PROJECT_DIR}", "python", "${CLAUDE_PROJECT_DIR}/hooks/<name>.py"]`.
   - Repos that adopt Lanes run `lanes hook <name>` instead. `lanes` is installed once per machine with `uv tool install`, and the hook code ships inside the `lanes` package (`lanes/hooks/`).
7. **The lane guard can't see writes made through Bash** (`echo > f`, `sed -i`, `git checkout -- f`). The git pre-commit lane check (`lanes check --staged`) is the safety net for these.
8. **"Always allow writes inside `.lanes/`" conflicts with "a contract is changed only by its owner"**, because contracts live in `.lanes/contracts/`. Contract ownership is checked first; the rest of `.lanes/` is always allowed.
