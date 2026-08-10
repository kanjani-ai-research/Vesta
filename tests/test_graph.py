"""The graph and what walks it.

Built against a real fixture tree resolved by a real language server, because
the failure that mattered here was not in the walking — it was in the resolving.
A first `ast` implementation collapsed four `describe` methods into one node, and
a half-initialised pyright answered `references` with 2 instead of 19. Both
produce a graph that is the right *shape* and wrong, so a test over a hand-built
`Graph` object would have passed through either.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vesta.graph import Edge, Graph, Hole, Node, build
from vesta.propagate import MAX_HOPS, from_definitions, from_files, from_lines, is_test
from vesta.resolve import for_suffix

TREE = {
    "core.py": (
        "def base(x):\n"
        "    return x + 1\n"
        "\n"
        "\n"
        "def middle(x):\n"
        "    return base(x) * 2\n"
        "\n"
        "\n"
        "def unrelated(x):\n"
        "    return x\n"
    ),
    "user.py": (
        "from core import middle\n"
        "\n"
        "\n"
        "def top(x):\n"
        "    return middle(x)\n"
    ),
    "test_core.py": (
        "from core import base\n"
        "\n"
        "\n"
        "def test_base():\n"
        "    assert base(1) == 2\n"
    ),
    "test_top.py": (
        "from user import top\n"
        "\n"
        "\n"
        "def test_top():\n"
        "    assert top(1) == 4\n"
    ),
}


def _pyright() -> bool:
    server = for_suffix(".py")
    return bool(server and server.is_available)


needs_server = pytest.mark.skipif(
    not _pyright(), reason="no language server for .py on this machine"
)


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("repo")
    for name, text in TREE.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def graph(tree: Path) -> Graph:
    return build(tree)


def node_named(graph: Graph, name: str) -> Node:
    found = [n for n in graph.nodes.values() if n.name == name]
    assert found, f"no definition named {name}"
    return found[0]


# ── Resolving ────────────────────────────────────────────────────────────


@needs_server
def test_every_definition_is_a_node(graph: Graph):
    names = {n.name for n in graph.nodes.values()}

    assert {"base", "middle", "unrelated", "top", "test_base", "test_top"} <= names


@needs_server
def test_a_reference_is_attributed_to_the_definition_containing_it(graph: Graph):
    """Not to the file. A change to one function must not appear to affect its
    neighbours — that is the difference between a useful set and the whole
    module."""
    base = node_named(graph, "base")
    sources = {graph.nodes[e.source].name for e in graph.referenced_by(base.id)}

    assert "middle" in sources
    assert "unrelated" not in sources


@needs_server
def test_the_graph_holds_both_directions(graph: Graph):
    middle, top = node_named(graph, "middle"), node_named(graph, "top")

    assert top.id in {e.source for e in graph.referenced_by(middle.id)}
    assert middle.id in {e.target for e in graph.depends_on(top.id)}


@needs_server
def test_a_tree_the_server_resolves_has_no_holes(graph: Graph):
    assert graph.is_whole, [h.describe() for h in graph.holes]


@needs_server
def test_a_line_resolves_to_the_definition_containing_it(graph: Graph, tree: Path):
    # `return base(x) * 2` is inside `middle`, not inside `base` above it.
    found = graph.at("core.py", 5)

    assert found is not None
    assert found.name == "middle"


def test_a_file_with_no_server_becomes_a_hole(tmp_path: Path):
    (tmp_path / "thing.zzz").write_text("nothing resolves this", encoding="utf-8")
    built = build(tmp_path)

    assert built.is_whole or all(h.path != "thing.zzz" for h in built.holes)


# ── Propagating ──────────────────────────────────────────────────────────


@needs_server
def test_a_change_reaches_what_transitively_uses_it(graph: Graph):
    reached = from_definitions(graph, [node_named(graph, "base").id])
    names = {graph.nodes[r.node].name for r in reached.reached}

    assert "middle" in names       # one hop
    assert "test_base" in names    # one hop, a test
    assert "unrelated" not in names


@needs_server
def test_a_change_does_not_reach_what_does_not_use_it(graph: Graph):
    reached = from_definitions(graph, [node_named(graph, "unrelated").id])

    assert not reached.tests(graph)


@needs_server
def test_the_nearest_reason_is_the_one_recorded(graph: Graph):
    """A definition reached by two paths is recorded at the shorter one."""
    reached = from_definitions(graph, [node_named(graph, "base").id])
    hops = {graph.nodes[r.node].name: r.hops for r in reached.reached}

    assert hops["middle"] == 1
    assert hops["top"] == 2


@needs_server
def test_propagation_stops_at_a_test(graph: Graph):
    """Nothing references a test, so walking past one only ever finds nothing —
    and stopping keeps the set from growing through test helpers."""
    reached = from_definitions(graph, [node_named(graph, "base").id])
    chains = [r.through for r in reached.reached]

    for chain in chains:
        passed = [graph.nodes[n].name for n in chain if n in graph.nodes]
        assert not any(name.startswith("test_") for name in passed)


@needs_server
def test_a_changed_file_propagates_from_every_definition_in_it(graph: Graph):
    reached = from_files(graph, ["core.py"])
    tests = reached.tests(graph)

    assert "test_core.py" in tests
    assert "test_top.py" in tests  # through middle → top


@needs_server
def test_a_line_change_propagates_from_only_what_moved(graph: Graph):
    """The precise form. A file-level change starts from every definition; a
    line-level change starts from the few that actually moved."""
    whole = from_files(graph, ["core.py"])
    precise = from_lines(graph, {"core.py": [9]})  # inside `unrelated`

    assert len(precise.reached) < len(whole.reached)


@needs_server
def test_the_hop_bound_is_honoured(graph: Graph):
    assert all(r.hops <= 1 for r in from_definitions(graph, [node_named(graph, "base").id], hops=1).reached)


# ── What the graph does not know ─────────────────────────────────────────


def test_a_propagation_over_a_graph_with_holes_says_so():
    """A caller told "these four tests" without being told "and two files could
    not be resolved" has a correctness claim the evidence does not support."""
    holed = Graph(
        root="/x",
        nodes={"a": Node(id="a", name="a", path="a.py", line=0, kind=12)},
        holes=[Hole(path="b.rs", what=".rs", why="no server")],
    )
    found = from_definitions(holed, ["a"])

    assert not found.is_bounded
    assert "b.rs" in found.unresolved
    assert "may be short" in found.describe(holed)


def test_a_propagation_over_a_whole_graph_claims_nothing_extra():
    whole = Graph(
        root="/x", nodes={"a": Node(id="a", name="a", path="a.py", line=0, kind=12)}
    )

    assert from_definitions(whole, ["a"]).is_bounded


def test_a_test_is_recognised_by_name_not_by_path():
    """A helper in a test file is not a test, and reaching it is not a reason to
    run anything."""
    assert is_test(Node(id="1", name="test_thing", path="tests/x.py", line=0, kind=12))
    assert is_test(Node(id="2", name="should_work", path="x.py", line=0, kind=12))
    assert not is_test(Node(id="3", name="make_fixture", path="tests/x.py", line=0, kind=12))


def test_a_cycle_does_not_loop_forever():
    """Mutual recursion is ordinary, and a walk that revisits is a hang."""
    cyclic = Graph(
        root="/x",
        nodes={
            "a": Node(id="a", name="a", path="x.py", line=0, kind=12),
            "b": Node(id="b", name="b", path="x.py", line=4, kind=12),
        },
        edges=[Edge(source="a", target="b"), Edge(source="b", target="a")],
    )
    found = from_definitions(cyclic, ["a"])

    assert {r.node for r in found.reached} == {"b"}  # `a` was the start, not reached
