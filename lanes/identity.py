"""Who am I? `LANES_USER` wins; otherwise map `git config user.email` to a member."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .plan import Plan


@dataclass(frozen=True)
class Identity:
    member_id: str | None  # None means "not a member of this plan"
    source: str  # "LANES_USER" | "git user.email" | "none"
    detail: str  # human-readable explanation, safe to show


def git_email(root: Path | str | None = None, scope: str | None = None) -> str | None:
    """The effective `user.email` (repo-local config wins over global), or one scope's value."""
    try:
        out = subprocess.run(
            ["git", "config", *([scope] if scope else []), "user.email"],
            cwd=root or None,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    email = out.stdout.strip()
    return email or None


def resolve(plan: Plan, root: Path | str | None = None, env: dict | None = None) -> Identity:
    env = os.environ if env is None else env
    ids = ", ".join(m.id for m in plan.members)

    wanted = (env.get("LANES_USER") or "").strip()
    if wanted:
        for m in plan.members:
            if m.id.lower() == wanted.lower():
                return Identity(m.id, "LANES_USER", f"LANES_USER={wanted}")
        return Identity(None, "LANES_USER", f"LANES_USER={wanted} is not a member of the plan (members: {ids})")

    email = git_email(root or plan.root)
    if email:
        for m in plan.members:
            if m.email and m.email.lower() == email.lower():
                return Identity(m.id, "git user.email", f"git user.email={email}")
        known = ", ".join(f"{m.id} <{m.email}>" if m.email else f"{m.id} (no email)" for m in plan.members)
        where = "this repo's git config" if git_email(root or plan.root, scope="--local") == email else "your global git config"
        return Identity(
            None,
            "git user.email",
            f"git user.email {email} (from {where}) doesn't match any member email in .lanes/plan.yaml "
            f"(members: {known}). Fix: ask the plan owner to put your email in `members`, "
            f"or set it for this repo with `git config user.email <the email in the plan>`, "
            f"or set LANES_USER to your member id ({ids}).",
        )
    return Identity(
        None,
        "none",
        f"LANES_USER is not set and git has no user.email. Run `git config user.email <your email in .lanes/plan.yaml>` "
        f"in this repo, or set LANES_USER to one of: {ids}.",
    )
