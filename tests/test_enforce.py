"""Checking a repository against what its user decided.

A rule nobody checks is a note. These pin the executed half — derivation is
model work and is not tested here; execution must be reproducible, because a
finding a reader cannot follow is the tool having an opinion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.enforce import (
    CALLS_INTO,
    FILES_LACKING,
    COUNT_AT_LEAST,
    COUNT_AT_MOST,
    FILES_MATCHING,
    NAMES_MATCHING,
    Check,
    Finding,
    run_check,
)
from vesta.graph import Edge, Graph, Node


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Graph, Path]:
    (tmp_path / "a.py").write_text("def loader():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def other():\n    pass\n", encoding="utf-8")
    nodes = [
        Node(id="n1", name="load_config", path="a.py", line=0, kind=12),
        Node(id="n2", name="other", path="b.py", line=0, kind=12),
    ]
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in nodes},
                  edges=[Edge(source="n2", target="n1")])
    return graph, tmp_path


def test_a_rule_that_holds_reports_nothing(repo):
    graph, root = repo
    check = Check(look_for=FILES_MATCHING, pattern=r"\.env$",
                  holds_when=COUNT_AT_MOST, how_many=1, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites and not why


def test_a_rule_that_is_broken_names_the_sites(repo):
    graph, root = repo
    (root / ".env").write_text("X=1\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / ".env").write_text("Y=2\n", encoding="utf-8")

    check = Check(look_for=FILES_MATCHING, pattern=r"\.env$",
                  holds_when=COUNT_AT_MOST, how_many=1, tests_the_rule=True)
    sites, _ = run_check(check, graph, root)

    assert len(sites) == 2
    assert {s.path for s in sites} == {".env", "sub/.env"}


def test_a_check_that_cannot_test_the_rule_decides_nothing(repo):
    """A live derivation supplied a pattern matching every source file while
    its own reason said the rule could not be tested. Executing it accused the
    user of thirty-five violations, and a user accused thirty-five times over
    stops believing any of it."""
    graph, root = repo
    check = Check(look_for=FILES_MATCHING, pattern=r".*\.py$",
                  holds_when=COUNT_AT_MOST, how_many=0,
                  why="requires reading comment text", tests_the_rule=False)

    sites, why = run_check(check, graph, root)

    assert not sites
    assert "comment text" in why


def test_a_malformed_pattern_decides_nothing(repo):
    graph, root = repo
    check = Check(look_for=FILES_MATCHING, pattern="[unclosed",
                  holds_when=COUNT_AT_MOST, how_many=0, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites
    assert "malformed" in why


def test_finding_none_of_a_presence_decides_nothing(repo):
    """Absence of the subject is not evidence about the rule.

    A rule about langextract, checked in a repository containing no langextract
    anywhere, was reported broken with a site pointing at the repository root.
    Nothing was found because the subject is not here, which settles neither
    way.
    """
    graph, root = repo
    check = Check(look_for=NAMES_MATCHING, pattern=r"^test_",
                  holds_when=COUNT_AT_LEAST, how_many=1, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites
    assert "neither honoured nor broken" in why


def test_finding_none_of_an_absence_honours_the_rule(repo):
    """`files_lacking` enumerates the violations themselves, so finding none
    of them is the rule holding — "every file must have a docstring" was called
    undecidable in a repository where every file has one."""
    graph, root = repo
    check = Check(look_for=FILES_LACKING, pattern=r"def ", within=r"\.py$",
                  holds_when=COUNT_AT_LEAST, how_many=1, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites and not why


def test_at_least_is_broken_by_too_few(repo):
    """Some, but fewer than required, is a genuine violation."""
    graph, root = repo
    check = Check(look_for=NAMES_MATCHING, pattern=r"load|other",
                  holds_when=COUNT_AT_LEAST, how_many=5, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert sites and not why


def test_definitions_reaching_a_name_are_found(repo):
    graph, root = repo
    check = Check(look_for=CALLS_INTO, pattern=r"load_config",
                  holds_when=COUNT_AT_MOST, how_many=0, tests_the_rule=True)

    sites, _ = run_check(check, graph, root)
    assert [s.what for s in sites] == ["other"]


def test_an_unknown_kind_of_check_decides_nothing(repo):
    graph, root = repo
    check = Check(look_for="telepathy", pattern=".", tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites and "unknown" in why


def test_a_finding_carries_the_words_it_came_from():
    """An agent told "this violates a constraint" will ask whose constraint."""
    finding = Finding(rule="one .env for the family", said="there should be one .env for v3")

    assert finding.holds
    assert "one .env for v3" in finding.said


def test_pasted_output_is_not_a_rule():
    """A user pasting an error is showing something, not deciding something —
    and a rule recovered from Vesta's own output is Vesta recording its own
    words as the user's."""
    from vesta.rules import constrains

    assert not constrains(
        "Vesta is not installed in a way this session can reach.\n"
        "  pip install vesta   (or set VESTA_PYTHON to an interpreter)"
    )
    assert not constrains(
        "❯ /vesta:help\n  ⎿ UserPromptSubmit hook error\n"
        "  ⎿ Failed with non-blocking status: python: command not found\n  ✘ vesta"
    )


def test_a_sentence_quoting_output_is_still_a_rule():
    """The quote is context that makes the instruction legible. Rejecting on
    presence rather than proportion would discard the real rule with it."""
    from vesta.rules import constrains

    assert constrains(
        'the namespace "❯ plugin:vesta:vesta · ✔ connected" should be '
        "causum:vesta, not vesta:vesta"
    )


def test_vestas_own_output_is_not_a_users_rule():
    """A slash command puts its output and its instructions into the prompt,
    the transcript records that, and the next harvest reads it as something the
    user decided. Those sentences are imperative, so they pass every other test
    for a constraint — and enforcing them would hold agents to Vesta's own
    help text."""
    from vesta.rules import constrains

    assert not constrains(
        "Vesta is not installed in a way this session can reach.\n"
        "  pip install vesta   (or set VESTA_PYTHON to an interpreter that has it)\n\n"
        "Show the guide above to the user verbatim. Do not summarise it or add to it."
    )
    assert not constrains(
        "Show these definitions verbatim. If nothing was found, say so plainly."
    )


def test_a_rule_stated_as_a_definition_is_still_a_rule():
    """People say what something *is* at least as often as what to do about it.

    Four rules about which mode may do what were all stated declaratively —
    "non-full auto is a companion, no consent" — none was captured, and the
    constraint they described was violated within the hour with nothing to
    notice. Matching only imperatives threw away every rule stated this way.
    """
    from vesta.rules import constrains

    assert constrains("non-full auto is a companion, no consent")
    assert constrains("the consent is only for full auto mode")
    assert constrains("the stuck signal does not apply to companion mode")
    assert constrains(
        "none of the decision management from the autonomous loop applies to "
        "the companion mode"
    )
    assert constrains("the graph is a tree, no cycles")


def test_a_definition_about_nothing_is_still_not_a_rule():
    from vesta.rules import constrains

    assert not constrains("this is a nice day, no rain at all today thankfully")
    assert not constrains("run the tests again")
    assert not constrains("what does the companion mode do")
