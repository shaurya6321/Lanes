import json
import subprocess

import pytest
import yaml
from conftest import git, write_plan

from lanes.cli import main
from lanes.install import GIT_HOOK_MARKER, init_repo
from lanes.notices import list_notices
from lanes.plan import load_plan


@pytest.fixture
def in_repo(repo, monkeypatch):
    monkeypatch.chdir(repo)
    return repo


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_whoami(in_repo, capsys):
    code, out = run(capsys, "whoami")
    assert code == 0 and "You are: shaurya" in out and "src/api/cart/**" in out
    assert "Contracts you own: cart-api" in out


def test_whoami_unknown_member(in_repo, capsys, monkeypatch):
    monkeypatch.setenv("LANES_USER", "ghost")
    code, out = run(capsys, "whoami")
    assert code == 1 and "not a member" in out


def test_status_table_and_counts(in_repo, capsys):
    code, out = run(capsys, "status")
    assert code == 0
    assert "checkout-v1" in out and "T2" in out and "friend" in out
    assert "Unread notices: shaurya 0 · friend 0 · sam 0" in out


def test_status_warns_about_out_of_lane_changes(in_repo, capsys):
    (in_repo / "src" / "pages" / "checkout").mkdir(parents=True)
    (in_repo / "src" / "pages" / "checkout" / "x.tsx").write_text("x")
    code, out = run(capsys, "status")
    assert "outside your lane" in out and "src/pages/checkout/x.tsx (owned by friend)" in out


def test_status_warns_about_overlapping_owns(in_repo, capsys, plan_dict):
    plan_dict["tasks"][0]["owns"].append("tests/**")
    plan_dict["tasks"][1]["owns"].append("tests/e2e_results/**")
    write_plan(in_repo, plan_dict)
    code, out = run(capsys, "status")
    assert code == 0 and "overlapping `owns` globs" in out
    assert "T1 tests/** and T2 tests/e2e_results/**: T2 wins (more specific)" in out


def test_status_has_no_overlap_warning_for_disjoint_globs(in_repo, capsys):
    code, out = run(capsys, "status")
    assert code == 0 and "overlapping" not in out


@pytest.mark.parametrize(
    "path, code",
    [("src/api/cart/add.py", 0), ("src/pages/checkout/x.tsx", 2), (".lanes/notices/n.md", 0), ("README.md", 2)],
)
def test_check_exit_codes(in_repo, capsys, path, code):
    got, out = run(capsys, "check", path)
    assert got == code
    if code == 2:
        assert "BLOCK" in out


def test_check_windows_style_relative_path(in_repo, capsys):
    got, _ = run(capsys, "check", "src\\api\\cart\\add.py")
    assert got == 0


def test_check_absolute_path(in_repo, capsys):
    got, _ = run(capsys, "check", str(in_repo / "src" / "pages" / "checkout" / "x.tsx"))
    assert got == 2


def test_check_staged(in_repo, capsys):
    (in_repo / "src" / "api" / "cart").mkdir(parents=True)
    (in_repo / "src" / "api" / "cart" / "a.py").write_text("ok")
    git(in_repo, "add", "-A")
    assert run(capsys, "check", "--staged")[0] == 0
    (in_repo / "src" / "emails").mkdir(parents=True)
    (in_repo / "src" / "emails" / "b.py").write_text("not mine")
    git(in_repo, "add", "-A")
    code, out = run(capsys, "check", "--staged")
    assert code == 2 and "src/emails/b.py" in out and "belongs to sam" in out


def test_invalid_plan_is_an_error(in_repo, capsys):
    (in_repo / ".lanes" / "plan.yaml").write_text("feature: x\nmembers: []\n")
    code, out = run(capsys, "check", "x")
    assert code == 1 and "members" in out


