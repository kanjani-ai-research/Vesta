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

    for spelling in ("venv", "virtualenv", "site-packages", "node_modules"):
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


# ── Nothing hidden, and no dependency directory ─────────────────────────────


def test_nothing_beginning_with_a_dot_is_ever_walked(tmp_path):
    """A dotfile is somebody's private business.

    Credentials in `.env`, tokens in `.aws`, a shell history, an editor's
    state. A tool that reads a repository to answer questions about its code
    has no reason to look inside one, and a rule beats a list because it
    cannot fall out of date.
    """
    from vesta.home import walk

    for hidden in (".env", ".aws", ".ssh", ".git", ".venv", ".conda", ".idea"):
        root = tmp_path / f"has-{hidden.lstrip('.')}"
        (root / hidden).mkdir(parents=True)
        (root / hidden / "secret.py").write_text("token = 'x'\n", encoding="utf-8")
        assert walk(root, ".py") == [], f"{hidden} was walked"


def test_visible_dependency_directories_are_banned_by_name(tmp_path):
    """The dot rule alone is not enough: most dependency directories are not
    hidden. `venv` without a dot was the spelling whose absence cost one
    repository 13,613 files of somebody's virtualenv."""
    from vesta.home import walk

    for name in (
        "venv", "node_modules", "site-packages", "target", "vendor",
        "Pods", "miniconda3", "__pycache__", "third_party",
    ):
        root = tmp_path / f"with-{name}"
        (root / name).mkdir(parents=True)
        (root / name / "dep.py").write_text("x = 1\n", encoding="utf-8")
        assert walk(root, ".py") == [], f"{name} was walked"


def test_a_directory_that_is_somebody_else_s_source_is_not_banned():
    """`bin`, `deps`, `pkg`, `packages` and `external` are each a dependency
    directory somewhere and somebody's own source elsewhere. This repository
    keeps its launcher in `bin/`; the workspace next door keeps a real
    component in `deps/`. Excluding one somebody works in is silent, and
    walking one they do not is only slow."""
    from vesta.home import NOT_THE_PROJECT

    for name in ("bin", "deps", "pkg", "packages", "external", "obj", "src"):
        assert name not in NOT_THE_PROJECT, f"{name} would hide real source"


def test_a_project_under_a_hidden_directory_is_still_walked(tmp_path):
    """The test applies below the root, not to where the root lives. Somebody
    working in `~/.local/src/thing` has not asked to be invisible."""
    from vesta.home import walk

    root = tmp_path / ".local" / "src" / "thing"
    root.mkdir(parents=True)
    (root / "app.py").write_text("def main(): pass\n", encoding="utf-8")

    assert [p.name for p in walk(root, ".py")] == ["app.py"]


def test_the_fingerprint_ignores_what_is_not_the_project(tmp_path):
    from vesta.held import _shape, _SHAPES

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "venv" / "lib").mkdir(parents=True)
    (root / "venv" / "lib" / "dep.py").write_text("y = 1\n", encoding="utf-8")

    _SHAPES.clear()
    before = _shape(root)
    (root / "venv" / "lib" / "dep.py").write_text("y = 2\n", encoding="utf-8")
    _SHAPES.clear()
    assert _shape(root) == before, "a change under venv moved the fingerprint"

    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    _SHAPES.clear()
    assert _shape(root) != before, "a real edit did not move the fingerprint"


def test_a_graph_is_never_served_stale(tmp_path, monkeypatch):
    """The invariant: whenever Vesta is active, its graph matches the code.

    Every sidecar tool asked for `trust_for=300`, so during an active session —
    the one time code changes minute to minute — answers came from a graph that
    could be a hundred edits behind. The fingerprint that would have caught it
    cost 3.6 seconds; it now costs 8 milliseconds, so there is nothing to trade.
    """
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    from vesta.held import graph_for

    root = tmp_path / "live"
    root.mkdir()
    (root / "a.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    assert len(graph_for(root).nodes) == 1

    (root / "b.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    # Even with the old trust window, the answer must be current.
    assert len(graph_for(root, trust_for=300).nodes) == 2


def test_an_edit_of_the_same_length_moves_the_fingerprint(tmp_path):
    """One-second mtime resolution missed the commonest edit there is.

    `int(st.st_mtime)` plus a size meant `x = 1` becoming `x = 2` within the
    same second changed nothing observable, and the graph went on describing
    code that no longer existed. Small, fast, same-length corrections are
    exactly what an active session produces most.
    """
    from vesta.held import _shape, _SHAPES

    root = tmp_path / "quick"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    _SHAPES.clear()
    before = _shape(root)

    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    _SHAPES.clear()
    assert _shape(root) != before


def test_a_fingerprint_is_not_reused_across_an_edit(tmp_path, monkeypatch):
    """The memo was two seconds, chosen when the walk cost 3.6 of them.

    An agent that writes a file and then asks about it — the ordinary rhythm
    of a session — was answered from the tree as it stood before the write.
    """
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    import time

    from vesta.held import _SHAPE_TTL, graph_for

    assert _SHAPE_TTL <= 0.5, "the memo is long enough to hide an edit"

    root = tmp_path / "rhythm"
    root.mkdir()
    (root / "a.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    assert len(graph_for(root).nodes) == 1

    (root / "b.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    time.sleep(_SHAPE_TTL + 0.05)
    assert len(graph_for(root, trust_for=300).nodes) == 2
