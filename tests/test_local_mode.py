"""`lanes init --local`: repo-only installs where Lanes is a dev dependency run through `uv run`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO, git

from lanes.cli import main
from lanes.install import detect_runner, init_repo
from lanes.runner import lanes_cmd

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the git hook shim is POSIX sh")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """An empty git repo whose folder name contains a space."""
    root = tmp_path / "my project"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "me@example.com")
    git(root, "config", "user.name", "me")
    git(root, "config", "commit.gpgsign", "false")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n[dependency-groups]\ndev = ["lanes @ git+https://github.com/shaurya6321/Lanes"]\n')
    monkeypatch.chdir(root)
    monkeypatch.delenv("LANES_USER", raising=False)
    return root


def _handlers(root: Path) -> list[dict]:
    settings = json.loads((root / ".claude" / "settings.json").read_text())
    return [h for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]


def test_local_hooks_run_through_uv_with_the_project_dir_as_one_arg(proj, capsys):
    assert main(["init", "--local", "--member", "me"]) == 0
    out = capsys.readouterr().out
    assert "repo-only" in out and "uv run lanes sync" in out
    handlers = _handlers(proj)
    assert len(handlers) == 4
    for h in handlers:
        assert h["command"] == "uv"
        args = h["args"]
        assert args[:4] == ["run", "--quiet", "--project", "${CLAUDE_PROJECT_DIR}"]  # exec form: no shell quoting
        assert args[4:6] == ["lanes", "hook"]
    assert detect_runner(proj) == "uv-local"


def test_exec_form_args_survive_a_space_in_the_path(proj):
    """Simulate Claude Code's exec form: substitute the var into each arg, run with no shell."""
    init_repo(proj, member="me", runner="uv-local")
    h = _handlers(proj)[0]
    argv = [h["command"], *(a.replace("${CLAUDE_PROJECT_DIR}", str(proj)) for a in h["args"])]
    assert argv[4] == str(proj) and " " in argv[4]  # one argv entry, space intact, no quote characters
    assert '"' not in argv[4] and "'" not in argv[4]


def test_local_instructions_and_commands_say_uv_run_lanes(proj):
    init_repo(proj, member="me", runner="uv-local")
    for rel in ("CLAUDE.md", "AGENTS.md", ".claude/commands/lanes-handoff.md", ".claude/commands/lanes-status.md"):
        text = (proj / rel).read_text()
        assert "uv run lanes" in text, rel
        assert "`lanes " not in text and "Bash(lanes " not in text, rel
    handoff = (proj / ".claude/commands/lanes-handoff.md").read_text()
    assert "Bash(uv run lanes handoff:*)" in handoff and "$ARGUMENTS" in handoff


def test_global_instructions_still_say_lanes(proj):
    init_repo(proj, member="me")
    text = (proj / "CLAUDE.md").read_text()
    assert "`lanes request --file" in text and "uv run lanes" not in text


def test_rerun_on_a_fresh_clone_keeps_local_mode_and_only_adds_the_git_hook(proj, tmp_path, capsys, monkeypatch):
    init_repo(proj, member="me", runner="uv-local")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "--no-verify", "-m", "setup")
    clone = tmp_path / "friend clone"
    subprocess.run(["git", "clone", "-q", str(proj), str(clone)], check=True)
    monkeypatch.chdir(clone)
    assert main(["init"]) == 0  # teammate forgot --local: the repo's mode is kept
    out = capsys.readouterr().out
    assert "created   .git/hooks/pre-commit" in out
    assert git(clone, "status", "--porcelain") == ""
    assert "uv run --quiet --project" in (clone / ".git" / "hooks" / "pre-commit").read_text()


def test_switching_mode_warns(proj):
    init_repo(proj, member="me")
    report = init_repo(proj, member="me", runner="uv-local")
    assert any("switching" in w for w in report.warnings) and detect_runner(proj) == "uv-local"


def test_missing_dev_dependency_warns(proj):
    (proj / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n')
    report = init_repo(proj, member="me", runner="uv-local")
    assert any("uv add --dev" in w for w in report.warnings)


def _fake_uv(bindir: Path, log: Path, version_ok: bool) -> None:
    """A `uv` that logs each argv entry on its own line, and runs this checkout's lanes for `... lanes hook`."""
    bindir.mkdir(exist_ok=True)
    script = bindir / "uv"
    script.write_text(
        "#!/bin/sh\n"
        f'for a in "$@"; do printf "%s\\n" "$a"; done >> "{log}"\n'
        'printf -- "--\\n" >> "' + str(log) + '"\n'
        'case "$*" in\n'
        f'  *"lanes --version"*) exit {0 if version_ok else 2} ;;\n'
        f'  *"lanes hook pre-commit"*) exec "{sys.executable}" -m lanes.cli hook pre-commit ;;\n'
        "esac\nexit 0\n"
    )
    script.chmod(0o755)


@pytest.mark.parametrize("version_ok", [True, False])
def test_local_git_hook_quotes_the_path_and_fails_open(proj, tmp_path, version_ok):
    init_repo(proj, member="me", runner="uv-local")
    bindir, log = tmp_path / "bin", tmp_path / "uv.log"
    _fake_uv(bindir, log, version_ok)
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin", PYTHONPATH=str(REPO), LANES_USER="me")
    git(proj, "add", "-A")
    ok = subprocess.run(["git", "commit", "-q", "-m", "setup"], cwd=proj, env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    calls = log.read_text().split("--\n")
    first = calls[0].splitlines()
    assert first[:3] == ["run", "--quiet", "--project"] and first[3] == str(proj)  # one arg, space intact
    if version_ok:
        (proj / "src" / "ui").mkdir(parents=True)
        (proj / "src" / "ui" / "x.txt").write_text("teammate's lane\n")
        git(proj, "add", "-A")
        blocked = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=proj, env=env, capture_output=True, text=True)
        assert blocked.returncode == 1 and "src/ui/x.txt" in blocked.stderr
    else:
        assert "lane check was skipped" in ok.stderr  # env not synced: never block the commit


def test_lanes_cmd_detects_the_repo_environment(proj, monkeypatch):
    monkeypatch.delenv("LANES_CMD", raising=False)
    assert lanes_cmd(proj) == "lanes"  # this test runs from the Lanes checkout's venv
    monkeypatch.setattr(sys, "prefix", str(proj / ".venv"))
    assert lanes_cmd(proj) == "uv run lanes"
    monkeypatch.setenv("LANES_CMD", "lanes")
    assert lanes_cmd(proj) == "lanes"


def test_guard_and_briefing_say_uv_run_lanes_in_local_mode(repo, clean_env):
    from test_hooks import edit, payload, run_hook

    env = dict(clean_env, LANES_CMD="uv run lanes")
    deny = run_hook("pre_tool_guard", edit(repo, "src/emails/x.py"), repo, env)
    assert 'uv run lanes request --file "src/emails/x.py"' in deny.json["hookSpecificOutput"]["permissionDecisionReason"]
    brief = run_hook("session_start", payload("SessionStart", repo, source="startup"), repo, env)
    text = brief.json["hookSpecificOutput"]["additionalContext"]
    assert "`uv run lanes sync`" in text and "`uv run lanes request --file" in text
