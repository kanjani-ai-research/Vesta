"""Crossing between code and concept.

The join is the point of the whole project: a reference graph knows structure
and an ontology knows vocabulary, and neither can answer "what is this code
about" or "where does this repository do that".

Every threshold here was set by a failure, and the two failures pull in
opposite directions — attach too readily and a covering-array ontology labels a
static-analysis codebase at full confidence; attach too reluctantly and
"resolve symbol references" matches nothing in a file called `resolve.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vesta.graph import Edge, Graph, Node
from vesta.traverse import Term, about, attach, neighbours, read_ontology, where


def node(name: str, path: str = "x.py", line: int = 0, container: str = "") -> Node:
    return Node(id=f"{path}:{line}:{name}", name=name, path=path, line=line, kind=12,
                container=container)


@pytest.fixture
def code() -> Graph:
    nodes = [
        node("_resolve_with", "graph.py", 10),
        node("references", "resolve.py", 20, container="Session"),
        node("Coverage", "resolve.py", 30),
        node("from_definitions", "propagate.py", 40),
        node("consult", "consult.py", 50),
        node("save", "store.py", 60),
    ]
    return Graph(root="/x", nodes={n.id: n for n in nodes})


def terms(*labels: str):
    return [Term(id=f"t:{i}", kind="activity", label=l) for i, l in enumerate(labels)]


# ── Attaching ────────────────────────────────────────────────────────────


def test_a_long_term_still_matches_a_short_identifier(code: Graph):
    """Scoring by the term's vocabulary alone made a five-word activity
    unmatchable by a two-word name: "resolve symbol references across a
    codebase" attached to nothing in a repository built around resolving."""
    mapped = attach(code, terms("resolve symbol references across a codebase"))

    matched = {code.nodes[a.node].name for a in mapped.attachments}
    assert "_resolve_with" in matched


def test_a_common_word_alone_does_not_attach(code: Graph):
    """`Coverage` — which files a language server resolved — attached to
    "create extended covering arrays" at 1.00 before this."""
    for _ in range(6):  # make "coverage" common in this repository
        extra = node("coverage_report", "a.py", 70)
        code.nodes[extra.id] = extra
        code.nodes[extra.id] = extra
    code.nodes.update({f"c{i}": node(f"coverage_{i}", "b.py", i) for i in range(6)})

    mapped = attach(code, terms("create extended covering arrays for coverage"))

    assert not [a for a in mapped.attachments if code.nodes[a.node].name == "Coverage"]


def test_a_rare_word_alone_may_attach(code: Graph):
    """Requiring two shared words killed the true matches. What separates a
    coincidence from a signal is whether the word narrows this codebase."""
    mapped = attach(code, terms("consult a corpus for cited passages"))

    assert any(code.nodes[a.node].name == "consult" for a in mapped.attachments)


def test_an_unrelated_ontology_attaches_to_almost_nothing(code: Graph):
    """The failure this is shaped against: a domain model labelling code
    confidently and wrongly."""
    mapped = attach(code, terms(
        "measure impact of a user on twitter",
        "price a used car by mileage and condition",
        "schedule freight across a rail network",
    ))

    assert not mapped.attachments
    assert len(mapped.unattached) == 3


def test_terms_that_match_nothing_are_reported(code: Graph):
    """The more interesting half: a term with no code is either unbuilt or
    called by another name."""
    mapped = attach(code, terms("consult a corpus", "orchestrate a kubernetes cluster"))

    assert "orchestrate a kubernetes cluster" in mapped.unattached


def test_an_attachment_carries_its_strength(code: Graph):
    mapped = attach(code, terms("resolve symbol references across a codebase"))

    assert all(0 < a.strength <= 1 for a in mapped.attachments)


# ── Crossing ─────────────────────────────────────────────────────────────


def test_concept_reaches_code(code: Graph):
    """Ask in the vocabulary of the domain, be answered in the vocabulary of
    the repository."""
    mapped = attach(code, terms("resolve symbol references across a codebase"))
    found = where(code, mapped, "resolve symbols")

    assert found
    assert code.nodes[found[0].node].name == "_resolve_with"


def test_code_reaches_concept(code: Graph):
    mapped = attach(code, terms("propagate changes to affected definitions"))
    target = next(n for n in code.nodes.values() if n.name == "from_definitions")

    said = about(code, mapped, target.id)
    assert said and "propagate" in said[0].label


def test_kin_are_found_without_a_code_edge(code: Graph):
    """The traversal a reference graph cannot do: two definitions doing the
    same kind of work, with nothing calling between them."""
    mapped = attach(code, terms("resolve symbol references across a codebase"))
    target = next(n for n in code.nodes.values() if n.name == "_resolve_with")

    kin = neighbours(code, mapped, target.id)
    assert any(k.name == "references" for k in kin)
    # Nothing in the code connects them.
    assert not code.depends_on(target.id)


def test_a_definition_about_nothing_has_no_kin(code: Graph):
    mapped = attach(code, terms("resolve symbol references across a codebase"))
    unrelated = next(n for n in code.nodes.values() if n.name == "save")

    assert neighbours(code, mapped, unrelated.id) == []


# ── Reading an ontology ──────────────────────────────────────────────────


def test_an_ontology_is_read_as_terms(tmp_path: Path):
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"graph": {"nodes": [
        {"id": "a:1", "kind": "activity", "label": "resolve symbols"},
        {"id": "d:1", "kind": "domain", "label": "static analysis"},
        {"id": "x:1", "kind": "activity"},
    ]}}), encoding="utf-8")

    got = read_ontology(path)

    assert len(got) == 2  # the one with no label is not a term
    assert {t.kind for t in got} == {"activity", "domain"}


def test_asking_in_words_the_label_does_not_use(tmp_path):
    """The crossing must survive a synonym.

    An ontology says a definition *scores how closely two texts overlap*; the
    definition is called `closeness` in `search.py`. "fuzzy search" shares no
    word with the label, so matching labels alone answers nothing — which is
    the case cross-project reference is made of.
    """
    from vesta.graph import Graph, Node
    from vesta.traverse import Attachment, Map, where

    graph = Graph(root=str(tmp_path))
    graph.nodes["n1"] = Node(
        id="n1",
        name="closeness",
        qualified="closeness",
        kind=12,  # LSP SymbolKind: Function
        path="search.py",
        line=10,
    )
    mapped = Map(
        ontology="test",
        attachments=[
            Attachment(
                node="n1",
                term="t1",
                label="score how closely two texts overlap",
                kind="activity",
                strength=1.0,
                how="read",
            )
        ],
    )

    assert [a.node for a in where(graph, mapped, "fuzzy search")] == ["n1"]
    # And the label still answers on its own terms.
    assert [a.node for a in where(graph, mapped, "texts that overlap")] == ["n1"]
    # Something genuinely absent stays absent — the widening must not invent.
    assert where(graph, mapped, "database migration rollback") == []
