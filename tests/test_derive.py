"""The seam between an agent's judgement and Vesta's records.

An agent decides and produces prose; Vesta needs structure. Everything here
parses, validates against the graph, and writes — it judges nothing, because
judging is what moved to the host's inference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.derive import read_attachments, read_terms
from vesta.graph import Graph, Node


def a_graph(tmp_path: Path) -> Graph:
    nodes = [
        Node(id="n1", name="advance", path="pipe.py", line=6, kind=12),
        Node(id="n2", name="note", path="audit.py", line=1, kind=12),
    ]
    return Graph(root=str(tmp_path), nodes={n.id: n for n in nodes})


def test_terms_are_parsed_from_prose():
    """An agent asked for a list will preface it, number it, or bullet it.
    Refusing the batch over a stray line would make the seam brittle exactly
    where it must not be."""
    got = read_terms(
        "Here is what I found:\n\n"
        "domain: record pipelines\n"
        "- activity: move a record to the next stage\n"
        "  role: pipeline stage\n"
        "this line is not a term\n"
    )

    assert [t.kind for t in got] == ["domain", "activity", "role"]
    assert got[1].label == "move a record to the next stage"


def test_a_term_too_short_to_mean_anything_is_dropped():
    assert not read_terms("domain: ab\n")


def test_an_attachment_is_placed_against_the_graph(tmp_path: Path):
    graph = a_graph(tmp_path)
    placed, refused = read_attachments(
        "pipe.py:7 advance | move a record to the next stage\n", graph
    )

    assert placed == [("n1", "move a record to the next stage")]
    assert not refused


def test_an_attachment_pointing_nowhere_is_refused(tmp_path: Path):
    """A map that points nowhere is worse than a smaller one."""
    graph = a_graph(tmp_path)
    placed, refused = read_attachments("pipe.py:900 ghost | something\n", graph)

    assert not placed
    assert "no definition there" in refused[0]


def test_a_line_off_by_one_still_places(tmp_path: Path):
    """An agent reading a file may be a line out either way."""
    graph = a_graph(tmp_path)
    placed, _ = read_attachments("pipe.py:8 advance | moving records\n", graph)

    assert placed and placed[0][0] == "n1"


def test_a_bare_filename_places_against_a_full_path(tmp_path: Path):
    nodes = {"n1": Node(id="n1", name="go", path="src/deep/mod.py", line=0, kind=12)}
    graph = Graph(root=str(tmp_path), nodes=nodes)

    placed, _ = read_attachments("deep/mod.py:1 go | doing the thing\n", graph)
    assert placed


def test_an_unbuilt_graph_says_so_rather_than_answering_emptily(tmp_path: Path, monkeypatch):
    """An empty list reads as "this repository has none" — a false answer that
    sends an agent away. A silence and an answer must not look alike."""
    import vesta.derive as derive
    import vesta.ready as ready

    monkeypatch.setattr(ready, "STATE", tmp_path / "prepared")
    monkeypatch.setattr(ready, "prepare", lambda root: None)
    monkeypatch.setattr(
        ready, "readiness", lambda root: type("S", (), {"can_answer": False, "describe": lambda self: "not prepared"})()
    )

    said = derive._waiting(tmp_path)
    assert said and "background" in said
