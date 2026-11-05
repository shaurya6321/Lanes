from lanes import notices as N
from lanes.plan import load_plan


def test_rank1_contract_change_notifies_higher_ranks(repo):
    plan = load_plan(repo)
    assert N.route_change(plan, plan.task("T1"), plan.contract("cart-api")) == ["T2", "T3"]


def test_rank2_change_never_notifies_rank1(repo):
    """T1 (rank 1) uses checkout-events, but T2 (rank 2) owns it: T1 must never hear about it."""
    plan = load_plan(repo)
    assert "checkout-events" in plan.task("T1").uses
    targets = N.route_change(plan, plan.task("T2"), plan.contract("checkout-events"))
    assert targets == ["T3"]
    assert all(plan.task(t).rank > 2 for t in targets)


def test_top_rank_change_notifies_nobody(repo):
    plan = load_plan(repo)
    assert N.route_change(plan, plan.task("T3"), None) == []


def test_record_change_writes_notice_only_for_higher_ranks(repo):
    plan = load_plan(repo)
    rel = ".lanes/contracts/checkout-events.md"
    notice, created = N.record_change(repo, plan, "friend", rel, plan.owner_of(rel), ["+ OrderPlaced(id, total)"])
    assert created and notice.to_tasks == ["T3"] and notice.to_members == ["sam"]
    assert notice.from_rank == 2 and notice.contract == "checkout-events"
    assert N.unread_for(repo, plan, "shaurya") == []
    assert [n.id for n in N.unread_for(repo, plan, "sam")] == [notice.id]


def test_notice_round_trip_and_mark_read(repo):
    plan = load_plan(repo)
    rel = ".lanes/contracts/cart-api.md"
    notice, _ = N.record_change(repo, plan, "shaurya", rel, plan.owner_of(rel), ["- addItem(sku, qty)", "+ addItem(sku, qty, note)"])
    parsed = N.parse_notice(notice.path)
    assert parsed.to_tasks == ["T2", "T3"] and parsed.body.startswith("- addItem")
    assert len(N.unread_for(repo, plan, "friend")) == 1
    assert N.mark_read(repo, "friend", [notice.id]) == 1
    assert N.mark_read(repo, "friend", [notice.id]) == 0  # idempotent
    assert N.unread_for(repo, plan, "friend") == []
    assert len(N.unread_for(repo, plan, "sam")) == 1  # read state is per member


def test_same_session_edits_coalesce_until_read(repo):
    plan = load_plan(repo)
    rel = ".lanes/contracts/cart-api.md"
    own = plan.owner_of(rel)
    first, new1 = N.record_change(repo, plan, "shaurya", rel, own, ["+ a"], session="s1")
    second, new2 = N.record_change(repo, plan, "shaurya", rel, own, ["+ b"], session="s1")
    assert new1 and not new2 and first.id == second.id
    assert N.parse_notice(first.path).body.splitlines() == ["+ a", "+ b"]
    N.mark_read(repo, "friend", [first.id])
    third, new3 = N.record_change(repo, plan, "shaurya", rel, own, ["+ c"], session="s1")
    assert new3 and third.id != first.id


def test_hub_file_change_goes_to_dependents(repo):
    plan = load_plan(repo)
    notice, _ = N.record_change(repo, plan, "shaurya", "package.json", plan.owner_of("package.json"), ["+ react 19"])
    assert notice.file == "package.json" and notice.to_tasks == ["T2", "T3"]


def test_describe_change_is_short():
    old = "\n".join(f"line {i}" for i in range(20))
    new = "\n".join(f"LINE {i}" for i in range(20))
    lines = N.describe_change(old, new)
    assert len(lines) == N.MAX_BODY_LINES and lines[-1].startswith("... (+")


def test_notice_redacts_secrets(repo):
    plan = load_plan(repo)
    rel = ".lanes/contracts/cart-api.md"
    notice, _ = N.record_change(repo, plan, "shaurya", rel, plan.owner_of(rel), ["+ STRIPE_KEY=sk_live_51Habcdefghijklmnop"])
    text = notice.path.read_text()
    assert "sk_live_51Habcdefghijklmnop" not in text and "[REDACTED]" in text


def test_request_goes_to_owner_regardless_of_rank(repo):
    plan = load_plan(repo)
    req = N.make_request(repo, plan, "friend", "Please add `currency` to Cart\nNeeded for the price label.", rel="src/types/cart.ts")
    assert req.kind == "request" and req.to_members == ["shaurya"] and req.from_rank == 2
    assert [n.id for n in N.unread_for(repo, plan, "shaurya")] == [req.id]


# Exact front matter an agent wrote in the live e2e run: the unquoted summary
# contains ': ' ("id: str"), which is invalid YAML. It must still be read.
AGENT_EDITED = """---
id: 20261105T132621Z-t1-example-api
kind: change
from_member: shaurya
from_task: T1
from_rank: 1
to_tasks:
- T2
to_members:
- friend
contract: example-api
created: '2026-11-05T13:26:21Z'
session: 1b8753aa-10e1-45ea-9d61-ce5917fb72da
summary: Added `getItem(id: str) -> Item` to the example-api Interface; it raises a 404 error when the item is missing.
---
+ getItem(id: str) -> Item  # returns 404 error if missing
New function: `getItem`, takes `id` (str), returns `Item`.
"""


def test_agent_edited_notice_with_invalid_yaml_is_still_read(repo):
    path = repo / ".lanes" / "notices" / "20261105T132621Z-t1-example-api.md"
    path.write_text(AGENT_EDITED)
    n = N.parse_notice(path)
    assert n is not None
    assert n.to_tasks == ["T2"] and n.to_members == ["friend"] and n.from_rank == 1
    assert n.created == "2026-11-05T13:26:21Z" and n.contract == "example-api"
    assert n.summary.startswith("Added `getItem(id: str) -> Item`")
    plan = load_plan(repo)
    assert [x.id for x in N.unread_for(repo, plan, "friend")] == [n.id]
    assert N.unreadable_notices(repo) == []


def test_unparseable_notice_is_reported_not_hidden(repo):
    (repo / ".lanes" / "notices" / "broken.md").write_text("no front matter at all\n")
    assert N.unreadable_notices(repo) == [".lanes/notices/broken.md"]


def test_a_committed_notice_is_never_extended(repo):
    from conftest import git

    plan = load_plan(repo)
    rel = ".lanes/contracts/cart-api.md"
    own = plan.owner_of(rel)
    first, _ = N.record_change(repo, plan, "shaurya", rel, own, ["+ a"], session="s1")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "notice")
    second, created = N.record_change(repo, plan, "shaurya", rel, own, ["+ b"], session="s1")
    assert created and second.id != first.id
    assert N.parse_notice(first.path).body == "+ a"
