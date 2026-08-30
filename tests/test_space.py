"""Refining a flat check into survivors, sound prunes, demotions, and gaps.

A member decides one rule at a time; `refine` runs the member across a rule
set and keeps a witness for every one, whatever it decided. These pin the
substrate itself, and one integration check that `enforce.against_with_witness`
does not silently disagree with `enforce.against` on the same fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.enforce import COUNT_AT_MOST, FILES_MATCHING, against, against_with_witness
from vesta.graph import Edge, Graph, Node
from vesta.rules import Found, Rule
from vesta.space import (
    Basis,
    Outcome,
    Verdict,
    Witness,
    demote,
    evaluated,
    gap,
    refine,
    sound_prune,
    survive,
)


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Graph, Path]:
    (tmp_path / "a.py").write_text("def loader():\n    pass\n", encoding="utf-8")
    nodes = [Node(id="n1", name="loader", path="a.py", line=0, kind=12)]
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in nodes}, edges=[])
    return graph, tmp_path


def test_a_surviving_rule_passes_through_and_is_witnessed():
    rule = Rule(text="a rule nothing objects to", horizon="standing")
    result = refine([rule], [lambda r: survive()])

    assert result.survivors == [rule]
    assert len(result.witness) == 1
    assert result.witness[0].verdict == Verdict.SURVIVES


def test_a_sound_pruned_rule_is_recorded_with_its_reason():
    rule = Rule(text="a rule about nothing in this repo", horizon="standing")
    result = refine([rule], [lambda r: sound_prune("no subject in this repo")])

    assert result.survivors == []
    assert len(result.pruned) == 1
    assert result.pruned[0].reason == "no subject in this repo"
    assert len(result.witness) == 1


def test_a_demoted_rule_is_kept_apart_from_a_sound_prune():
    rule = Rule(text="a rule worth deprioritising", horizon="standing")
    result = refine([rule], [lambda r: demote("a poor-fit check")])

    assert result.survivors == []
    assert result.pruned == []
    assert len(result.demoted) == 1


def test_a_rule_with_no_check_becomes_a_gap_not_a_silent_drop():
    rule = Rule(text="a rule nothing can check yet", horizon="standing")
    result = refine([rule], [lambda r: gap("no check was ever derived")])

    assert result.survivors == []
    assert len(result.gaps) == 1
    assert len(result.witness) == 1  # present, not merely absent


def test_first_non_survive_member_wins_and_later_members_are_not_asked():
    calls = []

    def first(rule):
        return sound_prune("excluded by the first member")

    def second(rule):
        calls.append(rule)
        return survive()

    rule = Rule(text="a rule", horizon="standing")
    refine([rule], [first, second])

    assert calls == []  # second member never ran


def test_against_with_witness_survivors_match_against_held_and_broken(repo):
    graph, root = repo
    found = Found(
        rules=[
            Rule(
                text="loader must exist",
                horizon="standing",
                look_for=FILES_MATCHING,
                pattern=r"loader",
                holds_when=COUNT_AT_MOST,
                how_many=99,
            ),
            Rule(
                text="no .env files here",
                horizon="standing",
                look_for=FILES_MATCHING,
                pattern=r"\.env$",
                holds_when=COUNT_AT_MOST,
                how_many=0,
            ),
        ]
    )

    verdict = against(found, graph, root)
    result = against_with_witness(found, graph, root)

    checked_texts = {f.rule for f in verdict.findings if not f.undecided}
    survivor_texts = {r.stated or r.text for r in result.survivors}
    assert survivor_texts <= checked_texts


# ── What a judgement rests on ───────────────────────────────────────────────


def test_a_basis_nobody_stated_claims_the_least():
    """The default has to be the kind that cannot be re-run.

    A judgement whose basis nobody stated is one nothing can replay, and
    defaulting the other way is how a record comes to imply that all of its
    reasoning is checkable when some of it was somebody reading.
    """
    assert Outcome(verdict=Verdict.SOUND_PRUNE).basis is Basis.ASSERTED
    assert Witness(rule="x", verdict=Verdict.GAP).basis is Basis.ASSERTED
    assert not Witness(rule="x", verdict=Verdict.GAP).replayable


def test_only_re_runnable_kinds_count_as_replayable():
    """Structural is a predicate over the graph and byte is a hash comparison;
    both either agree with what was recorded or do not. An assertion is somebody
    having read the code, and re-reading it proves nothing about the first read.
    """
    def witness(basis):
        return Witness(rule="x", verdict=Verdict.SOUND_PRUNE, basis=basis)

    assert witness(Basis.STRUCTURAL).replayable
    assert witness(Basis.BYTE).replayable
    assert not witness(Basis.ASSERTED).replayable


def test_a_gap_rests_on_nothing_re_runnable():
    """Nothing was decided, so there is nothing replay could confirm."""
    assert gap("no check exists for this").basis is Basis.ASSERTED


def test_refinement_carries_the_basis_through():
    """Dropped between the outcome and the witness, it would be as though the
    member had never stated it."""
    result = refine(
        [Rule(text="never a bare except")],
        [lambda r: sound_prune("nothing matches", Basis.STRUCTURAL)],
    )

    assert result.witness[0].basis is Basis.STRUCTURAL
    assert result.replayable == 1.0


def test_a_result_states_its_own_replayable_share():
    """Reported rather than assumed: one judgement a reader can verify and one
    they can only take or leave is the difference between an audit and a
    summary."""
    result = refine(
        [Rule(text="first"), Rule(text="second")],
        [
            lambda r: (
                sound_prune("structural", Basis.STRUCTURAL)
                if "first" in (r.stated or r.text)
                else demote("somebody read it")
            )
        ],
    )

    assert result.replayable == 0.5


# ── A verdict pooled from an authority ──────────────────────────────────────


def test_an_evaluated_verdict_demotes_and_never_prunes():
    """`SOUND_PRUNE` means certain and not to be reopened, and a probabilistic
    result is precisely not that.

    Allowing an evaluation to prune would let a wrong call silently remove the
    right answer from the space with no way back; as a demotion it costs a
    ranking rather than a candidate.
    """
    outcome = evaluated("the retry-policy skill says otherwise", authority="retry-policy")

    assert outcome.verdict is Verdict.DEMOTE
    assert outcome.basis is Basis.EVALUATED


def test_an_evaluated_verdict_carries_what_it_was_shown():
    """The retrieval is deterministic even where the judgement is not. When a
    pooled verdict turns out wrong the cause is usually what was put in front of
    it, and a record that blends the two cannot say which."""
    outcome = evaluated("x", authority="retry-policy", evidence=["a.py:10:work"])

    assert outcome.authority == "retry-policy"
    assert outcome.evidence == ["a.py:10:work"]


def test_an_evaluation_is_rerunnable_but_not_replayable():
    """Re-running a computation answers *does this still hold*; re-running an
    evaluation answers *does it still evaluate the same way*. Counting the
    second as the first would let a bundle report as deterministic a share of
    its reasoning that is not.
    """
    pooled = Witness(rule="x", verdict=Verdict.DEMOTE, basis=Basis.EVALUATED)
    read = Witness(rule="x", verdict=Verdict.DEMOTE, basis=Basis.ASSERTED)
    computed = Witness(rule="x", verdict=Verdict.SOUND_PRUNE, basis=Basis.STRUCTURAL)

    assert not pooled.replayable and pooled.rerunnable
    assert not read.replayable and not read.rerunnable
    assert computed.replayable and computed.rerunnable
