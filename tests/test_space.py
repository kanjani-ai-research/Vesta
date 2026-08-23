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
from vesta.space import Verdict, demote, gap, refine, sound_prune, survive


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
