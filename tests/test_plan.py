import pytest
from conftest import REPO

from lanes.identity import resolve
from lanes.lane import check_lane
from lanes.plan import PlanError, load_plan, parse_plan


def errors_of(data) -> list[str]:
    with pytest.raises(PlanError) as exc:
        parse_plan(data)
    return exc.value.errors


def test_valid_plan_loads(repo):
    plan = load_plan(repo)
    assert plan.feature == "checkout-v1"
    assert [t.id for t in plan.tasks_by_rank()] == ["T1", "T2", "T3"]
    assert plan.dependents("T1") == {"T2", "T3"}
    assert plan.implementer("cart-api").id == "T1"


def test_missing_plan(tmp_path):
    with pytest.raises(PlanError) as exc:
        load_plan(tmp_path)
    assert exc.value.missing


def test_invalid_yaml(tmp_path):
    (tmp_path / ".lanes").mkdir()
    (tmp_path / ".lanes" / "plan.yaml").write_text("feature: [unclosed\n")
    with pytest.raises(PlanError, match="not valid YAML"):
        load_plan(tmp_path)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p.pop("feature"), "`feature` is required"),
        (lambda p: p.update(members=[]), "`members` must be a non-empty list"),
        (lambda p: p["tasks"][0].update(owner="nobody"), "owner 'nobody' is not in members"),
        (lambda p: p["tasks"][1].update(id="T1"), "duplicate id 'T1'"),
        (lambda p: p["tasks"][0].update(rank=0), "`rank` must be an integer >= 1"),
        (lambda p: p["tasks"][0].update(rank="1"), "`rank` must be an integer >= 1"),
        (lambda p: p["tasks"][0].update(status="doing"), "`status` must be one of"),
        (lambda p: p["tasks"][1].update(uses=["nope"]), "unknown contract 'nope'"),
        (lambda p: p["tasks"][1].update(depends_on=["T9"]), "unknown task 'T9'"),
        (lambda p: p["tasks"][0].update(depends_on=["T2"]), "a dependency must have a lower rank"),
        (lambda p: p["tasks"][1].update(implements=["cart-api"]), "cart-api is owned by shaurya, not friend"),
        (lambda p: p["tasks"][1]["owns"].append("src/types/**"), "claimed by both shaurya and friend"),
        (lambda p: p["hub_files"].append({"path": "x"}), "hub_files[2]: owner None is not in members"),
        (lambda p: p["hub_files"].append({"owner": "sam"}), "needs `path` and `owner`"),
    ],
)
def test_validation_errors(plan_dict, mutate, needle):
    mutate(plan_dict)
    assert any(needle in e for e in errors_of(plan_dict)), errors_of(plan_dict)


def test_all_errors_reported_together(plan_dict):
    plan_dict["tasks"][0]["owner"] = "nobody"
    plan_dict["tasks"][1]["status"] = "bogus"
    assert len(errors_of(plan_dict)) >= 2


@pytest.mark.parametrize(
    "path, kind, owner",
    [
        ("src/api/cart/add.py", "task", "shaurya"),
        ("src\\api\\cart\\add.py", "task", "shaurya"),  # Windows-style relative path
        ("src/pages/checkout/index.tsx", "task", "friend"),
        ("src/types/cart.ts", "hub", "shaurya"),  # hub wins over task owns
        ("package.json", "hub", "shaurya"),
        (".lanes/contracts/cart-api.md", "contract", "shaurya"),  # contract wins over .lanes/
        (".lanes/contracts/checkout-events.md", "contract", "friend"),
        (".lanes/notices/x.md", "lanes", None),
        ("README.md", "unowned", None),
    ],
)
def test_owner_of(repo, path, kind, owner):
    own = load_plan(repo).owner_of(path)
    assert (own.kind, own.owner) == (kind, owner)


def test_most_specific_pattern_wins(plan_dict):
    plan_dict["tasks"][0]["owns"].append("tests/**")
    plan_dict["tasks"][1]["owns"].append("tests/e2e_phase0.md")
    plan = parse_plan(plan_dict)
    assert plan.owner_of("tests/test_x.py").owner == "shaurya"
    assert plan.owner_of("tests/e2e_phase0.md").owner == "friend"


