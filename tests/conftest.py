"""Shared fixtures: a throwaway git repo with a three-task Lanes plan."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent

# T1 (rank 1) -> T2 (rank 2) -> T3 (rank 3).
# T1 deliberately `uses` checkout-events (owned by T2's owner) so tests can prove
# a rank-2 contract change never notifies rank 1.
PLAN = {
    "feature": "checkout-v1",
    "updated": "2026-11-05",
    "members": [
        {"id": "shaurya", "email": "shaurya@example.com"},
        {"id": "friend", "email": "friend@example.com"},
        {"id": "sam", "email": "sam@example.com"},
    ],
    "hub_files": [
        {"path": "package.json", "owner": "shaurya"},
        {"path": "src/types/**", "owner": "shaurya"},
    ],
    "contracts": [
        {"id": "cart-api", "file": ".lanes/contracts/cart-api.md", "owner": "shaurya"},
        {"id": "checkout-events", "file": ".lanes/contracts/checkout-events.md", "owner": "friend"},
    ],
    "tasks": [
        {
            "id": "T1", "title": "Cart API + types", "rank": 1, "owner": "shaurya",
            "owns": ["src/api/cart/**", "src/types/**"], "implements": ["cart-api"],
            "uses": ["checkout-events"], "depends_on": [], "status": "in_progress",
        },
        {
            "id": "T2", "title": "Checkout page UI", "rank": 2, "owner": "friend",
            "owns": ["src/pages/checkout/**", "src/components/checkout/**"],
            "implements": ["checkout-events"], "uses": ["cart-api"], "depends_on": ["T1"], "status": "todo",
        },
        {
            "id": "T3", "title": "Order emails", "rank": 3, "owner": "sam",
            "owns": ["src/emails/**"], "uses": ["checkout-events"], "depends_on": ["T2"], "status": "todo",
        },
    ],
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def write_plan(root: Path, plan: dict | None = None) -> None:
    (root / ".lanes").mkdir(exist_ok=True)
    (root / ".lanes" / "plan.yaml").write_text(yaml.safe_dump(plan or PLAN, sort_keys=False), encoding="utf-8")


@pytest.fixture
def plan_dict() -> dict:
    import copy

    return copy.deepcopy(PLAN)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "shaurya@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    write_plan(root)
    for sub in ("contracts", "notices", "handoffs", "summaries"):
        (root / ".lanes" / sub).mkdir(parents=True, exist_ok=True)
    (root / ".lanes" / "contracts" / "cart-api.md").write_text("# cart-api\n\naddItem(sku: str, qty: int) -> Cart\n")
    (root / ".lanes" / "contracts" / "checkout-events.md").write_text("# checkout-events\n\nOrderPlaced(id)\n")
    (root / ".gitignore").write_text(".lanes/local/\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    monkeypatch.delenv("LANES_USER", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return root


@pytest.fixture
def clean_env() -> dict:
    """Environment for hook subprocesses, without the caller's Lanes identity."""
    env = {k: v for k, v in os.environ.items() if k not in ("LANES_USER", "CLAUDE_PROJECT_DIR", "LANES_AGENT")}
    env["PYTHONPATH"] = str(REPO)
    return env
