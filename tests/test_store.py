"""A graph as rows, so a question reads only what it asks about.

A graph kept as one document must be parsed whole before anything is answered:
free at four hundred definitions, ruinous at forty thousand. Measured on a real
graph scaled to twenty-nine thousand nodes, the same question took 555ms
against the document and 2.9ms against the store.

One store per repository, for the same reason there is one knowledge base per
repository: a shared file makes one project's rebuild block another's read, and
makes reaching across projects accidental rather than asked for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.graph import Edge, Graph, Hole, Node
from vesta.store import Held, shape_of, write


@pytest.fixture
def stored(tmp_path: Path, monkeypatch) -> Path:
    import vesta.store as store

    where = tmp_path / "kept"
    where.mkdir()
    monkeypatch.setattr(store, "_at", lambda repo: where / f"{Path(repo).name}.db")

    nodes = [
        Node(id="n1", name="advance", path="pipe.py", line=6, kind=12),
        Node(id="n2", name="rewind", path="pipe.py", line=20, kind=12),
        Node(id="n3", name="note", path="audit.py", line=1, kind=12, container="Log"),
    ]
    graph = Graph(
        root=str(tmp_path / "proj"),
        nodes={n.id: n for n in nodes},
        edges=[Edge(source="n2", target="n1"), Edge(source="n3", target="n1")],
        holes=[Hole(path="x.rs", what=".rs", why="no server")],
    )
    write(graph, tmp_path / "proj", shape="abc123")
    return tmp_path / "proj"


def test_a_definition_is_found_by_name(stored: Path):
    with Held(stored) as held:
        assert [n.name for n in held.named("advance")] == ["advance"]


def test_a_definition_is_found_by_qualified_name(stored: Path):
    with Held(stored) as held:
        assert [n.name for n in held.named("Log.note")] == ["note"]


def test_what_refers_to_a_definition(stored: Path):
    with Held(stored) as held:
        assert set(held.referenced_by("n1")) == {"n2", "n3"}


def test_what_a_definition_refers_to(stored: Path):
    """Both directions are indexed, because both are asked. Without the second
    index a propagation walk degrades to a scan per hop."""
    with Held(stored) as held:
        assert held.depends_on("n2") == ["n1"]


def test_the_definition_containing_a_line(stored: Path):
    """A change is reported by file and line; a graph is keyed by definition."""
    with Held(stored) as held:
        assert held.at("pipe.py", 25).name == "rewind"
        assert held.at("pipe.py", 10).name == "advance"


def test_holes_are_kept_with_the_graph(stored: Path):
    """A propagation claim is only as complete as the resolution behind it."""
    with Held(stored) as held:
        assert held.counts() == (3, 2, 1)


def test_the_busiest_definitions_without_loading_the_rest(stored: Path):
    with Held(stored) as held:
        top, callers = held.busiest(1)[0]
        assert top.name == "advance" and callers == 2


def test_the_whole_graph_is_recoverable(stored: Path):
    """A survey reads everything and there is no cheaper way; what matters is
    that the sparse questions no longer pay for it."""
    with Held(stored) as held:
        graph = held.everything()

    assert len(graph.nodes) == 3
    assert len(graph.edges) == 2
    assert graph.holes[0].path == "x.rs"


def test_a_store_carries_the_shape_it_was_written_for(stored: Path):
    """Stale in exactly the way the document was, and rebuilt rather than
    migrated."""
    assert shape_of(stored) == "abc123"


def test_rewriting_replaces_rather_than_accumulates(stored: Path, tmp_path: Path):
    """Reconciling a partial rebuild against old rows is how a store comes to
    hold edges for definitions that no longer exist."""
    smaller = Graph(
        root=str(stored),
        nodes={"n9": Node(id="n9", name="only", path="a.py", line=0, kind=12)},
    )
    write(smaller, stored, shape="def456")

    with Held(stored) as held:
        assert held.counts() == (1, 0, 0)
        assert not held.named("advance")


def test_a_missing_store_says_so_rather_than_raising(tmp_path: Path, monkeypatch):
    import vesta.store as store

    monkeypatch.setattr(store, "_at", lambda repo: tmp_path / "absent.db")
    assert not Held(tmp_path).exists
    assert shape_of(tmp_path) == ""
