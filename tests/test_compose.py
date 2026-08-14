"""A graph per path, and larger graphs made from smaller ones.

The invariant: editing one project invalidates one project. A workspace of
thirteen repositories built as a single tree took 73 seconds to rebuild
because one file in one of them changed, and paying that inside a prompt took
a hook past two minutes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.compose import composed, parts_of, rebase
from vesta.graph import Edge, Graph, Node, _node_id


def _project(root: Path, name: str, files: dict) -> Path:
    where = root / name
    where.mkdir(parents=True, exist_ok=True)
    (where / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    for path, body in files.items():
        target = where / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return where


def _graph(root: str, *names: str) -> Graph:
    """A small graph whose nodes are `a.py:0 <name>`, each referring to the next."""
    graph = Graph(root=root)
    made = []
    for n, name in enumerate(names):
        node = Node(
            id=_node_id("a.py", n, name), name=name, path="a.py", line=n, kind=12
        )
        graph.nodes[node.id] = node
        made.append(node)
    for one, two in zip(made, made[1:]):
        graph.edges.append(Edge(source=one.id, target=two.id, at="a.py"))
    return graph


# ── Which directories hold several projects ─────────────────────────────────


def test_a_directory_of_projects_is_split(tmp_path):
    _project(tmp_path, "alpha", {"a.py": "x = 1\n"})
    _project(tmp_path, "beta", {"a.py": "y = 1\n"})

    assert [p.name for p in parts_of(tmp_path)] == ["alpha", "beta"]


def test_a_project_is_never_split(tmp_path):
    """Somebody working in a repository that vendors another has one project,
    and the graph they want spans both."""
    root = _project(tmp_path, "solo", {"a.py": "x = 1\n"})
    _project(root, "inner", {"b.py": "y = 1\n"})

    assert parts_of(root) == []


def test_hidden_and_dependency_directories_are_not_projects(tmp_path):
    _project(tmp_path, "real", {"a.py": "x = 1\n"})
    _project(tmp_path, "node_modules", {"a.py": "x = 1\n"})
    _project(tmp_path, ".cache", {"a.py": "x = 1\n"})

    assert [p.name for p in parts_of(tmp_path)] == ["real"]


def test_looking_is_shallow(tmp_path):
    """Looking deeper would find every package inside every project and call
    each one a project, which is how a sensible idea becomes thousands of
    graphs."""
    deep = tmp_path / "one" / "two" / "three" / "four"
    deep.mkdir(parents=True)
    _project(deep, "buried", {"a.py": "x = 1\n"})

    assert parts_of(tmp_path) == []


# ── Rebasing ────────────────────────────────────────────────────────────────


def test_rebasing_moves_paths_under_the_shared_root(tmp_path):
    graph = _graph(str(tmp_path / "alpha"), "one", "two")
    moved = rebase(graph, tmp_path / "alpha", tmp_path)

    assert {n.path for n in moved.nodes.values()} == {"alpha/a.py"}


def test_rebasing_re_derives_every_id(tmp_path):
    """Ids are `sha256(path, line, name)`, so a node has a different id in its
    own graph than in a composed one. Getting this wrong would silently break
    every reference in the result."""
    graph = _graph(str(tmp_path / "alpha"), "one", "two")
    moved = rebase(graph, tmp_path / "alpha", tmp_path)

    for node in moved.nodes.values():
        assert node.id == _node_id(node.path, node.line, node.name)


def test_rebasing_rewrites_edges_to_match(tmp_path):
    graph = _graph(str(tmp_path / "alpha"), "one", "two", "three")
    moved = rebase(graph, tmp_path / "alpha", tmp_path)

    assert len(moved.edges) == len(graph.edges)
    for edge in moved.edges:
        assert edge.source in moved.nodes
        assert edge.target in moved.nodes


# ── Composing ───────────────────────────────────────────────────────────────


def test_composing_joins_disjoint_projects(tmp_path):
    parts = [tmp_path / "alpha", tmp_path / "beta"]
    of = {
        str(tmp_path / "alpha"): _graph(str(tmp_path / "alpha"), "one", "two"),
        str(tmp_path / "beta"): _graph(str(tmp_path / "beta"), "three"),
    }
    whole = composed(tmp_path, parts, of)

    assert len(whole.nodes) == 3
    assert {n.path for n in whole.nodes.values()} == {"alpha/a.py", "beta/a.py"}


def test_a_composed_graph_has_no_dangling_edges(tmp_path):
    parts = [tmp_path / "alpha", tmp_path / "beta"]
    of = {
        str(tmp_path / "alpha"): _graph(str(tmp_path / "alpha"), "one", "two"),
        str(tmp_path / "beta"): _graph(str(tmp_path / "beta"), "three", "four"),
    }
    whole = composed(tmp_path, parts, of)

    for edge in whole.edges:
        assert edge.source in whole.nodes
        assert edge.target in whole.nodes


def test_two_projects_with_the_same_layout_do_not_collide(tmp_path):
    """Both have `a.py:0 one`, which is the same id in their own graphs. If
    rebasing did not re-derive, one would overwrite the other."""
    parts = [tmp_path / "alpha", tmp_path / "beta"]
    of = {
        str(tmp_path / "alpha"): _graph(str(tmp_path / "alpha"), "one"),
        str(tmp_path / "beta"): _graph(str(tmp_path / "beta"), "one"),
    }
    whole = composed(tmp_path, parts, of)

    assert len(whole.nodes) == 2


def test_a_project_with_no_graph_yet_is_reported_not_omitted(tmp_path):
    """A composed graph that quietly covers half a workspace is worse than one
    that says which half."""
    parts = [tmp_path / "alpha", tmp_path / "beta"]
    of = {str(tmp_path / "alpha"): _graph(str(tmp_path / "alpha"), "one")}
    whole = composed(tmp_path, parts, of)

    assert any("not built yet" in h.why for h in whole.holes)


def test_references_between_projects_are_declared_missing(tmp_path):
    """If one project imports from another, that edge is in neither graph,
    because neither resolver was shown the other's files."""
    parts = [tmp_path / "alpha", tmp_path / "beta"]
    of = {
        str(tmp_path / "alpha"): _graph(str(tmp_path / "alpha"), "one"),
        str(tmp_path / "beta"): _graph(str(tmp_path / "beta"), "two"),
    }
    whole = composed(tmp_path, parts, of)

    assert any("between the 2 projects" in h.what for h in whole.holes)


# ── The point of all of it ──────────────────────────────────────────────────


def test_editing_one_project_leaves_the_others_alone(tmp_path, monkeypatch):
    """The invariant. Built as one tree, a workspace of thirteen repositories
    rebuilt all of them because one file changed."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    from vesta.held import _HELD, _SHAPES, _shape, graph_for

    alpha = _project(tmp_path / "space", "alpha", {"a.py": "def one(): pass\n"})
    beta = _project(tmp_path / "space", "beta", {"b.py": "def two(): pass\n"})

    graph_for(tmp_path / "space")
    _SHAPES.clear()
    before = _shape(beta)

    (alpha / "a.py").write_text("def one(): return 1\n", encoding="utf-8")
    _HELD.clear()
    _SHAPES.clear()

    # beta's fingerprint is untouched, so beta's graph is not rebuilt.
    assert _shape(beta) == before

    whole = graph_for(tmp_path / "space")
    assert any(n.path.startswith("alpha/") for n in whole.nodes.values())
    assert any(n.path.startswith("beta/") for n in whole.nodes.values())