def test_nested_glob_belongs_to_the_more_specific_task(plan_dict):
    plan_dict["tasks"][0]["owns"].append("tests/**")  # T1, rank 1
    plan_dict["tasks"][1]["owns"].append("tests/e2e_results/**")  # T2, rank 2
    plan = parse_plan(plan_dict)
    own = plan.owner_of("tests/e2e_results/x.md")
    assert (own.kind, own.owner, own.task.id) == ("task", "friend", "T2")
    assert plan.owner_of("tests/test_x.py").task.id == "T1"
    assert check_lane(plan, "friend", "tests/e2e_results/x.md").allowed
    assert not check_lane(plan, "shaurya", "tests/e2e_results/x.md").allowed


def test_this_repos_plan_gives_e2e_results_to_t2():
    plan = load_plan(REPO)
    own = plan.owner_of("tests/e2e_results/x.md")
    assert own.kind == "task" and own.task.id == "T2"
    assert plan.owner_of("tests/test_plan.py").task.id == "T1"


def test_owns_overlaps(plan_dict):
    plan_dict["tasks"][0]["owns"].append("tests/**")
    plan_dict["tasks"][1]["owns"].append("tests/e2e_results/**")
    plan_dict["tasks"][1]["owns"].append("src/emails/templates/*.html")  # inside T3's src/emails/**
    overlaps = {(o.a.id, o.a_glob, o.b.id, o.b_glob): (o.winner.id, o.reason) for o in parse_plan(plan_dict).owns_overlaps()}
    assert overlaps == {
        ("T1", "tests/**", "T2", "tests/e2e_results/**"): ("T2", "more specific"),
        ("T2", "src/emails/templates/*.html", "T3", "src/emails/**"): ("T2", "more specific"),
    }


def test_equally_specific_globs_go_to_the_lower_rank(plan_dict):
    plan_dict["tasks"][2]["owns"].append("src/pages/checkout/*")  # T3 (rank 3); same literal prefix as T2's glob
    plan = parse_plan(plan_dict)
    [o] = plan.owns_overlaps()
    assert (o.winner.id, o.reason) == ("T2", "lower rank")
    assert plan.owner_of("src/pages/checkout/x.tsx").task.id == "T2"


def test_no_overlaps_in_the_fixture_plan(repo):
    assert load_plan(repo).owns_overlaps() == []


def test_check_lane_messages(repo):
    plan = load_plan(repo)
    ok = check_lane(plan, "shaurya", "src/api/cart/add.py")
    assert ok.allowed
    denied = check_lane(plan, "shaurya", "src/pages/checkout/index.tsx")
    assert not denied.allowed
    assert "belongs to friend" in denied.reason and "lanes request" in denied.reason
    contract = check_lane(plan, "friend", ".lanes/contracts/cart-api.md")
    assert not contract.allowed and "contract `cart-api`" in contract.reason
    unowned = check_lane(plan, "friend", "README.md")
    assert not unowned.allowed and "no task" in unowned.reason
    assert check_lane(plan, "friend", ".lanes/handoffs/T2-1.md").allowed


def test_identity_lanes_user_wins(repo):
    plan = load_plan(repo)
    assert resolve(plan, repo, env={"LANES_USER": "Friend"}).member_id == "friend"
    bad = resolve(plan, repo, env={"LANES_USER": "ghost"})
    assert bad.member_id is None and "not a member" in bad.detail


def test_identity_from_git_email(repo):
    plan = load_plan(repo)
    ident = resolve(plan, repo, env={})
    assert ident.member_id == "shaurya" and ident.source == "git user.email"


def test_identity_unknown_email(repo):
    from conftest import git

    git(repo, "config", "user.email", "stranger@example.com")
    ident = resolve(load_plan(repo), repo, env={})
    assert ident.member_id is None and "LANES_USER" in ident.detail
