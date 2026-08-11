"""Vesta must not get in the way until it can help.

Three situations it has to survive identically: a brand new project with
nothing in it, a mature project seen for the first time, and a mature project
somebody has been working in for months before Vesta arrived.

The measured cost of building a graph is eight to twelve seconds. Spending
that on a user's first prompt makes the session worse whether or not it later
helps, so the rule is that a prompt never waits.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from vesta.ready import NOTHING, PREPARING, READY, prepare, readiness


@pytest.fixture(autouse=True)
def elsewhere(tmp_path, monkeypatch):
    """Keep every test off the real ~/.vesta."""
    import vesta.held as held
    import vesta.ready as ready

    monkeypatch.setattr(ready, "STATE", tmp_path / "prepared")
    monkeypatch.setattr(held, "GRAPH_DIR", tmp_path / "graphs")
    monkeypatch.setattr(held, "_HELD", {})
    monkeypatch.setattr(held, "_SHAPES", {})


def a_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    return root


def test_a_project_with_nothing_built_is_not_ready(tmp_path: Path):
    assert readiness(a_project(tmp_path)).state == NOTHING


def test_a_prompt_never_waits_for_a_build(tmp_path: Path):
    """The whole point. A hook that spends ten seconds on the first message
    has made the session worse for everyone."""
    from vesta.inject import context_for

    root = a_project(tmp_path)
    started = time.monotonic()
    said = context_for("what does thing do", root)

    assert time.monotonic() - started < 1.0
    assert said == ""


def test_asking_starts_preparation(tmp_path: Path):
    """Silence is not idleness: the next prompt should be able to answer."""
    from vesta.inject import context_for

    root = a_project(tmp_path)
    context_for("what does thing do", root)

    assert readiness(root).state in (PREPARING, READY)


def test_preparation_is_not_started_twice(tmp_path: Path):
    root = a_project(tmp_path)
    first = prepare(root)
    second = prepare(root)

    assert first.state == PREPARING
    assert second.state == PREPARING
    assert second.since == first.since


def test_a_stale_mark_does_not_block_forever(tmp_path: Path, monkeypatch):
    """A process that died mid-build must not stop every later session from
    trying again."""
    import vesta.ready as ready

    monkeypatch.setattr(ready, "STALE", 0.0)
    root = a_project(tmp_path)
    prepare(root)

    assert readiness(root).state == NOTHING


def test_readiness_says_what_it_is_doing(tmp_path: Path):
    """A user who wonders why nothing is happening should be able to find
    out, rather than concluding the tool is broken."""
    root = a_project(tmp_path)

    assert "not prepared" in readiness(root).describe()
    prepare(root)
    assert "preparing" in readiness(root).describe()


def test_a_built_project_answers_without_preparing(tmp_path: Path):
    from vesta.held import graph_for

    root = a_project(tmp_path)
    graph_for(root)

    state = readiness(root)
    assert state.state == READY
    assert state.can_answer
    assert state.definitions >= 0