def test_request_then_notices_flow(in_repo, capsys, monkeypatch):
    monkeypatch.setenv("LANES_USER", "friend")
    code, out = run(capsys, "request", "--file", "src/types/cart.ts", "Add currency to Cart")
    assert code == 0 and "to shaurya" in out
    monkeypatch.setenv("LANES_USER", "shaurya")
    code, out = run(capsys, "notices")
    assert "Add currency to Cart" in out and "request from T2/friend" in out
    run(capsys, "notices", "--mark-read")
    code, out = run(capsys, "notices")
    assert "No unread notices" in out
    code, out = run(capsys, "notices", "--all")
    assert "Add currency to Cart" in out


def test_handoff_creates_file(in_repo, capsys):
    code, out = run(capsys, "handoff")
    assert code == 0
    path = in_repo / out.strip()
    assert path.name.startswith("T1-") and "## Next step" in path.read_text()
    code, out = run(capsys, "handoff", "T2")
    assert (in_repo / out.strip()).name.startswith("T2-")


# ---- init ----------------------------------------------------------------------------


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "me@example.com")
    monkeypatch.chdir(root)
    monkeypatch.delenv("LANES_USER", raising=False)
    return root


def test_init_creates_working_setup(fresh, capsys):
    code, out = run(capsys, "init")
    assert code == 0
    for rel in (
        ".lanes/plan.yaml", ".lanes/contracts/example-api.md", ".lanes/contracts/_TEMPLATE.md",
        ".lanes/handoffs/_TEMPLATE.md", ".lanes/decisions.md", ".lanes/notices/.gitkeep",
        ".lanes/summaries/.gitkeep", "CLAUDE.md", "AGENTS.md", ".claude/settings.json",
        ".claude/commands/lanes-status.md", ".claude/commands/lanes-handoff.md",
    ):
        assert (fresh / rel).exists(), rel
    plan = load_plan(fresh)
    assert plan.members[0].id == "me" and plan.members[0].email == "me@example.com"
    settings = json.loads((fresh / ".claude/settings.json").read_text())
    assert set(settings["hooks"]) == {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}
    pre = settings["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert pre["hooks"][0] == {"type": "command", "command": "lanes", "args": ["hook", "pre-tool-guard"], "timeout": 10}
    assert "matcher" not in settings["hooks"]["Stop"][0]
    hook = fresh / ".git" / "hooks" / "pre-commit"
    assert GIT_HOOK_MARKER in hook.read_text() and hook.stat().st_mode & 0o111
    assert ".lanes/local/" in (fresh / ".gitignore").read_text()
    assert "/lanes-handoff" in (fresh / "CLAUDE.md").read_text()
    assert "lanes handoff" in (fresh / "AGENTS.md").read_text()
    # the copied slash command keeps its $ARGUMENTS placeholder
    assert "$ARGUMENTS" in (fresh / ".claude/commands/lanes-handoff.md").read_text()


def test_first_commit_after_init_passes_the_real_git_hook(fresh, capsys, monkeypatch):
    """Regression: init used to create files nobody owned, so the pre-commit hook blocked the first commit."""
    import os
    import sys
    from pathlib import Path

    monkeypatch.setenv("LANES_USER", "me")
    run(capsys, "init")
    bindir = fresh.parent / "bin"
    bindir.mkdir()
    shim = bindir / "lanes"  # put a `lanes` on PATH that runs this checkout
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} -m lanes.cli \"$@\"\n")
    shim.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", LANES_USER="me",
               PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    git(fresh, "add", "-A")
    ok = subprocess.run(["git", "commit", "-q", "-m", "Set up Lanes"], cwd=fresh, env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    (fresh / "src" / "ui").mkdir(parents=True)
    (fresh / "src" / "ui" / "page.txt").write_text("teammate's lane")
    git(fresh, "add", "-A")
    blocked = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=fresh, env=env, capture_output=True, text=True)
    assert blocked.returncode != 0 and "src/ui/page.txt" in blocked.stderr


