"""Plan-change notices: the plan owner's ownership edits notify every affected task."""

from __future__ import annotations

import pytest
from conftest import git, write_plan

from lanes import notices as N
from lanes.plan import PlanError, load_plan, parse_plan
from lanes.plandiff import record_plan_change


def edit_plan(repo, plan_dict, editor="shaurya"):
    write_plan(repo, plan_dict)
    return record_plan_change(repo, load_plan(repo), editor, session="s1")


def test_plan_owner_defaults_to_lowest_rank_owner_and_can_be_set(plan_dict):
    assert parse_plan(plan_dict).owner == "shaurya"
    plan_dict["owner"] = "sam"
    assert parse_plan(plan_dict).owner == "sam"
    plan_dict["owner"] = "ghost"
    with pytest.raises(PlanError, match="plan `owner`"):
        parse_plan(plan_dict)


def test_moving_files_between_tasks_notifies_the_other_task(repo, plan_dict):
    plan_dict["tasks"][1]["owns"] = ["src/pages/checkout/**"]  # T2 loses components/
    plan_dict["tasks"][0]["owns"].append("src/components/checkout/**")  # T1 gains it
    notice, created = edit_plan(repo, plan_dict)
    assert created and notice.kind == "plan" and notice.file == ".lanes/plan.yaml"
    assert notice.to_tasks == ["T2"] and notice.to_members == ["friend"]  # not sam (T3 unchanged), not me
    assert "~ T1 owns: +src/components/checkout/**" in notice.body
    assert "~ T2 owns: -src/components/checkout/**" in notice.body
    assert notice.base == git(repo, "rev-parse", "HEAD").strip()
    plan = load_plan(repo)
    assert [n.id for n in N.unread_for(repo, plan, "friend")] == [notice.id]
    assert N.unread_for(repo, plan, "shaurya") == [] and N.unread_for(repo, plan, "sam") == []


def test_plan_notices_ignore_rank(repo, plan_dict):
    """Unlike contract notices, a lower-rank task still hears that its files moved."""
    plan_dict["owner"] = "sam"  # rank-3 plan owner
    git(repo, "add", "-A")
    write_plan(repo, plan_dict)
    git(repo, "commit", "-q", "-am", "sam owns the plan")
    plan_dict["tasks"][0]["uses"] = []  # T1 (rank 1) stops using checkout-events
    notice, _ = edit_plan(repo, plan_dict, editor="sam")
    assert notice.to_tasks == ["T1"] and notice.to_members == ["shaurya"]
    assert "~ T1 uses: -checkout-events" in notice.body


def test_reassigning_a_task_notifies_old_and_new_owner(repo, plan_dict):
    plan_dict["tasks"][2]["owner"] = "friend"
    notice, _ = edit_plan(repo, plan_dict)
    assert notice.to_tasks == ["T3"] and notice.to_members == ["friend", "sam"]
    assert "~ T3 owner: sam -> friend" in notice.body
    plan = load_plan(repo)
    assert N.unread_for(repo, plan, "sam")  # sam no longer owns T3 but still hears about it


def test_status_only_and_own_task_changes_send_nothing(repo, plan_dict):
    plan_dict["tasks"][1]["status"] = "in_progress"
    plan_dict["tasks"][0]["owns"].append("src/lib/**")  # only my own task
    assert edit_plan(repo, plan_dict) == (None, False)
    assert N.list_notices(repo) == []


def test_only_the_plan_owner_sends_plan_notices(repo, plan_dict):
    plan_dict["tasks"][0]["owns"] = ["src/api/cart/**"]
    assert edit_plan(repo, plan_dict, editor="friend") == (None, False)
    assert N.list_notices(repo) == []


def test_repeat_edits_rewrite_one_notice_and_undo_withdraws_it(repo, plan_dict):
    original = [list(t["owns"]) for t in plan_dict["tasks"]]
    plan_dict["tasks"][1]["owns"].append("src/hooks/checkout/**")
    first, new1 = edit_plan(repo, plan_dict)
    plan_dict["tasks"][2]["owns"].append("src/emails/templates/**")
    second, new2 = edit_plan(repo, plan_dict)
    assert new1 and not new2 and first.id == second.id and len(N.list_notices(repo)) == 1
    assert second.to_tasks == ["T2", "T3"] and second.to_members == ["friend", "sam"]
    for t, owns in zip(plan_dict["tasks"], original):
        t["owns"] = owns
    assert edit_plan(repo, plan_dict) == (None, False)
    assert N.list_notices(repo) == []  # unread, so it was withdrawn


def test_amended_summary_survives_later_edits(repo, plan_dict):
    plan_dict["tasks"][1]["owns"].append("src/hooks/checkout/**")
    n, _ = edit_plan(repo, plan_dict)
    N.amend(repo, "shaurya", n.id, summary="T2 now also owns src/hooks/checkout/.")
    plan_dict["tasks"][1]["owns"].append("src/hooks/cart/**")
    n2, _ = edit_plan(repo, plan_dict)
    assert n2.summary == "T2 now also owns src/hooks/checkout/." and "+src/hooks/cart/**" in n2.body


def test_a_read_notice_is_never_rewritten(repo, plan_dict):
    plan_dict["tasks"][1]["owns"].append("src/hooks/checkout/**")
    first, _ = edit_plan(repo, plan_dict)
    N.mark_read(repo, "friend", [first.id])
    plan_dict["tasks"][1]["owns"].append("src/hooks/cart/**")
    second, created = edit_plan(repo, plan_dict)
    assert created and second.id != first.id
