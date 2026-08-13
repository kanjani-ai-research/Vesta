"""What was agreed to be built, and whether it has been.

A loop needs a target that does not move. Without one "done" is unreachable —
any late correction resets the goal and the loop runs forever, which is the
failure every autonomous coding tool shares.

The strictness is the feature: behaviour agreed is behaviour fixed. Most of
these tests are about that holding.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vesta.contract import (
    WHERE,
    Behaviour,
    Contract,
    defer,
    keep,
    met,
    recall,
    sign,
)


@pytest.fixture
def agreed(tmp_path):
    contract = Contract(
        goal="a todo app with tags",
        behaviours=[
            Behaviour(does="a user can file a task"),
            Behaviour(does="a user can tag a task"),
        ],
        constraints=["SQLite, no external services"],
        inferred=["tasks persist between runs", "a task has a title"],
    )
    keep(contract, tmp_path)
    return tmp_path


# ── What the user is shown ──────────────────────────────────────────────────


def test_verification_shows_behaviour_the_goal_and_stated_design(agreed):
    said = recall(agreed).to_verify()
    assert "a todo app with tags" in said
    assert "a user can file a task" in said
    assert "SQLite" in said


def test_verification_never_shows_what_was_inferred(agreed):
    """99% of users do not care what is under the hood, and a long spec is
    dismissed rather than checked — dismissal looks exactly like agreement."""
    said = recall(agreed).to_verify()
    assert "persist between runs" not in said
    assert "has a title" not in said


def test_verification_stays_short_however_complex_the_project(tmp_path):
    """Complexity lives in the inferred half, which is never displayed."""
    contract = Contract(
        goal="something complex",
        behaviours=[Behaviour(does=f"a user can do thing {n}") for n in range(8)],
        inferred=[f"an inferred detail {n}" for n in range(60)],
    )
    keep(contract, tmp_path)
    said = recall(tmp_path).to_verify()
    assert len(said.splitlines()) < 15
    assert "inferred detail" not in said


def test_nothing_is_said_about_design_when_none_was_stated(tmp_path):
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can y")]), tmp_path)
    assert "You asked for" not in recall(tmp_path).to_verify()


# ── The contract itself ─────────────────────────────────────────────────────


def test_it_lives_in_the_repository(agreed):
    """A contract nobody can see is not a contract."""
    assert (agreed / WHERE).is_file()
    assert "a user can file a task" in (agreed / WHERE).read_text(encoding="utf-8")


def test_it_is_not_binding_until_signed(agreed):
    assert not recall(agreed).signed
    sign(agreed)
    assert recall(agreed).signed


def test_signing_records_that_behaviour_is_fixed(agreed):
    sign(agreed)
    said = (agreed / WHERE).read_text(encoding="utf-8")
    assert "Behaviour does not change after this" in said


# ── When a behaviour counts as met ──────────────────────────────────────────


def test_an_implementation_with_no_test_is_not_met(agreed):
    """A loop could otherwise finish over code nothing checks."""
    met(agreed, "a user can file a task", nodes=["todo.py:file"])
    assert recall(agreed).met == []


def test_a_test_with_no_implementation_is_not_met(agreed):
    """The usual way an agent games a suite."""
    met(agreed, "a user can file a task", tests=["test_todo.py:test_file"])
    assert recall(agreed).met == []


def test_both_together_are_met(agreed):
    met(agreed, "a user can file a task", nodes=["todo.py:file"])
    met(agreed, "a user can file a task", tests=["test_todo.py:test_file"])
    assert [b.does for b in recall(agreed).met] == ["a user can file a task"]


def test_a_behaviour_nobody_agreed_to_is_ignored(agreed):
    met(agreed, "a user can do something nobody asked for", nodes=["x"], tests=["y"])
    assert recall(agreed).met == []


def test_it_is_complete_only_when_every_behaviour_is_met(agreed):
    sign(agreed)
    assert not recall(agreed).complete
    for does in ("a user can file a task", "a user can tag a task"):
        met(agreed, does, nodes=["x"], tests=["y"])
    assert recall(agreed).complete


def test_an_unsigned_contract_is_never_complete(agreed):
    for does in ("a user can file a task", "a user can tag a task"):
        met(agreed, does, nodes=["x"], tests=["y"])
    assert not recall(agreed).complete


def test_a_contract_with_no_behaviours_is_never_complete(tmp_path):
    keep(Contract(goal="x"), tmp_path)
    sign(tmp_path)
    assert not recall(tmp_path).complete


# ── A change after signing ──────────────────────────────────────────────────


def test_a_deferred_change_does_not_alter_the_behaviours(agreed):
    """The whole point of the strictness: the target does not move."""
    sign(agreed)
    before = [b.does for b in recall(agreed).behaviours]
    defer(agreed, "actually make it multi-user with accounts")
    assert [b.does for b in recall(agreed).behaviours] == before


def test_a_deferred_change_is_kept_for_after_delivery(agreed):
    defer(agreed, "make it multi-user")
    assert recall(agreed).deferred == ["make it multi-user"]
    assert "not built" in (agreed / WHERE).read_text(encoding="utf-8")


def test_the_same_change_is_not_recorded_twice(agreed):
    defer(agreed, "make it multi-user")
    defer(agreed, "make it multi-user")
    assert len(recall(agreed).deferred) == 1


def test_deferring_nothing_records_nothing(agreed):
    defer(agreed, "   ")
    assert recall(agreed).deferred == []


# ── Absence ─────────────────────────────────────────────────────────────────


def test_a_project_with_no_contract_says_so(tmp_path):
    assert recall(tmp_path) is None
    assert sign(tmp_path) is None
    assert met(tmp_path, "anything") is None


def test_an_unreadable_contract_is_not_a_missing_one(tmp_path):
    from vesta.contract import _where

    _where(tmp_path).write_text("not json", encoding="utf-8")
    assert recall(tmp_path) is None


# ── What gets elicited, and what does not ───────────────────────────────────
#
# The judgement is the agent's, so what is tested here is the instruction it
# reads: that it names the three categories, gives the shape of a behaviour,
# and says plainly that structure is inferred rather than asked about. The
# judgement itself is scored against `fixtures/what_to_elicit.json`.


HERE = Path(__file__).resolve().parent.parent
SPEC = HERE / "agents" / "vesta-spec.md"


def _flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_the_spec_agent_exists():
    assert SPEC.is_file()


def test_it_separates_the_three_kinds():
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "behaviours" in said
    assert "constraints" in said
    assert "structure" in said


def test_it_says_to_infer_structure_rather_than_ask():
    """The line that keeps verification short: complexity lives in the
    inferred half, and that half is never displayed."""
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "infer all of it and ask about none of it" in said


def test_it_never_infers_a_constraint():
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "if they did not say it, it is not a constraint" in said


def test_it_requires_a_behaviour_to_be_falsifiable():
    """The threshold that lets the loop measure itself."""
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "falsifiable" in said
    assert "without an opinion" in said


def test_it_gives_examples_of_what_is_not_a_behaviour():
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "the app is fast" in said
    assert "the code is clean" in said


def test_it_forbids_building_before_agreement():
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "do not ask the user anything and do not build" in said


def test_it_shows_only_what_verification_shows():
    """What it prints is what they agree to, verbatim. A user who reads one
    description and accepts another has agreed to nothing."""
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "do not summarise it in your own words" in said
    assert "do not list what you inferred" in said


def test_the_standard_covers_more_than_one_kind_of_project():
    """An instruction tuned on todo apps works only on todo apps."""
    import json

    cases = json.loads(
        (HERE / "tests" / "fixtures" / "what_to_elicit.json").read_text(encoding="utf-8")
    )["cases"]
    assert len(cases) >= 3
    for case in cases:
        assert case["said"]
        assert case["why"]
        assert case["must_not_ask_about"], "every case must name structure to infer"


# ── Something that has no effect ────────────────────────────────────────────


def test_something_inert_is_noted_rather_than_argued_with(agreed):
    """"Make it do a somersault" contradicts nothing and reaches nothing. The
    correct response is to note it and carry on — not to measure its blast
    radius and report solemnly that it is zero."""
    from vesta.contract import note

    note(agreed, "make it do a somersault")
    assert recall(agreed).noted == ["make it do a somersault"]


def test_what_was_noted_is_shown_so_its_author_sees_it_was_heard(agreed):
    from vesta.contract import note

    note(agreed, "make it do a somersault")
    said = recall(agreed).to_verify()
    assert "somersault" in said


def test_nothing_is_told_to_the_user_about_it_having_no_effect(agreed):
    """Telling somebody their request was pointless is worse than saying
    nothing. They can see it is not in the list above."""
    from vesta.contract import note

    note(agreed, "make it do a somersault")
    said = recall(agreed).to_verify().lower()
    for smug in ("no effect", "cannot", "will not", "ignored", "pointless"):
        assert smug not in said


def test_absurdity_is_not_the_test(agreed):
    """"Add a CNN to my todo list" may be sensible, and Vesta is in no
    position to say. What decides is whether it names a behaviour."""
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "the test is not whether it is absurd" in said
    assert "convolutional neural network" in said


def test_a_note_gates_nothing(agreed):
    """It is never built and never blocks completion."""
    from vesta.contract import note

    sign(agreed)
    note(agreed, "make it do a somersault")
    for does in ("a user can file a task", "a user can tag a task"):
        met(agreed, does, nodes=["x"], tests=["y"])
    assert recall(agreed).complete


def test_a_note_is_not_a_deferred_change(agreed):
    """`deferred` is for real work worth having after delivery. A somersault
    in that list is noise nobody wants to read six months later."""
    from vesta.contract import note

    note(agreed, "make it do a somersault")
    assert recall(agreed).deferred == []


def test_the_same_note_is_not_kept_twice(agreed):
    from vesta.contract import note

    note(agreed, "make it fly")
    note(agreed, "make it fly")
    assert len(recall(agreed).noted) == 1


def test_noting_nothing_records_nothing(agreed):
    from vesta.contract import note

    note(agreed, "  ")
    assert recall(agreed).noted == []


def test_the_spec_agent_is_told_not_to_argue_with_it():
    said = _flat(SPEC.read_text(encoding="utf-8"))
    assert "do not argue with it" in said
    assert 'say "sure" and nothing else' in said


def test_a_brief_with_nothing_agreed_reaches_the_agent():
    """The live failure. Everything was installed — the spec agent was listed,
    the server connected, every command registered — and the agent built the
    whole project with no contract, no verification and no consent, because
    the instruction lived in a skill whose description is about answering
    questions on an existing repository."""
    import tempfile

    from vesta import driving
    from vesta.inject import _something_to_build

    empty = Path(tempfile.mkdtemp())
    driving.start(empty)
    said = _something_to_build(
        "Build a command-line todo list.\n\nI want to be able to add a task, "
        "see my tasks, mark one done, and delete one. Tasks should survive "
        "between runs.",
        str(empty),
    )
    assert "$V contract" in said
    assert "do not start building until they have accepted" in said.lower()


def test_ordinary_work_does_not_demand_a_contract(tmp_path):
    """Demanding one for "add a field to the form" would make the tool
    insufferable."""
    from vesta.inject import _something_to_build

    from vesta import driving

    driving.start(tmp_path)
    (tmp_path / "app.py").write_text("def x():\n    return 1\n", encoding="utf-8")
    assert _something_to_build("add a field to the form", str(tmp_path)) == ""
    assert _something_to_build("why is this test failing?", str(tmp_path)) == ""
    assert _something_to_build("refactor the storage module", str(tmp_path)) == ""


def test_nothing_is_said_once_something_is_agreed(tmp_path):
    from vesta.inject import _something_to_build

    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can y")]), tmp_path)
    assert _something_to_build("build me a todo app", str(tmp_path)) == ""


def test_several_behaviours_may_share_one_implementation(agreed):
    """Common and correct: recording an expense is also where the over-budget
    warning happens. Both behaviours point at the same function."""
    sign(agreed)
    met(agreed, "a user can file a task", nodes=["e.py:cmd_add"], tests=["t.py:a"])
    met(agreed, "a user can tag a task", nodes=["e.py:cmd_add"], tests=["t.py:b"])

    kept = recall(agreed)
    assert [b.nodes for b in kept.behaviours] == [["e.py:cmd_add"], ["e.py:cmd_add"]]
    assert kept.complete


def test_recording_replaces_rather_than_accumulates(agreed):
    met(agreed, "a user can file a task", nodes=["one"], tests=["t"])
    met(agreed, "a user can file a task", nodes=["two"], tests=["t"])
    assert recall(agreed).behaviours[0].nodes == ["two"]


def test_a_batched_call_is_sorted_out_rather_than_refused():
    """`--node` accumulates, so an agent recording several behaviours in one
    invocation hands the last of them every node the others had. Found in a
    live run, where the final behaviour claimed all five.

    The information is not wrong, only misfiled — each name still says what
    implements something, and which something is already recorded. Refusing
    would throw away work an agent did and ask it to guess a different shape.
    """
    import tempfile

    where = Path(tempfile.mkdtemp())
    keep(
        Contract(goal="x", behaviours=[Behaviour(does=n) for n in "abcde"]), where
    )
    sign(where)
    for name in "abcd":
        met(where, name, nodes=[f"f.py:{name}"], tests=[f"t.py:{name}"])

    met(
        where,
        "e",
        nodes=["f.py:a", "f.py:b", "f.py:c", "f.py:d", "f.py:e"],
        tests=["t.py:e"],
    )

    kept = recall(where)
    assert [b.nodes for b in kept.behaviours] == [
        ["f.py:a"], ["f.py:b"], ["f.py:c"], ["f.py:d"], ["f.py:e"]
    ]
    assert kept.complete


def test_one_behaviour_may_span_several_definitions():
    """Sorting out a batch must not break the ordinary case."""
    import tempfile

    where = Path(tempfile.mkdtemp())
    keep(
        Contract(goal="x", behaviours=[Behaviour(does="a"), Behaviour(does="b")]),
        where,
    )
    sign(where)
    met(where, "a", nodes=["f.py:parse", "f.py:store", "f.py:report"], tests=["t.py:a"])
    assert recall(where).behaviours[0].nodes == [
        "f.py:parse", "f.py:store", "f.py:report"
    ]
