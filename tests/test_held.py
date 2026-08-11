"""Keeping a graph, and knowing when it is stale.

Rebuilding per question would make the graph too slow to ask, which is the same
as not having it. Serving a stale one would answer wrongly, invisibly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.held import forget, graph_for


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def base():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import base\n\n\ndef top():\n    return base()\n", encoding="utf-8")
    return tmp_path


def test_a_graph_is_kept_between_questions(repo: Path, monkeypatch):
    """The whole point: a sidecar answers many questions about one repository."""
    built = {"n": 0}
    import vesta.held as held
    real = held.build

    def counted(root, *a, **k):
        built["n"] += 1
        return real(root, *a, **k)

    monkeypatch.setattr(held, "build", counted)
    forget(repo)
    graph_for(repo)
    graph_for(repo)

    assert built["n"] == 1


def test_a_changed_file_makes_the_graph_stale(repo: Path, monkeypatch):
    """Staleness is decided by the files, not a clock: a time-to-live either
    serves a wrong graph or rebuilds a right one."""
    import vesta.held as held
    built = {"n": 0}
    real = held.build

    def counted(root, *a, **k):
        built["n"] += 1
        return real(root, *a, **k)

    monkeypatch.setattr(held, "build", counted)
    forget(repo)
    graph_for(repo)

    (repo / "c.py").write_text("def added():\n    return 2\n", encoding="utf-8")
    graph_for(repo)

    assert built["n"] == 2


def test_the_graph_survives_a_restart(repo: Path):
    """Cached to disk, so a sidecar restarted mid-session does not pay again."""
    forget(repo)
    first = graph_for(repo)
    forget(repo)  # as if the process had gone away
    second = graph_for(repo)

    assert set(second.nodes) == set(first.nodes)
