"""Shared hook plumbing: find the repo, load the plan, resolve identity, keep session state.

Hooks FAIL OPEN: a missing/invalid plan, unknown identity, or an unexpected
error never blocks the user's session. They warn instead.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..identity import resolve
from ..paths import find_root
from ..plan import Plan, PlanError, load_plan
from .adapters import HookInput, read_input, warn_user

LOCAL_SESSIONS = Path(".lanes") / "local" / "sessions"


@dataclass
class HookCtx:
    root: Path
    plan: Plan | None
    plan_error: str | None
    member: str | None
    identity_detail: str


def load_ctx(inp: HookInput) -> HookCtx | None:
    """None when this repo doesn't use Lanes (no .lanes/ dir): hooks then do nothing."""
    root = None
    for start in (inp.project_dir, inp.cwd):
        if start:
            root = find_root(start)
            if root:
                break
    if root is None:
        return None
    try:
        plan = load_plan(root)
    except PlanError as exc:
        return HookCtx(root, None, "; ".join(exc.errors), None, "")
    ident = resolve(plan, root)
    return HookCtx(root, plan, None, ident.member_id, ident.detail)


def run_hook(body: Callable[[HookInput], int]) -> int:
    """Parse stdin, run `body`, and turn any crash into a visible warning plus exit 0."""
    try:
        inp = read_input()
    except Exception as exc:  # malformed payload: never block
        print(f"lanes: could not read hook input: {exc}", file=sys.stderr)
        return 0
    try:
        return body(inp)
    except Exception as exc:  # pragma: no cover - defensive
        traceback.print_exc(file=sys.stderr)
        try:
            warn_user(f"Lanes {inp.event or 'hook'} failed and was skipped (fail-open): {exc}", agent=inp.agent)
        except Exception:
            pass
        return 0


# ---- per-session local state (.lanes/local/, gitignored) ---------------------------------


def _state_path(root: Path, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:80] or "unknown"
    return root / LOCAL_SESSIONS / f"{safe}.json"


def load_state(root: Path, session_id: str | None) -> dict | None:
    if not session_id:
        return None
    try:
        return json.loads(_state_path(root, session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(root: Path, session_id: str | None, state: dict) -> None:
    if not session_id:
        return
    path = _state_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def warn_once(root: Path, session_id: str | None, key: str, message: str, agent: str) -> None:
    state = load_state(root, session_id) or {}
    warned = set(state.get("warned", []))
    if key in warned:
        return
    warned.add(key)
    state["warned"] = sorted(warned)
    save_state(root, session_id, state)
    warn_user(message, agent=agent)


def is_shared_lanes_state(rel: str) -> bool:
    """Lanes bookkeeping that shouldn't count as 'files touched' (contracts do count)."""
    return rel.startswith(".lanes/") and not rel.startswith(".lanes/contracts/")
