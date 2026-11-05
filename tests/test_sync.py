"""`lanes sync` against a real bare remote with two clones (shaurya = A, friend = B)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import git, write_plan

from lanes.cli import main
from lanes.notices import list_notices, unread_for
from lanes.plan import load_plan


def _clone(origin: Path, dest: Path, email: str) -> Path:
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True, capture_output=True)
    git(dest, "config", "user.email", email)
    git(dest, "config", "user.name", email.split("@")[0])
    git(dest, "config", "commit.gpgsign", "false")
    return dest


@pytest.fixture
def team(tmp_path, monkeypatch):
    """A bare `origin` holding a Lanes plan, plus clones A (shaurya) and B (friend)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(origin)], check=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    git(seed, "config", "user.email", "shaurya@example.com")
    git(seed, "config", "user.name", "seed")
    git(seed, "config", "commit.gpgsign", "false")
    write_plan(seed)
    for sub in ("notices", "summaries", "handoffs", "contracts"):
        (seed / ".lanes" / sub).mkdir(parents=True, exist_ok=True)
        (seed / ".lanes" / sub / ".gitkeep").write_text("")
    (seed / ".lanes" / "decisions.md").write_text("# Decisions\n")
    (seed / ".gitignore").write_text(".lanes/local/\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "init")
    git(seed, "push", "-q", str(origin), "main")
    a = _clone(origin, tmp_path / "a", "shaurya@example.com")
    b = _clone(origin, tmp_path / "b", "friend@example.com")
    monkeypatch.delenv("LANES_USER", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return origin, a, b


def sync(where: Path, monkeypatch, capsys, *flags: str) -> tuple[int, str]:
    monkeypatch.chdir(where)
    code = main(["sync", *flags])
    out = capsys.readouterr()
    return code, out.out + out.err


def remote_log(origin: Path) -> str:
    return git(origin, "log", "--format=%s", "main")


def request(where: Path, monkeypatch, capsys, path: str, msg: str) -> None:
    monkeypatch.chdir(where)
    assert main(["request", "--file", path, msg]) == 0
    capsys.readouterr()


def test_lanes_only_commits_are_pushed_and_reach_the_teammate(team, monkeypatch, capsys):
    origin, a, b = team
    request(b, monkeypatch, capsys, "src/types/cart.ts", "Please add `currency` to Cart")
    code, out = sync(b, monkeypatch, capsys)
    assert code == 0, out
    assert "Committed 1 .lanes/ file(s)." in out and "Pushed 1 commit(s) to origin/main (.lanes/ only)." in out
    assert remote_log(origin).splitlines()[0] == "lanes: sync friend"

    code, out = sync(a, monkeypatch, capsys)
    assert code == 0 and "Nothing to push" in out
    (n,) = unread_for(a, load_plan(a), "shaurya")
    assert n.kind == "request" and "currency" in n.summary


def test_unpushed_code_commits_are_listed_and_held_back(team, monkeypatch, capsys):
    origin, a, b = team
    (a / "src" / "api" / "cart").mkdir(parents=True)
    (a / "src" / "api" / "cart" / "total.py").write_text("def total(): ...\n")
    git(a, "add", "-A")
    git(a, "commit", "-q", "-m", "WIP cart totals")
    (a / ".lanes" / "decisions.md").write_text("# Decisions\n- totals exclude tax\n")
    before = remote_log(origin)

    code, out = sync(a, monkeypatch, capsys)
    assert code == 3, out
    assert "Not pushed: 1 of 2 unpushed commit(s) contain code:" in out and "WIP cart totals (1 file(s))" in out
    assert "--include-code" in out
    assert remote_log(origin) == before  # nothing pushed, not even the .lanes/ commit

    code, out = sync(a, monkeypatch, capsys, "--include-code")
    assert code == 0 and "Pushed 2 commit(s) to origin/main (including code)." in out
    assert remote_log(origin).splitlines()[:2] == ["lanes: sync shaurya", "WIP cart totals"]


def test_only_lanes_is_committed_and_staged_code_stays_staged(team, monkeypatch, capsys):
    origin, a, b = team
    (a / "src" / "api" / "cart").mkdir(parents=True)
    (a / "src" / "api" / "cart" / "x.py").write_text("x = 1\n")
    git(a, "add", "src/api/cart/x.py")
    (a / ".lanes" / "decisions.md").write_text("# Decisions\n- one\n")
    code, out = sync(a, monkeypatch, capsys)
    assert code == 0, out
    assert git(origin, "show", "--name-only", "--format=", "main").split() == [".lanes/decisions.md"]
    assert git(a, "diff", "--cached", "--name-only").split() == ["src/api/cart/x.py"]


def test_pull_works_with_uncommitted_code_and_a_remote_ahead(team, monkeypatch, capsys):
    """`git pull --rebase` refuses with unstaged changes; sync autostashes them."""
    origin, a, b = team
    request(b, monkeypatch, capsys, "src/types/cart.ts", "need currency")
    assert sync(b, monkeypatch, capsys)[0] == 0
    (a / "README.md").write_text("local edit, not committed\n")
    git(a, "add", "README.md")
    git(a, "commit", "-q", "-m", "readme")  # a code commit, so the push is held back
    (a / "README.md").write_text("more local edits\n")  # and the tree is dirty
    code, out = sync(a, monkeypatch, capsys)
    assert code == 3 and "Pulled origin/main." in out
    assert (a / "README.md").read_text() == "more local edits\n"  # restored after the pull
    assert len(list_notices(a)) == 1


def test_conflict_aborts_the_rebase_and_lists_files(team, monkeypatch, capsys):
    origin, a, b = team
    (b / ".lanes" / "decisions.md").write_text("# Decisions\n- from friend\n")
    assert sync(b, monkeypatch, capsys)[0] == 0
    (a / ".lanes" / "decisions.md").write_text("# Decisions\n- from shaurya\n")
    code, out = sync(a, monkeypatch, capsys)
    assert code == 1 and "conflict" in out and ".lanes/decisions.md" in out
    assert not (a / ".git" / "rebase-merge").exists() and not (a / ".git" / "rebase-apply").exists()
    assert git(a, "log", "-1", "--format=%s").strip() == "lanes: sync shaurya"  # my commit is intact
    assert (a / ".lanes" / "decisions.md").read_text() == "# Decisions\n- from shaurya\n"


def test_no_upstream_is_reported(tmp_path, monkeypatch, capsys, repo):
    (repo / ".lanes" / "decisions.md").write_text("x\n")
    code, out = sync(repo, monkeypatch, capsys)
    assert code == 1 and "has no upstream" in out and "git push -u origin main" in out
    assert git(repo, "log", "-1", "--format=%s").strip() == "lanes: sync shaurya"


def test_hand_edited_plan_gets_its_notice_on_sync(team, monkeypatch, capsys):
    origin, a, b = team
    import yaml

    plan = yaml.safe_load((a / ".lanes" / "plan.yaml").read_text())
    plan["tasks"][1]["owns"] = ["src/pages/checkout/**"]
    write_plan(a, plan)
    code, out = sync(a, monkeypatch, capsys)
    assert code == 0 and "Wrote plan notice" in out and "for friend" in out
    assert sync(b, monkeypatch, capsys)[0] == 0
    (n,) = unread_for(b, load_plan(b), "friend")
    assert n.kind == "plan" and "-src/components/checkout/**" in n.body


def test_sync_commit_still_runs_the_lane_check(team, monkeypatch, capsys):
    import os
    import sys

    from lanes.install import install_git_hook

    origin, a, b = team
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    install_git_hook(a)
    (a / "src" / "emails").mkdir(parents=True)
    (a / "src" / "emails" / "x.py").write_text("sam's file\n")
    git(a, "add", "src/emails/x.py")  # staged but outside .lanes/: not part of the sync commit
    (a / ".lanes" / "decisions.md").write_text("# Decisions\n- ok\n")
    code, out = sync(a, monkeypatch, capsys)
    assert code == 0, out

    (a / ".lanes" / "contracts" / "checkout-events.md").write_text("# friend's contract, edited by shaurya\n")
    code, out = sync(a, monkeypatch, capsys)
    assert code == 1 and "lane check" in out and "checkout-events.md" in out


def test_task_status_by_its_owner_syncs_through_the_commit_check(team, monkeypatch, capsys):
    import os
    import sys

    from lanes.install import install_git_hook

    origin, a, b = team
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    install_git_hook(b)
    monkeypatch.chdir(b)
    assert main(["task", "status", "T2", "in_progress"]) == 0
    code, out = sync(b, monkeypatch, capsys)
    assert code == 0 and "Pushed 1 commit(s)" in out, out
    assert list_notices(b) == []  # status-only: no plan notice
    assert sync(a, monkeypatch, capsys)[0] == 0
    assert load_plan(a).task("T2").status == "in_progress"

    import yaml

    data = yaml.safe_load((b / ".lanes" / "plan.yaml").read_text())
    data["tasks"][1]["owns"].append("src/api/**")  # friend grabs files by hand
    write_plan(b, data)
    code, out = sync(b, monkeypatch, capsys)
    assert code == 1 and "plan owner, shaurya" in out
