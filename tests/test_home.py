"""What is, and is not, the project.

A walk that indexes build output doubles every definition in the package;
one that skips a directory somebody works in loses it silently. The author's
own `.gitignore` is the one list that is right for their repository.
"""

from __future__ import annotations

from pathlib import Path

from vesta.home import ignored_by_git, walk


def _source(at: Path, *parts: str) -> Path:
    path = at.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def f():\n    pass\n", encoding="utf-8")
    return path


def _names(found) -> set:
    return {str(p.relative_to(p.parents[len(p.relative_to(p.anchor).parts) - 1])) for p in found} if False else {p.name for p in found}


def test_the_gitignore_is_honoured(tmp_path):
    _source(tmp_path, "pkg", "a.py")
    _source(tmp_path, "out", "b.py")
    _source(tmp_path, "pkg", "scratch_c.py")
    (tmp_path / ".gitignore").write_text("out/\nscratch_*.py\n# a comment\n!kept.py\n", encoding="utf-8")
    assert _names(walk(tmp_path)) == {"a.py", ".gitignore"} - {".gitignore"}


def test_an_anchored_pattern_matches_the_relative_path(tmp_path):
    _source(tmp_path, "pkg", "gen", "a.py")
    _source(tmp_path, "other", "gen", "b.py")
    (tmp_path / ".gitignore").write_text("pkg/gen\n", encoding="utf-8")
    assert _names(walk(tmp_path)) == {"b.py"}


def test_build_output_beside_a_manifest_is_not_the_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    _source(tmp_path, "pkg", "a.py")
    _source(tmp_path, "build", "lib", "pkg", "a.py")
    _source(tmp_path, "dist", "pkg", "a.py")
    assert [str(p.relative_to(tmp_path)) for p in walk(tmp_path, ".py")] == ["pkg/a.py"]


def test_a_build_directory_without_a_manifest_is_somebodys_source(tmp_path):
    """A repository of build scripts keeps them in `build/`."""
    _source(tmp_path, "build", "release.py")
    assert _names(walk(tmp_path, ".py")) == {"release.py"}


def test_a_nested_build_directory_is_kept(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    _source(tmp_path, "pkg", "build", "steps.py")
    assert _names(walk(tmp_path, ".py")) == {"steps.py"}


def test_an_unreadable_or_absent_gitignore_ignores_nothing(tmp_path):
    assert ignored_by_git(tmp_path)(tmp_path / "anything.py") is False
