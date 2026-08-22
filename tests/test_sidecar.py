"""The sidecar's answers, where they can go wrong silently.

`_does` found a real gap: an ontology's attachments point at node ids, and a
node id is a hash of `(path, line, name)` — any edit that shifts a line
number orphans the attachment even though nothing about the definition
changed. When every attachment a phrase matched turns out to be orphaned,
`_does` used to return a bare two-line header with no body and no
explanation, indistinguishable from a phrase naming nothing at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.graph import Graph, Node
from vesta.sidecar import _does
from vesta.traverse import Attachment, Map


def _graph(*names: str) -> Graph:
    nodes = {
        f"id-{name}": Node(id=f"id-{name}", name=name, path="x.py", line=i, kind=12)
        for i, name in enumerate(names)
    }
    return Graph(root="/x", nodes=nodes)


def test_hits_that_all_point_to_stale_nodes_are_reported_not_silent(tmp_path, monkeypatch):
    """The bug, reproduced directly: a Map whose attachments resolve to no
    node in the current graph must not degrade to an empty body."""
    graph = _graph("current_function")
    stale_map = Map(
        attachments=[
            Attachment(
                node="id-a-node-that-no-longer-exists",
                term="t:1", label="resolving imports", kind="activity", strength=0.9,
            )
        ]
    )

    monkeypatch.setattr("vesta.sidecar.graph_for", lambda *a, **k: graph)
    monkeypatch.setattr("vesta.sidecar.recall_map", lambda *a, **k: stale_map)
    monkeypatch.setattr("vesta.sidecar.where_in", lambda *a, **k: stale_map.attachments)

    said = _does("resolving imports", tmp_path)

    assert "moved since" in said or "no longer" in said
    # And not the empty-body shape this used to produce: a header with
    # nothing under it reads as a match with results, which this is not.
    lines = [l for l in said.splitlines() if l.strip()]
    assert len(lines) > 1


def test_hits_that_resolve_are_shown_normally(tmp_path, monkeypatch):
    """The fix must not turn a real, resolvable hit into a false stale
    report — only when every hit is orphaned does the new message apply."""
    graph = _graph("current_function")
    fresh_map = Map(
        attachments=[
            Attachment(
                node="id-current_function",
                term="t:1", label="resolving imports", kind="activity", strength=0.9,
            )
        ]
    )

    monkeypatch.setattr("vesta.sidecar.graph_for", lambda *a, **k: graph)
    monkeypatch.setattr("vesta.sidecar.recall_map", lambda *a, **k: fresh_map)
    monkeypatch.setattr("vesta.sidecar.where_in", lambda *a, **k: fresh_map.attachments)

    said = _does("resolving imports", tmp_path)

    assert "current_function" in said
    assert "moved since" not in said


def test_a_mix_of_stale_and_fresh_hits_shows_only_the_fresh_ones(tmp_path, monkeypatch):
    """Partial staleness is not total staleness — one orphaned attachment
    among several real ones should not suppress the real results, and should
    not trigger the all-stale message either."""
    graph = _graph("current_function")
    mixed_map = Map(
        attachments=[
            Attachment(node="id-a-stale-one", term="t:1", label="a", kind="activity", strength=0.9),
            Attachment(node="id-current_function", term="t:2", label="b", kind="activity", strength=0.8),
        ]
    )

    monkeypatch.setattr("vesta.sidecar.graph_for", lambda *a, **k: graph)
    monkeypatch.setattr("vesta.sidecar.recall_map", lambda *a, **k: mixed_map)
    monkeypatch.setattr("vesta.sidecar.where_in", lambda *a, **k: mixed_map.attachments)

    said = _does("something", tmp_path)

    assert "current_function" in said
    assert "moved since" not in said
