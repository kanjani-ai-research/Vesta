"""What to do when somebody asks for something mid-build.

The rule is not a calculation: behaviour agreed is behaviour fixed, and a
change to it is refused rather than weighed. What is measured is only the
things that do not touch behaviour — where a structural change is small enough
to absorb, and where it is large enough to be better after delivery.

Both directions matter equally here. Missing a behavioural change means
building something that invalidates agreed work. Refusing an ordinary refactor
means a tool nobody can work with — and every refactor in a todo app mentions
tasks, so the naive version refused all of them.
"""

from __future__ import annotations

import pytest

from vesta.asked import ABSORB, AFTER, REFUSED, SURE, act, where_it_lands
from vesta.contract import Behaviour, Contract, keep, recall, sign


@pytest.fixture
def agreed(tmp_path):
    keep(
        Contract(
            goal="a todo app with tags",
            behaviours=[
                Behaviour(does="a user can file a task"),
                Behaviour(does="a user can tag a task"),
                Behaviour(does="a user can filter tasks by tag"),
            ],
        ),
        tmp_path,
    )
    sign(tmp_path)
    return tmp_path


# ── Behaviour does not move ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "said",
    [
        "actually tasks should be shared between users, not private",
        "a user should also be able to delete a task",
        "tasks should no longer be editable",
        "make it multi-user",
        "only an admin can file a task",
    ],
)
def test_a_behavioural_change_is_refused(agreed, said):
    assert where_it_lands(said, agreed).verdict == REFUSED


def test_a_refusal_names_what_it_would_alter(agreed):
    landing = where_it_lands("make it multi-user", agreed)
    assert landing.behaviours
    assert "changes what was agreed" in landing.describe()


def test_a_refusal_offers_the_choice_rather_than_making_it(agreed):
    """Their project. A tool that cannot be overruled is one people fight."""
    said = where_it_lands("make it multi-user", agreed).what_to_say().lower()
    assert "carry on" in said
    assert "start over" in said
    assert "after delivery" in said


def test_a_refused_change_does_not_alter_the_contract(agreed):
    before = [b.does for b in recall(agreed).behaviours]
    act("make it multi-user", agreed)
    assert [b.does for b in recall(agreed).behaviours] == before


def test_a_refused_change_is_kept_for_after_delivery(agreed):
    act("make it multi-user", agreed)
    assert recall(agreed).deferred == ["make it multi-user"]


# ── Structure is not behaviour ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "said",
    [
        "move the task storage into its own module",
        "use a dataclass for the task record",
        "split the storage file in two",
        "rename file_task to create_task",
        "use postgres instead of sqlite",
    ],
)
def test_an_ordinary_refactor_is_not_refused(agreed, said):
    """Every refactor in a todo app mentions tasks. Refusing on that basis is
    not a strict contract, it is a broken tool."""
    assert where_it_lands(said, agreed, reaches=3).verdict != REFUSED


def test_a_small_structural_change_is_absorbed(agreed):
    landing = where_it_lands("use postgres instead of sqlite", agreed, reaches=3)
    assert landing.verdict == ABSORB
    assert "3 definition" in landing.describe()


def test_a_wide_structural_change_waits_for_delivery(agreed):
    """The same change is trivial behind one adapter and a different project
    when the substrate leaked into forty call sites."""
    landing = where_it_lands(
        "switch the whole storage layer to a document store", agreed, reaches=40
    )
    assert landing.verdict == AFTER
    assert "40 definition" in landing.describe()


def test_the_same_change_lands_differently_by_spread(agreed):
    said = "switch the storage layer to a document store"
    assert where_it_lands(said, agreed, reaches=2).verdict == ABSORB
    assert where_it_lands(said, agreed, reaches=90).verdict == AFTER


def test_what_it_reaches_is_reported_rather_than_reduced(agreed):
    """Forty mechanical edits and four subtle ones count the same, so the
    number is shown rather than turned into a verdict nobody can argue with."""
    landing = where_it_lands("use postgres instead of sqlite", agreed, reaches=7)
    assert landing.reaches == 7
    assert "7" in landing.describe()


# ── Something that names no behaviour ───────────────────────────────────────


@pytest.mark.parametrize(
    "said",
    ["make it do a somersault", "add a convolutional neural network", "make it pop"],
)
def test_something_that_names_no_behaviour_gets_sure(agreed, said):
    landing = where_it_lands(said, agreed)
    assert landing.verdict == SURE
    assert landing.describe() == "Sure."


def test_nothing_smug_is_said_about_it(agreed):
    """Telling somebody their request was pointless is worse than saying
    nothing."""
    said = where_it_lands("make it do a somersault", agreed).what_to_say().lower()
    for smug in ("no effect", "cannot", "pointless", "not possible", "absurd"):
        assert smug not in said


def test_it_is_noted_rather_than_deferred(agreed):
    act("make it do a somersault", agreed)
    kept = recall(agreed)
    assert kept.noted == ["make it do a somersault"]
    assert kept.deferred == []


# ── Before anything is agreed ───────────────────────────────────────────────


def test_nothing_is_refused_when_nothing_was_agreed(tmp_path):
    """Before a contract exists there is nothing to depart from."""
    assert where_it_lands("make it multi-user", tmp_path).verdict == ABSORB


def test_an_unsigned_contract_binds_nothing(tmp_path):
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can file a task")]), tmp_path)
    assert where_it_lands("a user should also delete tasks", tmp_path).verdict == ABSORB


def test_nothing_said_is_nothing_to_decide(agreed):
    assert where_it_lands("   ", agreed).verdict == SURE


def test_ordinary_work_is_not_answered_with_sure(agreed):
    """"Add a test for filing" is a request to do something. Answering it
    with "sure" would be a tool declining its job politely."""
    assert where_it_lands("add a test for filing", agreed, reaches=2).verdict == ABSORB


# ── Reaching the agent on the way in ────────────────────────────────────────


def test_a_behavioural_change_is_flagged_before_it_is_built(agreed):
    """A change arrives as ordinary conversation, and an agent that notices
    after building it has already spent the work."""
    from vesta.inject import _a_change_to_what_was_agreed as check

    said = check("actually make it multi-user", str(agreed))
    assert "do not build it" in said
    assert "after delivery" in said


def test_the_agent_makes_the_final_call(agreed):
    """A pattern is not a reading of somebody's meaning, and the judgement
    belongs where every other judgement here does."""
    from vesta.inject import _a_change_to_what_was_agreed as check

    said = check("actually make it multi-user", str(agreed))
    assert "judge for yourself" in said.lower()
    assert "if it does not, carry on" in said.lower()


def test_something_inert_is_answered_with_sure(agreed):
    from vesta.inject import _a_change_to_what_was_agreed as check

    said = check("make it do a somersault", str(agreed)).lower()
    assert '"sure"' in said
    assert "do not argue" in said


def test_an_ordinary_request_is_not_mentioned(agreed):
    from vesta.inject import _a_change_to_what_was_agreed as check

    assert check("use postgres instead of sqlite", str(agreed)) == ""


def test_nothing_is_said_before_a_contract_is_signed(tmp_path):
    from vesta.inject import _a_change_to_what_was_agreed as check

    assert check("actually make it multi-user", str(tmp_path)) == ""
