"""plan.yaml belongs to the plan owner; task owners change status via `lanes task status`."""

from __future__ import annotations

import subprocess
import sys

import pytest
import yaml
from conftest import REPO, git, write_plan

from lanes.cli import main
from lanes.notices import list_notices
from lanes.plan import load_plan

PLAN = ".lanes/plan.yaml"


def commit_check(repo, clean_env, user):
    env = dict(clean_env, LANES_USER=user)
    return subprocess.run([sys.executable, str(REPO / "hooks" / "pre_commit.py")], capture_output=True, text=True, cwd=repo, env=env)


def stage_plan(repo, plan_dict):
    write_plan(repo, plan_dict)
    git(repo, "add", PLAN)


@pytest.fixture
def as_friend(repo, monkeypatch):
    monkeypatch.chdir(repo)
    monkeypatch.setenv("LANES_USER", "friend")
    return repo


def cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_plan_file_is_owned_by_the_plan_owner(repo):
    own = load_plan(repo).owner_of(PLAN)
    assert own.kind == "plan" and own.owner == "shaurya"


def test_guard_blocks_non_owner_plan_edits_and_points_to_task_status(repo, clean_env):
    from test_hooks import edit, run_hook

    p = run_hook("pre_tool_guard", edit(repo, PLAN), repo, clean_env, user="friend")
    reason = p.json["hookSpecificOutput"]["permissionDecisionReason"]
    assert p.json["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "belongs to the plan owner, shaurya" in reason and "lanes task status <TASK>" in reason
    assert run_hook("pre_tool_guard", edit(repo, PLAN), repo, clean_env, user="shaurya").stdout == ""


def test_task_status_edits_only_that_line_and_keeps_comments(as_friend, capsys):
    path = as_friend / PLAN
    text = "# team plan: keep this comment\n" + path.read_text().replace("status: todo", "status: todo   # T2 starts after T1", 1)
    path.write_text(text)
    git(as_friend, "commit", "-qam", "comments")
    code, out = cli(capsys, "task", "status", "T2", "in_progress")
    assert code == 0 and "T2 status: todo -> in_progress" in out and "lanes sync" in out
    new = path.read_text()
    assert new == text.replace("status: todo   # T2 starts after T1", "status: in_progress   # T2 starts after T1")
    assert load_plan(as_friend).task("T2").status == "in_progress"


def test_task_status_adds_a_missing_status_line(as_friend, capsys, plan_dict):
    del plan_dict["tasks"][1]["status"]
    write_plan(as_friend, plan_dict)
    assert cli(capsys, "task", "status", "T2", "blocked")[0] == 0
    assert load_plan(as_friend).task("T2").status == "blocked"
    assert yaml.safe_load((as_friend / PLAN).read_text())["tasks"][1]["status"] == "blocked"


def test_task_status_only_for_your_own_tasks(as_friend, capsys):
    code, out = cli(capsys, "task", "status", "T1", "done")
    assert code == 1 and "T1 belongs to shaurya; only its owner can change its status" in out
    code, out = cli(capsys, "task", "status", "T9", "done")
    assert code == 1 and "no task 'T9'" in out


def test_commit_check_accepts_a_status_only_change_to_your_own_task(as_friend, capsys, clean_env):
    cli(capsys, "task", "status", "T2", "review")
    git(as_friend, "add", PLAN)
    p = commit_check(as_friend, clean_env, "friend")
    assert p.returncode == 0, p.stderr
    assert cli(capsys, "check", "--staged")[0] == 0
    _, out = cli(capsys, "status")
    assert "outside your lane" not in out


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["tasks"][0].update(status="done"),  # someone else's task
        lambda d: d["tasks"][1].update(owns=["src/**"]),  # ownership
        lambda d: (d.update(owner="friend"), d["tasks"][1].update(status="review")),  # make myself plan owner
        lambda d: d["members"].append({"id": "eve", "email": "eve@example.com"}),
    ],
)
def test_commit_check_blocks_other_plan_changes_by_non_owners(repo, clean_env, plan_dict, change):
    change(plan_dict)
    stage_plan(repo, plan_dict)
    p = commit_check(repo, clean_env, "friend")
    assert p.returncode == 1 and ".lanes/plan.yaml" in p.stderr and "plan owner, shaurya" in p.stderr
    assert "more than the status of your own tasks" in p.stderr


def test_plan_owner_may_commit_any_plan_change(repo, clean_env, plan_dict):
    plan_dict["tasks"][1]["owns"] = ["src/**"]
    stage_plan(repo, plan_dict)
    assert commit_check(repo, clean_env, "shaurya").returncode == 0


def test_status_only_changes_create_no_plan_notices(repo, clean_env, plan_dict, monkeypatch, capsys):
    from test_hooks import edit, run_hook

    plan_dict["tasks"][1]["status"] = "in_progress"  # the plan owner edits a status directly
    write_plan(repo, plan_dict)
    p = run_hook("post_tool_notice", edit(repo, PLAN, event="PostToolUse"), repo, clean_env, user="shaurya")
    assert p.stdout == "" and list_notices(repo) == []
    git(repo, "checkout", "--", PLAN)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("LANES_USER", "friend")
    cli(capsys, "task", "status", "T2", "done")
    p = run_hook("post_tool_notice", edit(repo, PLAN, event="PostToolUse"), repo, clean_env, user="friend")
    assert p.stdout == "" and list_notices(repo) == []
