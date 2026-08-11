"""Scoring the checker against verdicts fixed before it was built.

The standard is `tests/fixtures/rule_verdicts.json`, written and committed
before any remedy existed, so the checker cannot be tuned to flatter itself.
Each case carries a verdict a careful reader would reach about this repository
and the reason, justified independently.

This needs a model and network, so it is skipped by default. Run it with
VESTA_SCORE=1 to hold the checker to the standard.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("VESTA_SCORE"),
    reason="set VESTA_SCORE=1 to score against the fixed standard (needs a model)",
)


def test_the_checker_meets_the_standard():
    from vesta.acquire import _load_env
    from vesta.enforce import derive_check, run_check
    from vesta.held import graph_for
    from vesta.rules import Rule

    _load_env("/Users/rf/Developer/causum/v3", override=True)
    root = Path(__file__).resolve().parent.parent
    graph = graph_for(root)
    cases = json.loads(
        (root / "tests" / "fixtures" / "rule_verdicts.json").read_text()
    )["cases"]

    wrong = []
    for case in cases:
        rule = Rule(text=case["rule"], stated=case["rule"])
        check = derive_check(rule, graph=graph)
        if check is None:
            got = "undecided"
        else:
            sites, why = run_check(check, graph, root)
            got = "undecided" if why else ("broken" if sites else "held")
        if got != case["expect"]:
            wrong.append(f"{case['rule'][:50]}: want {case['expect']}, got {got}")

    # Seven of nine at the time this was written. The three that must stay
    # undecided are the ones that matter: claiming to check a value or a
    # runtime behaviour is the failure the whole design guards against.
    assert len(cases) - len(wrong) >= 7, "\n".join(wrong)


def test_no_case_that_must_stay_undecided_is_ever_decided():
    """The one-way property. A rule about values or runtime behaviour must
    never produce a verdict, whatever else changes."""
    from vesta.acquire import _load_env
    from vesta.enforce import derive_check, run_check
    from vesta.held import graph_for
    from vesta.rules import Rule

    _load_env("/Users/rf/Developer/causum/v3", override=True)
    root = Path(__file__).resolve().parent.parent
    graph = graph_for(root)
    cases = json.loads(
        (root / "tests" / "fixtures" / "rule_verdicts.json").read_text()
    )["cases"]

    for case in [c for c in cases if c["expect"] == "undecided"]:
        rule = Rule(text=case["rule"], stated=case["rule"])
        check = derive_check(rule, graph=graph)
        if check is None:
            continue
        sites, why = run_check(check, graph, root)
        assert why, f"decided what it should not: {case['rule'][:60]}"
