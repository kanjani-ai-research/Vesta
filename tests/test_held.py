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


# ── Dependencies are not the project ────────────────────────────────────────


def test_a_virtualenv_without_a_dot_is_not_the_project():
    """The defect that made a large repository unusable.

    A real project was 62 source files beside a `venv/` holding 13,613. The
    exclusion list said `.venv` with a dot; the directory was named `venv`
    without one, which is at least as common. Vesta walked all 13,675.
    """
    from vesta.home import NOT_THE_PROJECT

    for spelling in ("venv", ".venv", "env", "virtualenv", ".tox", "site-packages"):
        assert spelling in NOT_THE_PROJECT, f"{spelling} is not the project"


def test_the_exclusion_list_is_shared_by_everything_that_walks():
    """There were three lists in three modules with three different contents,
    so what the resolver walked and what the graph called its shape could
    disagree — and the spelling that mattered was in none of them."""
    from vesta.held import IGNORED
    from vesta.home import NOT_THE_PROJECT
    from vesta.resolve import _SKIP

    assert IGNORED is NOT_THE_PROJECT
    for name in NOT_THE_PROJECT:
        assert name in _SKIP, f"the resolver would walk {name}"


def test_output_directories_somebody_might_work_in_are_not_excluded():
    """`build` and `dist` are output in most projects and source in others.
    Excluding a directory somebody works in is a worse failure than walking
    one they do not."""
    from vesta.home import NOT_THE_PROJECT

    assert "build" not in NOT_THE_PROJECT
    assert "dist" not in NOT_THE_PROJECT


def test_a_tree_with_a_venv_resolves_only_the_project(tmp_path):
    from vesta.home import NOT_THE_PROJECT

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main(): pass\n", encoding="utf-8")
    deep = tmp_path / "venv" / "lib" / "python3.13" / "site-packages" / "dep"
    deep.mkdir(parents=True)
    for n in range(20):
        (deep / f"mod{n}.py").write_text("x = 1\n", encoding="utf-8")

    walked = [
        p for p in tmp_path.rglob("*.py")
        if not any(part in NOT_THE_PROJECT for part in p.parts)
    ]
    assert [p.name for p in walked] == ["app.py"]
