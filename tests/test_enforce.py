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
