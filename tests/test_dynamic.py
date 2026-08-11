"""References a language server cannot resolve.

Found by a live agent, not by a test: the graph reported two consumers of
`why_not` where a harvested note claimed five, and the agent grepped rather
than trusting either. The note was right. A `getattr` with a string literal
reaches a definition and no server sees it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.dynamic import missed_by, scan
from vesta.graph import Graph, Node


def a_repo(tmp_path: Path) -> Graph:
    (tmp_path / "uses.py").write_text(
        "\n".join([
            "def caller(search):",
            '    return getattr(search, "why_not", "")',
            "",
            "",
            "def plain(search):",
            "    return search.described",
        ]),
        encoding="utf-8",
    )
    nodes = [
        Node(id="n1", name="why_not", path="api.py", line=10, kind=12, container="Search"),
        Node(id="n2", name="described", path="api.py", line=20, kind=12),
        Node(id="n3", name="caller", path="uses.py", line=0, kind=12),
    ]
    return Graph(root=str(tmp_path), nodes={n.id: n for n in nodes})


def test_a_getattr_by_string_is_found(tmp_path: Path):
    graph = a_repo(tmp_path)
    found = scan(tmp_path, graph)

    assert [u.name for u in found.for_name("why_not")]
    assert found.for_name("why_not")[0].line == 2


def test_a_resolvable_reference_is_not_reported(tmp_path: Path):
    """Only what a server cannot see. Reporting ordinary attribute access
    would bury the real gaps in noise."""
    graph = a_repo(tmp_path)

    assert not scan(tmp_path, graph).for_name("described")


def test_candidates_are_offered_not_chosen(tmp_path: Path):
    """A textual match cannot say which definition of a shared name is
    reached. Manufacturing an edge from a guess would put unverified structure
    into a graph whose whole value is that its edges are verified."""
    graph = a_repo(tmp_path)
    graph.nodes["n4"] = Node(id="n4", name="why_not", path="other.py", line=5, kind=12,
                             container="Local")

    found = scan(tmp_path, graph).for_name("why_not")[0]

    assert len(found.candidates) == 2
    assert "one of" in found.describe()


def test_prose_about_getattr_is_not_a_reference(tmp_path: Path):
    """This module's own docstring matched itself: the mildest possible
    version of a scanner believing documentation."""
    (tmp_path / "doc.py").write_text(
        '"""\nA getattr(obj, "why_not") in prose is not a call.\n"""\n',
        encoding="utf-8",
    )
    graph = Graph(root=str(tmp_path), nodes={})

    assert not [u for u in scan(tmp_path, graph).found if u.path == "doc.py"]


def test_a_name_no_definition_carries_is_still_reported(tmp_path: Path):
    """Unresolvable and unknown is a different fact from unresolvable and
    ambiguous, and a reader should see which."""
    (tmp_path / "x.py").write_text('getattr(o, "nowhere")\n', encoding="utf-8")
    found = scan(tmp_path, Graph(root=str(tmp_path), nodes={}))

    assert found.for_name("nowhere")
    assert "no definition" in found.for_name("nowhere")[0].describe()


def test_a_propagation_learns_what_it_missed(tmp_path: Path):
    """A caller told "these four tests" without being told "and three call
    sites reach this by name" has a claim the evidence does not support."""
    graph = a_repo(tmp_path)
    found = scan(tmp_path, graph)

    assert missed_by(found, graph, ["n1"])       # why_not is reached dynamically
    assert not missed_by(found, graph, ["n2"])   # described is not
