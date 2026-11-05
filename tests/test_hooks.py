"""Run each hook as a real subprocess with stdin shaped like the Claude Code docs examples."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import REPO, git, write_plan

from lanes.notices import list_notices, mark_read

SESSION = "abc123"


def payload(event: str, repo: Path, **extra) -> dict:
    base = {
        "session_id": SESSION,
        "transcript_path": "/Users/me/.claude/projects/x/abc123.jsonl",
        "cwd": str(repo),
        "permission_mode": "default",
        "hook_event_name": event,
    }
    base.update(extra)
    return base


def edit(repo: Path, rel: str, old: str = "a", new: str = "b", tool: str = "Edit", event: str = "PreToolUse") -> dict:
    tool_input = {"file_path": str(repo / rel), "old_string": old, "new_string": new, "replace_all": False}
    extra = {"tool_name": tool, "tool_input": tool_input, "tool_use_id": "toolu_01ABC123"}
    if event == "PostToolUse":
        extra["tool_response"] = {"filePath": str(repo / rel), "success": True}
        extra["duration_ms"] = 12
    return payload(event, repo, **extra)


def run_hook(name: str, data, repo: Path, env: dict, user: str | None = "shaurya", raw: str | None = None):
    env = dict(env, CLAUDE_PROJECT_DIR=str(repo))
    if user:
        env["LANES_USER"] = user
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(REPO / "hooks" / f"{name}.py")],
        input=raw if raw is not None else json.dumps(data),
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        timeout=20,
    )
    proc.elapsed = time.perf_counter() - started
    proc.json = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc


# ---- SessionStart ---------------------------------------------------------------------


def test_session_start_briefing(repo, clean_env):
    p = run_hook("session_start", payload("SessionStart", repo, source="startup", model="claude-opus-5-5"), repo, clean_env, user="friend")
    assert p.returncode == 0, p.stderr
    out = p.json["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    text = out["additionalContext"]
    assert "feature: checkout-v1" in text and "You are **friend**" in text
    assert "T2 [rank 2, todo] Checkout page UI" in text and "src/pages/checkout/**" in text
    assert "uses: cart-api (.lanes/contracts/cart-api.md)" in text
    assert "## Teammates" in text and "shaurya: T1" in text and "sam: T3" in text
    assert "Lanes: briefing loaded for friend (T2); 0 unread notice(s)." == p.json["systemMessage"]
    assert (repo / ".lanes" / "local" / "sessions" / f"{SESSION}.json").exists()


def test_session_start_shows_unread_notices_and_handoff(repo, clean_env):
    run_hook("post_tool_notice", edit(repo, ".lanes/contracts/cart-api.md", "addItem(sku, qty)", "addItem(sku, qty, note)", event="PostToolUse"), repo, clean_env)
    (repo / ".lanes" / "handoffs" / "T2-20261105T120000Z.md").write_text("---\ntask: T2\n---\n# Handoff: T2\n\n## Next step\nWire the pay button.\n")
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env, user="friend")
    text = p.json["hookSpecificOutput"]["additionalContext"]
    assert "## Unread notices for you (1)" in text and "about cart-api" in text and "+ addItem(sku, qty, note)" in text
    assert "## Latest handoff for your task" in text and "Wire the pay button." in text
    # sam (T3) also gets the cart-api notice (depends on T2 -> T1) but not T2's handoff
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env, user="sam")
    text = p.json["hookSpecificOutput"]["additionalContext"]
    assert "Unread notices for you (1)" in text and "Wire the pay button" not in text
    # the author (rank 1) never sees its own downstream notice
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env, user="shaurya")
    assert "Unread notices" not in p.json["hookSpecificOutput"]["additionalContext"]


def test_briefing_is_capped_and_drops_oldest_first(repo, clean_env):
    folder = repo / ".lanes" / "summaries"
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0)
    for i in range(80):
        ts = now - timedelta(minutes=10 * i)
        (folder / f"sam-{i:03d}.md").write_text(
            f"## {ts:%Y-%m-%d %H:%M} UTC · sam · T3\n<!-- lanes-session:s{i} updated:{ts:%Y-%m-%dT%H:%M:%SZ} -->\n"
            f"- Why: summary number {i} " + "x" * 120 + "\n- Files: a\n- Open: none\n"
        )
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env, user="friend")
    text = p.json["hookSpecificOutput"]["additionalContext"]
    assert len(text) <= 6000
    assert "summary number 0 " in text and "summary number 79 " not in text
    assert "older item(s) omitted" in text


def test_briefing_ignores_summaries_older_than_24h(repo, clean_env):
    (repo / ".lanes" / "summaries" / "sam-2026-01-01.md").write_text(
        "## 2026-01-01 10:00 UTC · sam · T3\n<!-- lanes-session:old updated:2026-01-01T10:00:00Z -->\n- Why: ancient\n"
    )
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env, user="friend")
    assert "ancient" not in p.json["hookSpecificOutput"]["additionalContext"]


def test_session_start_unknown_identity(repo, clean_env):
    git(repo, "config", "user.email", "stranger@example.com")
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env, user=None)
    text = p.json["hookSpecificOutput"]["additionalContext"]
    assert "can't tell who you are" in text and "guard is OFF" in text


def test_session_start_invalid_plan(repo, clean_env):
    (repo / ".lanes" / "plan.yaml").write_text("feature: x\n")
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env)
    assert p.returncode == 0 and "lane guard is OFF" in p.json["hookSpecificOutput"]["additionalContext"]


def test_hooks_do_nothing_without_lanes(tmp_path, clean_env):
    plain = tmp_path / "plain"
    plain.mkdir()
    for name, data in (
        ("session_start", payload("SessionStart", plain, source="startup")),
        ("pre_tool_guard", edit(plain, "x.py")),
        ("post_tool_notice", edit(plain, "x.py", event="PostToolUse")),
        ("stop_summary", payload("Stop", plain, stop_hook_active=False, last_assistant_message="hi")),
    ):
        p = run_hook(name, data, plain, clean_env)
        assert p.returncode == 0 and p.stdout == "", (name, p.stdout, p.stderr)


# ---- PreToolUse guard -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    ["src/api/cart/add.py", "src/types/cart.ts", "package.json", ".lanes/contracts/cart-api.md", ".lanes/handoffs/T1-x.md", ".lanes/summaries/x.md"],
)
def test_guard_allows_own_lane_silently(repo, clean_env, rel):
    p = run_hook("pre_tool_guard", edit(repo, rel), repo, clean_env)
    assert p.returncode == 0 and p.stdout == ""  # never an explicit "allow"


@pytest.mark.parametrize(
    "rel, owner",
    [("src/pages/checkout/index.tsx", "friend"), (".lanes/contracts/checkout-events.md", "friend"), ("src/emails/receipt.py", "sam")],
)
def test_guard_denies_other_lanes(repo, clean_env, rel, owner):
    p = run_hook("pre_tool_guard", edit(repo, rel), repo, clean_env)
    out = p.json["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"
    assert f"belongs to {owner}" in out["permissionDecisionReason"]
    assert "lanes request --file" in out["permissionDecisionReason"]


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
@pytest.mark.parametrize(
    "rel", [".lanes/notices/20261105T120000Z-t1-cart-api.md", ".lanes/notices/read-by/friend.txt", ".lanes/notices/new.md", ".Lanes/Notices/x.md"]
)
def test_guard_blocks_direct_notice_edits(repo, clean_env, rel, tool):
    """Notices are written only by `lanes request`, `lanes notices` and the hooks, even by their author."""
    p = run_hook("pre_tool_guard", edit(repo, rel, tool=tool), repo, clean_env)
    out = p.json["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "written only by Lanes" in out["permissionDecisionReason"] and "lanes notices amend" in out["permissionDecisionReason"]


def test_guard_blocks_notebook_edit_in_notices(repo, clean_env):
    data = payload("PreToolUse", repo, tool_name="NotebookEdit", tool_use_id="t",
                   tool_input={"notebook_path": str(repo / ".lanes/notices/x.ipynb"), "new_source": "x", "cell_id": "c1"})
    assert run_hook("pre_tool_guard", data, repo, clean_env).json["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_contract_notice_tells_claude_to_amend_not_edit(repo, clean_env):
    p = run_hook("post_tool_notice", edit(repo, ".lanes/contracts/cart-api.md", "a", "b", event="PostToolUse"), repo, clean_env)
    (n,) = list_notices(repo)
    text = p.json["hookSpecificOutput"]["additionalContext"]
    assert f"lanes notices amend {n.id} --summary" in text and "don't edit the file" in text


def test_guard_denies_unowned_file(repo, clean_env):
    p = run_hook("pre_tool_guard", edit(repo, "README.md", tool="Write"), repo, clean_env)
    assert p.json["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "no task" in p.json["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_covers_notebook_edit(repo, clean_env):
    data = payload("PreToolUse", repo, tool_name="NotebookEdit", tool_use_id="t",
                   tool_input={"notebook_path": str(repo / "src/emails/a.ipynb"), "new_source": "x", "cell_id": "c1"})
    assert run_hook("pre_tool_guard", data, repo, clean_env).json["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_guard_ignores_files_outside_repo(repo, clean_env, tmp_path):
    data = payload("PreToolUse", repo, tool_name="Write", tool_use_id="t", tool_input={"file_path": str(tmp_path / "elsewhere.txt"), "content": "x"})
    assert run_hook("pre_tool_guard", data, repo, clean_env).stdout == ""


def test_guard_fails_open_on_invalid_plan_and_warns_once(repo, clean_env):
    (repo / ".lanes" / "plan.yaml").write_text("feature: [broken\n")
    first = run_hook("pre_tool_guard", edit(repo, "src/emails/x.py"), repo, clean_env)
    assert first.returncode == 0 and "lane guard is OFF" in first.json["systemMessage"]
    assert "hookSpecificOutput" not in first.json
    second = run_hook("pre_tool_guard", edit(repo, "src/emails/x.py"), repo, clean_env)
    assert second.stdout == ""


def test_guard_fails_open_for_non_members(repo, clean_env):
    p = run_hook("pre_tool_guard", edit(repo, "src/emails/x.py"), repo, clean_env, user="ghost")
    assert "not a member" in p.json["systemMessage"] and "hookSpecificOutput" not in p.json


def test_guard_survives_garbage_input(repo, clean_env):
    p = run_hook("pre_tool_guard", None, repo, clean_env, raw="not json{")
    assert p.returncode == 0 and p.stdout == ""


def test_guard_via_lanes_cli_entry_point(repo, clean_env):
    env = dict(clean_env, CLAUDE_PROJECT_DIR=str(repo), LANES_USER="shaurya")
    proc = subprocess.run([sys.executable, "-m", "lanes.cli", "hook", "pre-tool-guard"], input=json.dumps(edit(repo, "src/emails/x.py")),
                          capture_output=True, text=True, cwd=repo, env=env)
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# ---- PostToolUse notices ----------------------------------------------------------------


def test_contract_edit_creates_notice_for_higher_ranks_only(repo, clean_env):
    p = run_hook("post_tool_notice", edit(repo, ".lanes/contracts/cart-api.md", "addItem(sku: str, qty: int)", "addItem(sku: str, qty: int, note: str = '')", event="PostToolUse"), repo, clean_env)
    ctx = p.json["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse" and "T2 (friend), T3 (sam)" in ctx["additionalContext"]
    (n,) = list_notices(repo)
    assert n.to_tasks == ["T2", "T3"] and n.contract == "cart-api" and n.from_rank == 1
    assert "+ addItem(sku: str, qty: int, note: str = '')" in n.body


def test_rank2_contract_edit_never_notifies_rank1(repo, clean_env):
    run_hook("post_tool_notice", edit(repo, ".lanes/contracts/checkout-events.md", "OrderPlaced(id)", "OrderPlaced(id, total)", event="PostToolUse"), repo, clean_env, user="friend")
    (n,) = list_notices(repo)
    assert n.to_tasks == ["T3"] and "T1" not in n.to_tasks and "shaurya" not in n.to_members


def test_repeat_edits_in_one_session_update_the_same_notice(repo, clean_env):
    run_hook("post_tool_notice", edit(repo, ".lanes/contracts/cart-api.md", "a", "b", event="PostToolUse"), repo, clean_env)
    p = run_hook("post_tool_notice", edit(repo, ".lanes/contracts/cart-api.md", "c", "d", event="PostToolUse"), repo, clean_env)
    assert len(list_notices(repo)) == 1 and "was updated" in p.json["hookSpecificOutput"]["additionalContext"]


def test_hub_write_creates_notice(repo, clean_env):
    data = payload("PostToolUse", repo, tool_name="Write", tool_use_id="t",
                   tool_input={"file_path": str(repo / "package.json"), "content": '{"deps": {"react": "19"}}'},
                   tool_response={"filePath": str(repo / "package.json"), "type": "create"})
    run_hook("post_tool_notice", data, repo, clean_env)
    (n,) = list_notices(repo)
    assert n.file == "package.json" and n.to_tasks == ["T2", "T3"]


def test_ordinary_edit_creates_no_notice(repo, clean_env):
    p = run_hook("post_tool_notice", edit(repo, "src/api/cart/add.py", event="PostToolUse"), repo, clean_env)
    assert p.stdout == "" and list_notices(repo) == []
    state = json.loads((repo / ".lanes" / "local" / "sessions" / f"{SESSION}.json").read_text())
    assert state["touched"] == ["src/api/cart/add.py"]


def test_top_rank_contract_edit_has_no_recipients(repo, clean_env, plan_dict):
    plan_dict["contracts"].append({"id": "email-tpl", "file": ".lanes/contracts/email-tpl.md", "owner": "sam"})
    plan_dict["tasks"][2]["implements"] = ["email-tpl"]
    plan_dict["tasks"][0]["uses"] = ["checkout-events", "email-tpl"]  # lower rank "uses" it: still never notified
    write_plan(repo, plan_dict)
    p = run_hook("post_tool_notice", edit(repo, ".lanes/contracts/email-tpl.md", event="PostToolUse"), repo, clean_env, user="sam")
    assert p.stdout == "" and list_notices(repo) == []


def _plan_edit(repo, plan_dict, user, env):
    write_plan(repo, plan_dict)
    return run_hook("post_tool_notice", edit(repo, ".lanes/plan.yaml", "x", "y", event="PostToolUse"), repo, env, user=user)


def test_plan_owner_editing_ownership_sends_plan_notice(repo, clean_env, plan_dict):
    plan_dict["tasks"][1]["owns"] = ["src/pages/checkout/**"]
    plan_dict["tasks"][0]["owns"].append("src/components/checkout/**")
    p = _plan_edit(repo, plan_dict, "shaurya", clean_env)
    (n,) = list_notices(repo)
    assert n.kind == "plan" and n.to_tasks == ["T2"]
    text = p.json["hookSpecificOutput"]["additionalContext"]
    assert "plan notice for friend" in text and f"lanes notices amend {n.id}" in text
    p = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env, user="friend")
    assert "-src/components/checkout/**" in p.json["hookSpecificOutput"]["additionalContext"]


def test_non_owner_editing_ownership_is_warned_not_broadcast(repo, clean_env, plan_dict):
    plan_dict["tasks"][0]["owns"] = ["src/api/cart/**"]
    p = _plan_edit(repo, plan_dict, "friend", clean_env)
    assert list_notices(repo) == []
    assert "only the plan owner (shaurya)" in p.json["hookSpecificOutput"]["additionalContext"]


def test_plan_status_edit_is_silent(repo, clean_env, plan_dict):
    plan_dict["tasks"][1]["status"] = "in_progress"
    p = _plan_edit(repo, plan_dict, "friend", clean_env)
    assert p.stdout == "" and list_notices(repo) == []


# ---- Stop summary --------------------------------------------------------------------------


def stop(repo, message: str, active: bool = False) -> dict:
    return payload("Stop", repo, stop_hook_active=active, last_assistant_message=message, background_tasks=[], session_crons=[])


def test_stop_writes_and_upserts_one_section_per_session(repo, clean_env):
    run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env)
    (repo / "src" / "api" / "cart").mkdir(parents=True)
    (repo / "src" / "api" / "cart" / "add.py").write_text("def add(): ...\n")
    run_hook("post_tool_notice", edit(repo, "src/api/cart/add.py", event="PostToolUse"), repo, clean_env)
    (repo / "src" / "api" / "cart" / "bash_made.py").write_text("x\n")  # e.g. created via Bash, never seen by PostToolUse

    msg = "**Added** `add()` to the cart API and wired it up.\n\n```py\ncode\n```\nShould totals include tax?"
    p = run_hook("stop_summary", stop(repo, msg), repo, clean_env)
    assert p.returncode == 0 and p.stdout == ""  # never blocks stopping
    files = list((repo / ".lanes" / "summaries").glob("shaurya-*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "· shaurya · T1" in text and "- Why: Added add() to the cart API and wired it up." in text
    assert "src/api/cart/add.py" in text and "src/api/cart/bash_made.py" in text
    assert "- Open: Should totals include tax?" in text

    run_hook("stop_summary", stop(repo, "Also added tests."), repo, clean_env)
    text = files[0].read_text()
    assert text.count("lanes-session:abc123") == 1 and "Also added tests." in text


def test_stop_skips_pure_chat_turns(repo, clean_env):
    run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env)
    run_hook("stop_summary", stop(repo, "Here is an explanation."), repo, clean_env)
    assert list((repo / ".lanes" / "summaries").glob("*.md")) == []


def test_stop_ignores_files_dirty_before_session(repo, clean_env):
    (repo / "src" / "api" / "cart").mkdir(parents=True)
    (repo / "src" / "api" / "cart" / "old.py").write_text("pre-existing change\n")
    run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env)
    (repo / "src" / "api" / "cart" / "new.py").write_text("x\n")
    run_hook("stop_summary", stop(repo, "Did a thing."), repo, clean_env)
    text = next((repo / ".lanes" / "summaries").glob("*.md")).read_text()
    assert "new.py" in text and "old.py" not in text


def test_stop_redacts_secrets(repo, clean_env):
    run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env)
    (repo / "src" / "api" / "cart").mkdir(parents=True)
    (repo / "src" / "api" / "cart" / "k.py").write_text("x\n")
    run_hook("stop_summary", stop(repo, "Set the key to sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx in config."), repo, clean_env)
    text = next((repo / ".lanes" / "summaries").glob("*.md")).read_text()
    assert "sk-ant-api03" not in text and "[REDACTED]" in text


def test_summary_shows_up_in_teammates_briefing(repo, clean_env):
    run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, clean_env)
    (repo / "src" / "api" / "cart").mkdir(parents=True)
    (repo / "src" / "api" / "cart" / "add.py").write_text("x\n")
    run_hook("stop_summary", stop(repo, "Implemented addItem with a note field."), repo, clean_env)
    data = payload("SessionStart", repo, source="startup", session_id="friend-session")
    p = run_hook("session_start", data, repo, clean_env, user="friend")
    text = p.json["hookSpecificOutput"]["additionalContext"]
    assert "## Recent session summaries (last 24h)" in text and "Implemented addItem with a note field." in text


# ---- git pre-commit ------------------------------------------------------------------------


def precommit(repo, clean_env, user="shaurya"):
    env = dict(clean_env, LANES_USER=user)
    return subprocess.run([sys.executable, str(REPO / "hooks" / "pre_commit.py")], capture_output=True, text=True, cwd=repo, env=env)


def test_pre_commit_blocks_out_of_lane_files(repo, clean_env):
    (repo / "src" / "emails").mkdir(parents=True)
    (repo / "src" / "emails" / "x.py").write_text("x")
    git(repo, "add", "-A")
    p = precommit(repo, clean_env)
    assert p.returncode == 1 and "src/emails/x.py" in p.stderr and "belongs to sam" in p.stderr and "--no-verify" in p.stderr


def test_pre_commit_allows_own_lane_and_lanes_state(repo, clean_env):
    (repo / "src" / "api" / "cart").mkdir(parents=True)
    (repo / "src" / "api" / "cart" / "x.py").write_text("x")
    (repo / ".lanes" / "notices" / "n.md").write_text("x")
    git(repo, "add", "-A")
    assert precommit(repo, clean_env).returncode == 0


def test_pre_commit_skips_merges(repo, clean_env):
    (repo / "src" / "emails").mkdir(parents=True)
    (repo / "src" / "emails" / "x.py").write_text("x")
    git(repo, "add", "-A")
    head = git(repo, "rev-parse", "HEAD").strip()
    (repo / ".git" / "MERGE_HEAD").write_text(head + "\n")
    p = precommit(repo, clean_env)
    assert p.returncode == 0 and "merge commit" in p.stderr


def test_hooks_are_fast(repo, clean_env):
    """Python startup + work, excluding uv's own launcher overhead (measured separately)."""
    worst = 0.0
    for name, data in (
        ("session_start", payload("SessionStart", repo, source="startup")),
        ("pre_tool_guard", edit(repo, "src/emails/x.py")),
        ("post_tool_notice", edit(repo, "src/api/cart/a.py", event="PostToolUse")),
        ("stop_summary", stop(repo, "done")),
    ):
        worst = max(worst, run_hook(name, data, repo, clean_env).elapsed)
    assert worst < 1.0, f"slowest hook took {worst:.3f}s"
