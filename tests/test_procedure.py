"""A control-flow template, and the refusal that keeps it honest.

Most of these tests are about the one discipline the module exists to
enforce: a branch-shaped outcome that does not say what triggers it is
refused at construction, not accepted and flagged later.
"""

from __future__ import annotations

import pytest

from vesta.graph import Edge, Graph, Node
from vesta.procedure import (
    BRANCHES,
    CONTINUES,
    EXITS,
    Procedure,
    Procedures,
    Step,
    Then,
    as_terms,
    keep,
    recall,
)
from vesta.traverse import attach


def test_branch_outcome_without_when_is_refused():
    with pytest.raises(ValueError):
        Then(source="a", target="b", outcome=BRANCHES)


def test_branch_outcome_with_when_is_accepted():
    then = Then(source="a", target="b", outcome=BRANCHES, when="the build fails")
    assert then.when == "the build fails"


def test_continues_outcome_needs_no_when():
    then = Then(source="a", target="b", outcome=CONTINUES)
    assert then.when == ""


def test_unknown_outcome_is_refused():
    with pytest.raises(ValueError):
        Then(source="a", target="b", outcome="teleports")


def test_procedures_round_trip_through_keep_and_recall(tmp_path):
    procedures = Procedures(
        procedures=[
            Procedure(
                id="release",
                label="ship a release",
                steps=[Step(id="a", label="run the tests"), Step(id="b", label="tag the commit")],
                thens=[Then(source="a", target="b", outcome=CONTINUES)],
            )
        ]
    )
    keep(procedures, tmp_path)
    recalled = recall(tmp_path)
    assert recalled.get("release").label == "ship a release"
    assert len(recalled.get("release").thens) == 1


def test_recall_with_nothing_kept_is_empty(tmp_path):
    assert recall(tmp_path).procedures == []


def test_after_and_leads_to_are_inverse_indices():
    procedure = Procedure(
        id="p",
        label="a procedure",
        steps=[Step(id="a", label="first"), Step(id="b", label="second"), Step(id="c", label="third")],
        thens=[
            Then(source="a", target="b", outcome=CONTINUES),
            Then(source="b", target="c", outcome=CONTINUES),
        ],
    )
    assert [t.target for t in procedure.after("a")] == ["b"]
    assert [t.source for t in procedure.leads_to("b")] == ["a"]
    assert procedure.leads_to("a") == []


def test_terminal_steps_have_no_continuation_or_only_end_outcomes():
    procedure = Procedure(
        id="p",
        label="a procedure",
        steps=[Step(id="a", label="first"), Step(id="b", label="last")],
        thens=[Then(source="a", target="b", outcome=CONTINUES), Then(source="b", outcome=EXITS)],
    )
    terminal_ids = {s.id for s in procedure.terminal()}
    assert terminal_ids == {"b"}


def test_as_terms_reuses_traverse_attach_end_to_end():
    procedure = Procedure(
        id="p",
        label="a procedure",
        steps=[Step(id="a", label="resolve symbol references", kind="activity")],
    )
    graph = Graph(
        nodes={
            "n1": Node(id="n1", name="_resolve_with", path="graph.py", line=10, kind=12),
        },
        edges=[],
    )
    mapped = attach(graph, as_terms(procedure), floor=0.3)
    assert len(mapped.attachments) == 1
    assert mapped.attachments[0].node == "n1"
