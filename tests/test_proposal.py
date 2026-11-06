"""Plan proposals: `lanes plan check|diff|accept` (the planner's review-and-apply half)."""

from __future__ import annotations

import datetime

import pytest
import yaml
from conftest import git, write_plan

from lanes import notices as N
from lanes import proposal as P
from lanes.cli import main
from lanes.plan import load_plan

SOURCES = [
    "src/api/cart/add.py",
    "src/pages/checkout/page.tsx",
    "src/components/checkout/button.tsx",
    "src/emails/order.py",
    "README.md",
]


@pytest.fixture
def plan_dict():
    """conftest's plan, minus T1 `uses: [checkout-events]`: that upstream use is there on purpose for
    the notice tests, but it's exactly what `lanes plan check` rejects (a user must rank below the implementer)."""
    import copy

    from conftest import PLAN

    plan = copy.deepcopy(PLAN)
    plan["tasks"][0]["uses"] = []
    return plan


@pytest.fixture
def proj(repo, plan_dict):
    write_plan(repo, plan_dict)
    for rel in SOURCES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "sources")
    return repo


def propose(root, plan_dict, touches=("src/api/cart/add.py",), based_on="current", header="# proposed by /lanes-plan\n"):
    data = dict(plan_dict)
    data["proposal"] = {
        "based_on": P.plan_fingerprint(root) if based_on == "current" else based_on,
        "touches": list(touches),
        "rationale": {"T1": "cart API and its types change together"},
    }
    (root / P.PROPOSAL_FILE).write_text(header + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def draft(root, name, text="# draft\n"):
    d = root / P.DRAFT_CONTRACTS
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


# ---- check -----------------------------------------------------------------------------


def test_unchanged_plan_as_proposal_is_ok(proj, plan_dict):
    propose(proj, plan_dict)
    res = P.check_proposal(proj)
    assert res.ok, res.errors
    assert not res.stale
    assert any("README.md" in w and "no owner" in w for w in res.warnings)


def test_missing_proposal(proj):
    res = P.check_proposal(proj)
    assert not res.ok and "/lanes-plan" in res.errors[0]


def test_invalid_plan_errors_are_reported(proj, plan_dict):
    plan_dict["tasks"][1]["owner"] = "ghost"
    propose(proj, plan_dict)
    res = P.check_proposal(proj)
    assert any("owner 'ghost' is not in members" in e for e in res.errors)


def test_unexplained_overlap_is_an_error_and_explained_one_is_not(proj, plan_dict):
    plan_dict["tasks"][0]["owns"].append("src/**")
    propose(proj, plan_dict)
    res = P.check_proposal(proj)
    assert any("`src/**`" in e and "overlaps:" in e for e in res.errors)

    plan_dict["overlaps"] = [{"globs": ["src/**", "src/pages/checkout/**"], "why": "T1 sweeps formatting"},
                             {"globs": ["src/**", "src/components/checkout/**"], "why": "same"},
                             {"globs": ["src/**", "src/emails/**"], "why": "same"}]
    propose(proj, plan_dict)
    assert P.check_proposal(proj).ok


def test_stale_overlap_entry_is_a_warning(proj, plan_dict):
    plan_dict["overlaps"] = [{"globs": ["src/api/cart/**", "src/emails/**"], "why": "no longer true"}]
    propose(proj, plan_dict)
    res = P.check_proposal(proj)
    assert res.ok and any("don't overlap" in w for w in res.warnings)


def test_contract_rules(proj, plan_dict):
    # sam's T3 implements a new contract that T2 (rank 2, upstream of T3) would use
    plan_dict["contracts"].append({"id": "email-api", "file": ".lanes/contracts/email-api.md", "owner": "sam"})
    plan_dict["tasks"][2]["implements"] = ["email-api"]
    plan_dict["tasks"][1]["uses"] = ["cart-api", "email-api"]
    propose(proj, plan_dict)
    errors = P.check_proposal(proj).errors
    assert any("uses contract email-api" in e and "lower rank" in e for e in errors)
    assert any(".lanes/contracts/email-api.md doesn't exist" in e and P.DRAFT_CONTRACTS in e for e in errors)

    plan_dict["tasks"][1]["uses"] = ["cart-api"]  # now nobody uses it
    propose(proj, plan_dict)
    assert any("contract email-api: no task uses it" in e for e in P.check_proposal(proj).errors)

    plan_dict["tasks"][2]["implements"] = []
    propose(proj, plan_dict)
    assert any("contract email-api: no task implements it" in e for e in P.check_proposal(proj).errors)


def test_new_contract_draft_and_conflicts(proj, plan_dict):
    plan_dict["contracts"].append({"id": "pricing", "file": ".lanes/contracts/pricing.md", "owner": "shaurya"})
    plan_dict["tasks"][0]["implements"].append("pricing")
    plan_dict["tasks"][1]["uses"].append("pricing")
    propose(proj, plan_dict)
    draft(proj, "pricing.md")
    draft(proj, "orphan.md")
    res = P.check_proposal(proj)
    assert res.ok, res.errors
    assert any("orphan.md isn't used" in w for w in res.warnings)

    draft(proj, "cart-api.md")  # would overwrite an existing contract
    assert any("would replace the existing .lanes/contracts/cart-api.md" in e for e in P.check_proposal(proj).errors)


def test_user_of_contract_should_depend_on_implementer(proj, plan_dict):
    plan_dict["tasks"][2]["uses"] = ["checkout-events", "cart-api"]  # T3 depends on T2 -> T1: fine
    propose(proj, plan_dict)
    assert not any("doesn't depend" in w for w in P.check_proposal(proj).warnings)
    plan_dict["tasks"][2]["depends_on"] = []
    plan_dict["tasks"][2]["uses"] = ["cart-api"]
    propose(proj, plan_dict)
    assert any("T3 uses contract cart-api from T1 but doesn't depend on it" in w for w in P.check_proposal(proj).warnings)


def test_touched_paths_need_an_owner(proj, plan_dict):
    propose(proj, plan_dict, touches=["src/api/cart/**", "src/api/cart/new.py", "src/search/**", "docs/new.md"])
    res = P.check_proposal(proj)
    assert any("2 path(s) the work touches have no owner" in e and "src/search/x" in e and "docs/new.md" in e for e in res.errors)


def test_empty_touches_is_a_warning(proj, plan_dict):
    propose(proj, plan_dict, touches=[])
    res = P.check_proposal(proj)
    assert res.ok and any("touches` is empty" in w for w in res.warnings)


def test_hub_inside_someone_elses_lane_is_a_warning(proj, plan_dict):
    plan_dict["hub_files"].append({"path": "src/pages/checkout/routes.ts", "owner": "shaurya"})
    propose(proj, plan_dict)
    assert any("hub file `src/pages/checkout/routes.ts`" in w and "T2" in w for w in P.check_proposal(proj).warnings)


def test_plan_md_team_names_must_be_members(proj, plan_dict):
    (proj / ".lanes" / "PLAN.md").write_text("# Plan\n\n## Team\n<!-- - ignored: comment -->\n- shaurya: API\n- **kim**: the UI\n\n## Rules\n- no: x\n")
    plan_dict["members"].append({"id": "lee", "email": "lee@example.com"})
    propose(proj, plan_dict)
    warnings = P.check_proposal(proj).warnings
    assert any("names 'kim'" in w for w in warnings)
    assert not any("'no'" in w or "'ignored'" in w for w in warnings)
    assert any("member lee has no task" in w for w in warnings)


def test_stale_proposal(proj, plan_dict):
    propose(proj, plan_dict, based_on="000000000000")
    res = P.check_proposal(proj)
    assert res.ok and res.stale and any("changed after this proposal" in w for w in res.warnings)
    with pytest.raises(ValueError, match="--force"):
        P.accept_proposal(proj, "shaurya")
    P.accept_proposal(proj, "shaurya", force=True)


# ---- diff ------------------------------------------------------------------------------


def test_diff_shows_what_moves(proj, plan_dict):
    plan_dict["tasks"][1]["owns"] = ["src/pages/checkout/**"]
    plan_dict["tasks"][0]["owns"].append("src/components/checkout/**")
    plan_dict["tasks"].append({"id": "T4", "title": "Docs", "rank": 4, "owner": "sam", "owns": ["README.md"], "depends_on": ["T1"]})
    plan_dict["contracts"].append({"id": "pricing", "file": ".lanes/contracts/pricing.md", "owner": "shaurya"})
    plan_dict["tasks"][0]["implements"].append("pricing")
    plan_dict["tasks"][3]["uses"] = ["pricing"]
    plan_dict["tasks"][0]["status"] = "todo"
    propose(proj, plan_dict, touches=["src/components/checkout/**", "src/api/cart/price.py"])
    draft(proj, "pricing.md")
    text = "\n".join(P.diff_proposal(proj))
    assert "~ T1 owns: +src/components/checkout/**" in text and "~ T2 owns: -src/components/checkout/**" in text
    assert "+ T4 added (owner sam, rank 4, owns README.md)" in text
    assert "+ pricing (owner shaurya, .lanes/contracts/pricing.md, new draft)" in text
    assert "T2 (friend) -> T1 (shaurya): src/components/checkout/button.tsx" in text
    assert "unowned -> T4 (sam): README.md" in text
    assert "T1 keeps its current status, in_progress" in text
    assert "Accepting sends a plan notice to: friend, sam." in text


def test_diff_of_identical_proposal(proj, plan_dict):
    propose(proj, plan_dict)
    assert P.diff_proposal(proj) == ["No changes: the proposal matches plan.yaml."]


# ---- accept ----------------------------------------------------------------------------


def test_only_the_plan_owner_accepts(proj, plan_dict):
    propose(proj, plan_dict)
    with pytest.raises(ValueError, match=r"only the plan owner \(shaurya\)"):
        P.accept_proposal(proj, "friend")


def test_accept_refuses_a_proposal_with_errors(proj, plan_dict):
    plan_dict["tasks"][0]["owns"].append("src/**")
    propose(proj, plan_dict)
    with pytest.raises(ValueError, match="overlap"):
        P.accept_proposal(proj, "shaurya")
    assert load_plan(proj).tasks[0].owns == ("src/api/cart/**", "src/types/**")


def test_accept_replaces_plan_moves_drafts_keeps_status_and_notifies(proj, plan_dict):
    plan_dict["tasks"][1]["owns"] = ["src/pages/checkout/**"]
    plan_dict["tasks"][0]["owns"].append("src/components/checkout/**")
    plan_dict["contracts"].append({"id": "pricing", "file": ".lanes/contracts/pricing.md", "owner": "shaurya"})
    plan_dict["tasks"][0]["implements"].append("pricing")
    plan_dict["tasks"][1]["uses"].append("pricing")
    plan_dict["tasks"][0]["status"] = "todo"  # proposal tries to reset T1; it stays in_progress
    plan_dict["tasks"][1]["status"] = "done"
    plan_dict["updated"] = "2000-01-01"
    propose(proj, plan_dict, header="# Plan for checkout-v1 (keep this comment)\n")
    draft(proj, "pricing.md", "# pricing\n\nprice(sku) -> Decimal\n")

    result = P.accept_proposal(proj, "shaurya")

    text = (proj / ".lanes" / "plan.yaml").read_text()
    assert text.startswith("# Plan for checkout-v1 (keep this comment)")
    assert "proposal:" not in text and "based_on" not in text
    data = yaml.safe_load(text)
    assert data["updated"] == datetime.date.today()
    plan = load_plan(proj)
    assert [t.status for t in plan.tasks] == ["in_progress", "todo", "todo"]
    assert plan.owner_of("src/components/checkout/button.tsx").owner == "shaurya"
    assert (proj / ".lanes/contracts/pricing.md").read_text().startswith("# pricing")
    assert result.moved_contracts == [".lanes/contracts/pricing.md"]
    assert not (proj / P.PROPOSAL_FILE).exists() and not (proj / P.PROPOSAL_DIR).exists()
    assert result.notice is not None and result.notice.kind == "plan" and result.notice.to_members == ["friend"]
    assert [n.id for n in N.unread_for(proj, plan, "friend")] == [result.notice.id]


def test_accept_can_hand_the_plan_to_a_new_owner(proj, plan_dict):
    plan_dict["owner"] = "friend"
    plan_dict["tasks"][1]["owns"].append("src/emails/templates/**")
    plan_dict["overlaps"] = [{"globs": ["src/emails/**", "src/emails/templates/**"], "why": "friend owns the templates"}]
    propose(proj, plan_dict)
    result = P.accept_proposal(proj, "shaurya")
    assert load_plan(proj).owner == "friend"
    assert result.notice is not None and result.notice.to_members == ["friend"]  # sam's T3 didn't change


# ---- CLI -------------------------------------------------------------------------------


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_cli_plan_check_diff_accept(proj, plan_dict, capsys, monkeypatch):
    monkeypatch.chdir(proj)
    code, out = run(capsys, "plan", "check")
    assert code == 1 and "doesn't exist" in out

    plan_dict["tasks"][1]["owns"] = ["src/pages/checkout/**"]
    plan_dict["tasks"][0]["owns"].append("src/components/checkout/**")
    propose(proj, plan_dict)
    code, out = run(capsys, "plan", "check")
    assert code == 0 and "OK" in out and "plan diff" in out

    code, out = run(capsys, "plan", "diff")
    assert code == 0 and "What moves" in out and "src/components/checkout/button.tsx" in out

    monkeypatch.setenv("LANES_USER", "friend")
    code, out = run(capsys, "plan", "accept")
    assert code == 1 and "only the plan owner" in out

    monkeypatch.setenv("LANES_USER", "shaurya")
    code, out = run(capsys, "plan", "accept")
    assert code == 0 and "Accepted" in out and "plan notice for friend" in out and "sync" in out
    code, out = run(capsys, "plan", "diff")
    assert code == 1 and "doesn't exist" in out
