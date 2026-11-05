"""Identity comes from the repo-local `git config user.email`, with no LANES_USER needed."""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import REPO, git

from lanes.cli import main
from lanes.identity import resolve
from lanes.plan import load_plan


@pytest.fixture
def global_git(tmp_path, monkeypatch):
    """Point git's global config at a temp file (and ignore system config) for the whole test."""
    cfg = tmp_path / "global.gitconfig"
    cfg.write_text("[user]\n\temail = friend@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("LANES_USER", raising=False)
    return cfg


def test_repo_local_email_wins_over_global(repo, global_git):
    ident = resolve(load_plan(repo), repo, env={})
    assert ident.member_id == "shaurya" and ident.source == "git user.email"


def test_global_email_is_used_when_the_repo_has_none(repo, global_git):
    git(repo, "config", "--unset", "user.email")
    assert resolve(load_plan(repo), repo, env={}).member_id == "friend"


def test_whoami_works_with_no_lanes_user_at_all(repo, global_git, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    assert main(["whoami"]) == 0
    assert "You are: shaurya (git user.email=shaurya@example.com)" in capsys.readouterr().out


def test_no_match_gives_a_clear_error(repo, global_git, monkeypatch, capsys):
    git(repo, "config", "user.email", "stranger@example.com")
    monkeypatch.chdir(repo)
    assert main(["whoami"]) == 1
    err = capsys.readouterr().err
    assert "git user.email stranger@example.com (from this repo's git config) doesn't match any member email" in err
    assert "shaurya <shaurya@example.com>" in err and "friend <friend@example.com>" in err
    assert "git config user.email" in err and "LANES_USER" in err


def test_no_match_from_global_config_says_so(repo, global_git):
    git(repo, "config", "--unset", "user.email")
    global_git.write_text("[user]\n\temail = nobody@example.com\n")
    ident = resolve(load_plan(repo), repo, env={})
    assert ident.member_id is None and "(from your global git config)" in ident.detail


def test_no_email_anywhere(repo, global_git):
    git(repo, "config", "--unset", "user.email")
    global_git.write_text("")
    ident = resolve(load_plan(repo), repo, env={})
    assert ident.member_id is None and "git has no user.email" in ident.detail


def test_hooks_and_commit_check_explain_a_mismatch_and_fail_open(repo, global_git, clean_env):
    import json

    from test_hooks import payload

    git(repo, "config", "user.email", "stranger@example.com")
    env = dict(clean_env, GIT_CONFIG_GLOBAL=str(global_git), GIT_CONFIG_NOSYSTEM="1", CLAUDE_PROJECT_DIR=str(repo))
    p = subprocess.run([sys.executable, str(REPO / "hooks" / "session_start.py")], input=json.dumps(payload("SessionStart", repo, source="startup")),
                       capture_output=True, text=True, cwd=repo, env=env)
    assert "stranger@example.com (from this repo's git config) doesn't match" in json.loads(p.stdout)["systemMessage"]
    (repo / "src" / "emails").mkdir(parents=True)
    (repo / "src" / "emails" / "x.py").write_text("x\n")
    git(repo, "add", "-A")
    pc = subprocess.run([sys.executable, str(REPO / "hooks" / "pre_commit.py")], capture_output=True, text=True, cwd=repo, env=env)
    assert pc.returncode == 0 and "lane check skipped" in pc.stderr and "doesn't match any member email" in pc.stderr
