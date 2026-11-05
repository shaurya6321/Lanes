"""Normalize hook payloads and outputs across agents.

Hook logic only ever sees a `HookInput` and calls the output helpers below, so
adding an agent means adding one `from_<agent>()` and its output functions.

Claude Code formats follow https://code.claude.com/docs/en/hooks (see docs/HOOKS_NOTES.md).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import IO

FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


@dataclass
class HookInput:
    agent: str  # "claude" | "codex"
    event: str  # "SessionStart" | "PreToolUse" | "PostToolUse" | "Stop" | ...
    session_id: str | None = None
    cwd: str | None = None
    project_dir: str | None = None
    source: str | None = None  # SessionStart: startup | resume | clear | compact | fork
    tool_name: str | None = None
    tool_input: dict = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)  # files the tool writes
    last_message: str | None = None  # Stop: Claude's final reply text
    stop_hook_active: bool = False
    raw: dict = field(default_factory=dict)


def read_input(stream: IO[str] | None = None, env: dict | None = None) -> HookInput:
    env = os.environ if env is None else env
    text = (stream or sys.stdin).read()
    payload = json.loads(text) if text.strip() else {}
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be a JSON object")
    agent = (env.get("LANES_AGENT") or "claude").strip().lower()
    if agent == "codex":
        return from_codex(payload, env)
    return from_claude(payload, env)


# ---- Claude Code ---------------------------------------------------------------------


def from_claude(payload: dict, env: dict) -> HookInput:
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    paths: list[str] = []
    if payload.get("tool_name") in FILE_TOOLS:
        # Edit/Write/MultiEdit use file_path; NotebookEdit uses notebook_path.
        for key in ("file_path", "notebook_path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
    last = payload.get("last_assistant_message")
    return HookInput(
        agent="claude",
        event=str(payload.get("hook_event_name") or ""),
        session_id=payload.get("session_id"),
        cwd=payload.get("cwd"),
        project_dir=env.get("CLAUDE_PROJECT_DIR") or payload.get("cwd"),
        source=payload.get("source"),
        tool_name=payload.get("tool_name"),
        tool_input=tool_input,
        paths=paths,
        last_message=last if isinstance(last, str) else None,
        stop_hook_active=bool(payload.get("stop_hook_active")),
        raw=payload,
    )


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def deny(reason: str, agent: str = "claude") -> None:
    """Block a tool call; `reason` is shown to the model."""
    if agent != "claude":
        return _codex_todo()
    _emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


def add_context(event: str, text: str, system_message: str | None = None, agent: str = "claude") -> None:
    """Add text to the model's context (SessionStart, PostToolUse)."""
    if agent != "claude":
        return _codex_todo()
    out: dict = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
    if system_message:
        out["systemMessage"] = system_message
    _emit(out)


def warn_user(message: str, agent: str = "claude") -> None:
    """Show a warning to the human without blocking anything."""
    if agent != "claude":
        return _codex_todo()
    _emit({"systemMessage": message})


# ---- Codex (Phase 1) --------------------------------------------------------------------


def from_codex(payload: dict, env: dict) -> HookInput:
    """TODO(Phase 1, docs/BACKLOG.md): map Codex's `.codex/hooks.json` payload to HookInput.

    Known differences to handle: PreToolUse may fire only for Bash (not file
    patches), Codex can only deny (not allow/ask), and field names differ.
    """
    raise NotImplementedError("the Codex adapter is not built yet (Phase 1); see docs/BACKLOG.md")


def _codex_todo() -> None:
    raise NotImplementedError("Codex hook output is not built yet (Phase 1); see docs/BACKLOG.md")
