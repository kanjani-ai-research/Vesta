"""Whether a recorded claim still speaks for the code.

Two accounts of a codebase and the truth between them: a graph that cannot see
`getattr(obj, "name")`, and a note that cannot know whether the code has moved.
A live agent verified everything it was told, correctly, because nothing
established authority — and verification costs more than the note saves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.authority import CURRENT, MOVED, UNKNOWN, bounded_region, check, settle
from vesta.graph import Graph, Node


def a_repo(tmp_path: Path) -> tuple[Graph, Node]:
    (tmp_path / "m.py").write_text(
        "\n".join(
            ["def first():", "    return 1", "", ""]
            + ["def judged():"]
            + [f"    x = {i}" for i in range(10)]
            + ["", "", "def last():", "    return 2"]
        ),
        encoding="utf-8",
    )
    node = Node(id="n1", name="judged", path="m.py", line=4, kind=12)
    others = [
        Node(id="n0", name="first", path="m.py", line=0, kind=12),
        Node(id="n2", name="last", path="m.py", line=17, kind=12),
    ]
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in [node, *others]})
    return graph, node


def test_an_unchanged_region_keeps_its_claim(tmp_path: Path):
    graph, node = a_repo(tmp_path)
    region, was = bounded_region(graph, node, tmp_path)

    assert check(graph, node.id, tmp_path, region, was).state == CURRENT


def test_an_edit_inside_the_region_supersedes_the_claim(tmp_path: Path):
    graph, node = a_repo(tmp_path)
    region, was = bounded_region(graph, node, tmp_path)

    path = tmp_path / "m.py"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(6, "    changed = True")
    path.write_text("\n".join(lines), encoding="utf-8")

    assert check(graph, node.id, tmp_path, region, was).state == MOVED


def test_an_edit_elsewhere_in_the_file_does_not(tmp_path: Path):
    """File-level staleness is too coarse: an edit 400 lines away says nothing
    about a claim concerning this function."""
    graph, node = a_repo(tmp_path)
    region, was = bounded_region(graph, node, tmp_path)

    path = tmp_path / "m.py"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = "    return 99"  # inside `first`, before the region
    path.write_text("\n".join(lines), encoding="utf-8")

    assert check(graph, node.id, tmp_path, region, was).state == CURRENT


def test_a_deleted_definition_supersedes_its_claims(tmp_path: Path):
    graph, node = a_repo(tmp_path)
    region, was = bounded_region(graph, node, tmp_path)
    del graph.nodes[node.id]

    assert check(graph, node.id, tmp_path, region, was).state == MOVED


def test_a_claim_with_no_recorded_region_is_unverifiable(tmp_path: Path):
    """Not current and not superseded: nothing was written down, so nothing can
    be checked, and saying either would be a claim about nothing."""
    graph, node = a_repo(tmp_path)

    assert check(graph, node.id, tmp_path, "", "").state == UNKNOWN


def test_a_region_stops_where_the_next_definition_begins(tmp_path: Path):
    """A hash over the whole file calls every claim stale on any edit; a hash
    over one line calls a rewritten body unchanged."""
    graph, node = a_repo(tmp_path)
    region, _ = bounded_region(graph, node, tmp_path)

    assert region.startswith("m.py:5-")
    assert region.endswith("-17")


def test_settling_many_notes_agrees_with_checking_one(tmp_path: Path):
    graph, node = a_repo(tmp_path)
    region, was = bounded_region(graph, node, tmp_path)

    class Held:
        def __init__(self):
            self.node, self.region, self.region_hash = node.id, region, was

    held = Held()
    assert settle(graph, [held], tmp_path)[id(held)].state == CURRENT