def test_init_is_idempotent_and_preserves_user_content(fresh, capsys):
    (fresh / "CLAUDE.md").write_text("# My project\n\nUse tabs.\n")
    (fresh / ".claude").mkdir()
    (fresh / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(npm test)"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}))
    run(capsys, "init")
    (fresh / ".lanes" / "plan.yaml").write_text((fresh / ".lanes" / "plan.yaml").read_text().replace("my-feature", "edited"))
    code, out = run(capsys, "init")
    assert "unchanged .lanes/plan.yaml" in out and "unchanged CLAUDE.md" in out
    assert load_plan(fresh).feature == "edited"  # plan not overwritten
    claude = (fresh / "CLAUDE.md").read_text()
    assert claude.startswith("# My project") and claude.count("lanes:begin") == 1
    settings = json.loads((fresh / ".claude" / "settings.json").read_text())
    assert settings["permissions"]["allow"] == ["Bash(npm test)"]
    stop_cmds = [h["command"] for g in settings["hooks"]["Stop"] for h in g["hooks"]]
    assert stop_cmds.count("lanes") == 1 and "say done" in stop_cmds


def test_init_does_not_replace_foreign_git_hook(fresh, capsys):
    hook = fresh / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho mine\n")
    code, out = run(capsys, "init")
    assert "already exists" in out and hook.read_text() == "#!/bin/sh\necho mine\n"


def test_init_uv_dev_runner(fresh):
    init_repo(fresh, member="me", runner="uv-dev")
    settings = json.loads((fresh / ".claude/settings.json").read_text())
    h = settings["hooks"]["SessionStart"][0]["hooks"][0]
    assert h["command"] == "uv" and h["args"][-1] == "${CLAUDE_PROJECT_DIR}/hooks/session_start.py"


def test_example_plan_template_is_valid(fresh):
    init_repo(fresh, member="me", email="me@example.com")
    plan = load_plan(fresh)
    assert [t.id for t in plan.tasks] == ["T1", "T2"]
    assert yaml.safe_load((fresh / ".lanes/plan.yaml").read_text())["feature"] == "my-feature"


# ---- notices amend --------------------------------------------------------------------


def _contract_notice(repo):
    from lanes.notices import record_change

    plan = load_plan(repo)
    rel = ".lanes/contracts/cart-api.md"
    notice, _ = record_change(repo, plan, "shaurya", rel, plan.owner_of(rel), ["+ addItem(sku, qty, note)"])
    return notice


def test_amend_rewrites_summary_and_body_as_valid_yaml(in_repo, capsys):
    n = _contract_notice(in_repo)
    code, out = run(capsys, "notices", "amend", n.id, "--summary", "Added `note: str` to addItem(sku, qty) -> Cart.",
                    "--body", "+ addItem(sku, qty, note: str = '')\\nCallers can omit note.")
    assert code == 0, out
    text = n.path.read_text()
    fm = yaml.safe_load(text.split("---")[1])  # strict YAML still parses
    assert fm["summary"] == "Added `note: str` to addItem(sku, qty) -> Cart." and fm["to_tasks"] == ["T2", "T3"]
    assert text.rstrip().endswith("+ addItem(sku, qty, note: str = '')\nCallers can omit note.")


def test_amend_refuses_someone_elses_notice(in_repo, capsys, monkeypatch):
    n = _contract_notice(in_repo)
    monkeypatch.setenv("LANES_USER", "friend")
    code, out = run(capsys, "notices", "amend", n.id, "--summary", "hijacked")
    assert code == 1 and "only its author can amend it" in out
    assert "hijacked" not in n.path.read_text()


def test_amend_refuses_a_notice_already_read(in_repo, capsys):
    from lanes.notices import mark_read

    n = _contract_notice(in_repo)
    mark_read(in_repo, "friend", [n.id])
    code, out = run(capsys, "notices", "amend", n.id, "--summary", "too late")
    assert code == 1 and "already been read" in out


def test_amend_needs_a_known_id_and_some_text(in_repo, capsys):
    n = _contract_notice(in_repo)
    assert "no notice with id" in run(capsys, "notices", "amend", "nope", "--summary", "x")[1]
    assert "give --summary" in run(capsys, "notices", "amend", n.id)[1]
    assert "only work with" in run(capsys, "notices", "--summary", "x")[1]
