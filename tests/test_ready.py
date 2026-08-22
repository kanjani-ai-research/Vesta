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

from vesta.ready import MISSING, NOTHING, PREPARING, READY, prepare, readiness


# Where things are kept is handled by the conftest, which points every run at a
# directory it owns. A fixture here patched the graph directory directly and
# replaced a function with a path, which broke every test that wrote a graph.


def a_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def thing():\n    return 1\n", encoding="utf-8")
    return root


def test_a_project_with_nothing_built_is_not_ready(tmp_path: Path):
    assert readiness(a_project(tmp_path)).state == NOTHING


def test_a_path_that_does_not_exist_is_not_the_same_as_unbuilt(tmp_path: Path):
    """The two looked identical: both fell through to "nothing has been
    built", which sends a user chasing a build that can never succeed rather
    than telling them the path itself is wrong."""
    absent = tmp_path / "does-not-exist" / "at-all"

    found = readiness(absent)

    assert found.state == MISSING
    assert found.state != NOTHING
    assert not found.can_answer
    assert "not a directory" in found.describe()


def test_a_missing_path_is_distinguishable_by_its_own_message(tmp_path: Path):
    """The message itself, not just the state code, has to say something
    different — a caller reading only `describe()` must not see the same
    sentence for two different problems."""
    unbuilt = readiness(a_project(tmp_path)).describe()
    absent = readiness(tmp_path / "nope").describe()

    assert unbuilt != absent


def test_a_missing_part_does_not_make_a_workspace_report_ready(tmp_path: Path):
    """`_readiness_of_parts` ranks states worst-first and falls through to
    READY if none of the worse states is present — MISSING has to be in that
    ranking or a part that vanished between discovery and this check would
    make the whole workspace look complete."""
    from vesta.ready import _readiness_of_parts

    real = tmp_path / "real"
    real.mkdir()
    (real / "a.py").write_text("def one():\n    return 1\n", encoding="utf-8")

    gone = tmp_path / "gone"  # never created: simulates a part deleted mid-check

    found = _readiness_of_parts(tmp_path, [real, gone])

    assert found.state == MISSING


def test_preparing_a_missing_path_does_not_start_a_build(tmp_path: Path, monkeypatch):
    """`prepare` declines whenever readiness is not NOTHING, and a missing
    path now reports MISSING rather than NOTHING — this is what stops a mark
    being written and a build being started against a path with no code."""
    started = {"n": 0}
    import vesta.ready as ready_module

    monkeypatch.setattr(ready_module, "_start_build", lambda root: started.__setitem__("n", started["n"] + 1))

    absent = tmp_path / "nope"
    result = prepare(absent)

    assert result.state == MISSING
    assert started["n"] == 0


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


def test_the_state_directory_follows_the_store(tmp_path):
    """Bound at import, this was evaluated before any fixture could move the
    store — so every test recording a failure wrote into the user's real
    `~/.vesta/prepared`. Fifty stale marks saying "boom" were found there.

    `GRAPH_DIR` had already been fixed for exactly this, and the same rule
    applies: a location that can move must be read, not remembered.
    """
    import vesta.home as home_module
    import vesta.ready as ready

    moved = tmp_path / "elsewhere"
    home_module.keep_in(moved)
    try:
        assert ready.STATE().resolve() == (moved / "prepared").resolve()
    finally:
        home_module.keep_in(None)


def test_a_build_that_resolved_nothing_is_not_cached(tmp_path, monkeypatch):
    """A broken environment must not be remembered as an empty repository.

    A detached build inherits `sys.executable` but not the user's PATH, so
    `pyright-langserver` in `~/.n/bin` was unreachable. The graph came back
    with 0 definitions and 79 holes saying "no server for this language", was
    written to disk, and the project then reported itself ready with nothing
    in it — answering every later question from nothing, confidently.
    """
    import pytest

    from vesta.graph import Graph, Hole
    from vesta.held import GRAPH_DIR, graph_for

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def one(): pass\n", encoding="utf-8")

    def _nothing(where):
        empty = Graph(root=str(where))
        empty.holes.append(
            Hole(path="a.py", what="a.py", why="no server for this language")
        )
        return empty

    monkeypatch.setattr("vesta.held.build", _nothing)

    with pytest.raises(RuntimeError, match="resolved nothing"):
        graph_for(root)

    assert not list(GRAPH_DIR().glob("*.json")), "an empty graph was cached"


def test_an_empty_repository_is_still_cached(tmp_path, monkeypatch):
    """A project with nothing in it is not a broken environment. The holes are
    what tell the two apart."""
    from vesta.held import graph_for

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = tmp_path / "empty"
    root.mkdir()
    (root / "README.md").write_text("# nothing here\n", encoding="utf-8")

    graph = graph_for(root)
    assert len(graph.nodes) == 0  # and no exception


def test_a_detached_build_can_find_a_language_server(tmp_path, monkeypatch):
    """A hook runs in a minimal shell and `Popen` inherits it. The places a
    language server is installed are few and worth naming."""
    import vesta.ready as ready

    seen = {}

    def _fake(cmd, **kw):
        seen.update(kw)

        class _P:
            pass

        return _P()

    monkeypatch.setattr(ready.subprocess, "Popen", _fake)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    ready._start_build(tmp_path)

    assert "env" in seen, "the build was given no environment"
    assert seen["env"]["PATH"] != "/usr/bin:/bin", "PATH was not widened"
