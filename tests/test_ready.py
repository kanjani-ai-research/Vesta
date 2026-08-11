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


# ── When preparation cannot finish ───────────────────────────────────────


def test_a_failure_is_remembered_not_forgotten(tmp_path: Path):
    """A cleared mark reads as "never attempted". The difference between that
    and "attempted and could not" is the whole of what a user needs to act."""
    import vesta.ready as ready

    root = a_project(tmp_path)
    ready._record_failure(root, "RuntimeError: no language server for .py")

    state = readiness(root)
    assert state.state == "failed"
    assert "no language server" in state.why
    assert "could not prepare" in state.describe()


def test_a_failed_project_is_not_retried_on_every_prompt(tmp_path: Path):
    """A broken environment must not spawn a build per message."""
    import vesta.ready as ready

    root = a_project(tmp_path)
    ready._record_failure(root, "boom")

    assert prepare(root).state == "failed"


def test_a_failure_is_forgotten_eventually(tmp_path: Path, monkeypatch):
    """Installing the missing thing should take effect without a restart."""
    import vesta.ready as ready

    root = a_project(tmp_path)
    ready._record_failure(root, "boom")
    monkeypatch.setattr(ready, "FORGET_FAILURE", 0.0)

    assert readiness(root).state == NOTHING


def test_a_build_that_raises_records_why(tmp_path: Path, monkeypatch):
    import vesta.held
    import vesta.ready as ready

    root = a_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("pyright is not installed")

    monkeypatch.setattr(vesta.held, "graph_for", boom)
    ready._build(str(root))

    state = readiness(root)
    assert state.state == "failed"
    assert "pyright" in state.why


def test_a_failure_is_written_where_readiness_looks(tmp_path: Path):
    """These disagreed once: one resolved the path and the other did not, so
    failures were written under one name and looked for under another."""
    import vesta.ready as ready

    root = a_project(tmp_path)
    unresolved = Path(str(root).replace("/", "//", 1))
    ready._record_failure(unresolved, "boom")

    assert readiness(root).state == "failed"


def test_injection_stays_silent_for_a_failed_project(tmp_path: Path):
    """Silence is right, but it must not also mean re-attempting forever."""
    from vesta.inject import context_for
    import vesta.ready as ready

    root = a_project(tmp_path)
    ready._record_failure(root, "boom")

    assert context_for("what does thing do", root) == ""
