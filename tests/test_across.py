"""Referring to another project while working in one."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from vesta import across
from vesta.across import Project, known, loaded, refer, release, resolve


@pytest.fixture(autouse=True)
def _nothing_referred():
    release()
    yield
    release()


def _graphed(root: Path) -> Path:
    from vesta.held import graph_for

    root.mkdir(parents=True, exist_ok=True)
    (root / "thing.py").write_text('"""A module."""\n\n\ndef work():\n    return 1\n')
    graph_for(root)
    return root


def test_a_path_is_taken_as_a_path(tmp_path):
    found = resolve(str(tmp_path))
    assert found.found
    assert Path(found.project.path) == tmp_path.resolve()


def test_a_path_that_is_not_a_directory_says_so(tmp_path):
    found = resolve(str(tmp_path / "absent"))
    assert not found.found
    assert "not a directory" in found.describe()


def test_a_bare_word_is_a_name_not_a_directory(tmp_path, monkeypatch):
    """Run from a repository root, `vesta` names a project and is also a
    directory inside it. The name must win, or the answer is about the package."""
    inside = tmp_path / "vesta"
    inside.mkdir()
    monkeypatch.chdir(tmp_path)
    found = resolve("vesta")
    assert not found.found or Path(found.project.path) != inside


def test_a_name_this_session_was_given_resolves(tmp_path):
    root = tmp_path / "ledger"
    root.mkdir()
    found = resolve("ledger", roots=[root])
    assert found.found
    assert Path(found.project.path) == root.resolve()


def test_a_prepared_project_resolves_by_name(tmp_path):
    root = _graphed(tmp_path / "chronicle")
    found = resolve("chronicle")
    assert found.found
    assert Path(found.project.path) == root.resolve()


def test_part_of_a_name_resolves_when_only_one_matches(tmp_path):
    root = tmp_path / "peculiar-name"
    root.mkdir()
    found = resolve("peculiar", roots=[root])
    assert found.found
    assert Path(found.project.path) == root.resolve()


def test_an_unknown_name_is_not_searched_for(tmp_path):
    """The disk is not scanned. A tool that hunts a filesystem for a word finds
    something eventually and it is wrong."""
    buried = tmp_path / "deep" / "deeper" / "quarry"
    buried.mkdir(parents=True)
    found = resolve("quarry")
    assert not found.found
    said = found.describe()
    assert "does not search the disk" in said
    assert "by path" in said


def test_two_projects_of_one_name_ask_for_a_path(tmp_path):
    first = tmp_path / "one" / "twin"
    second = tmp_path / "two" / "twin"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    found = resolve("twin", roots=[first, second])
    assert not found.found
    assert len(found.ambiguous) == 2
    assert "more than one" in found.describe()
    assert "Say which by path" in found.describe()


def test_the_most_recently_referred_to_wins(tmp_path):
    first = tmp_path / "one" / "twin"
    second = tmp_path / "two" / "twin"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    refer(str(second.resolve()))
    found = resolve("twin", roots=[first, second])
    assert found.found
    assert Path(found.project.path) == second.resolve()


def test_nothing_named_is_reported(tmp_path):
    assert not resolve("   ").found


def test_a_reference_falls_away_when_nobody_mentions_it(tmp_path):
    root = tmp_path / "fading"
    root.mkdir()
    refer(str(root.resolve()))
    assert [p.name for p in loaded()] == ["fading"]
    assert loaded(now=time.time() + across.STAYS + 1) == []


def test_releasing_one_leaves_the_others(tmp_path):
    first, second = tmp_path / "kept", tmp_path / "dropped"
    first.mkdir()
    second.mkdir()
    refer(str(first.resolve()))
    refer(str(second.resolve()))
    release(str(second.resolve()))
    assert [p.name for p in loaded()] == ["kept"]


def test_a_referenced_project_that_is_gone_is_not_listed(tmp_path):
    root = tmp_path / "vanishing"
    root.mkdir()
    refer(str(root.resolve()))
    root.rmdir()
    assert loaded() == []


def test_the_session_supersedes_what_was_prepared(tmp_path):
    root = _graphed(tmp_path / "current")
    entries = {p.path: p for p in known(roots=[root])}
    assert entries[str(root.resolve())].prepared is True
