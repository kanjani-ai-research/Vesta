"""How long a rule holds, stated outright instead of only inferred.

`is_standing`'s repetition/time heuristic is a proxy for something a user
sometimes just says. These tests are about `horizon` overriding that proxy
when it is set, falling back to it unchanged when it is not, and about
`supersedes` letting a later rule replace an earlier one without both
standing at once.
"""

from __future__ import annotations

import json

from vesta.graph import Graph, Node
from vesta.rules import (
    HORIZON_DURABLE,
    HORIZON_STANDING,
    Found,
    Rule,
    Said,
    attach_rules,
)


def test_old_stored_rule_json_without_horizon_falls_back_to_heuristic():
    # Simulates a Rule persisted before `horizon` existed: the field is
    # simply absent from the payload, the way real stored JSON from before
    # this change would be.
    payload = {
        "text": "there should be one .env for the whole project",
        "first": 0.0,
        "last": 0.0,
    }
    rule = Rule.model_validate_json(json.dumps(payload))
    assert rule.horizon == ""
    # Said once, no time gap — the old heuristic says candidate, not standing.
    assert not rule.is_standing


def test_explicit_horizon_overrides_a_failing_heuristic():
    rule = Rule(
        text="never a bare except",
        first=100.0,
        last=100.0,  # same instant, said once — heuristic alone would refuse
        horizon=HORIZON_DURABLE,
    )
    assert rule.is_standing


def test_explicit_episodic_horizon_is_not_standing_even_if_repeated():
    rule = Rule(
        text="hold off on this for now",
        said=[Said(text="hold off", at=1.0), Said(text="hold off", at=5000.0)],
        first=1.0,
        last=5000.0,  # would pass the old heuristic on repetition alone
        horizon="episodic",
    )
    assert not rule.is_standing


def test_bears_on_is_populated_by_attachment_not_regex():
    # A rule whose text overlaps a definition's name in words, but whose
    # `names` (regex-extracted mention) is empty — proving bears_on comes
    # from a different mechanism than names.
    rule = Rule(text="resolve symbol references carefully", names=[])
    found = Found(rules=[rule])
    graph = Graph(
        nodes={"n1": Node(id="n1", name="_resolve_with", path="graph.py", line=10, kind=12)},
        edges=[],
    )
    attached = attach_rules(found, graph)
    assert attached.rules[0].bears_on == ["n1"]


def test_stable_id_agrees_for_the_same_rule_recovered_twice():
    a = Rule(text="one .env for the whole project, not one per service")
    b = Rule(text="one .env for the whole project, not one per service")
    assert a.stable_id == b.stable_id


def test_supersedes_removes_the_earlier_rule_from_standing():
    earlier = Rule(text="use SQLite for everything", horizon=HORIZON_STANDING)
    earlier.id = earlier.stable_id
    later = Rule(
        text="use Postgres instead of SQLite",
        horizon=HORIZON_STANDING,
        supersedes=earlier.stable_id,
    )
    later.id = later.stable_id
    found = Found(rules=[earlier, later])

    standing_texts = {r.text for r in found.standing}
    assert earlier.text not in standing_texts
    assert later.text in standing_texts
