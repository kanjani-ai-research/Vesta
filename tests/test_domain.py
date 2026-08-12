"""The ontology of what a repository is for, derived from the repository.

`traverse` could cross between code and concept and had nothing to cross to.
The difficulty is narrowness: a broad purpose labels everything and partitions
nothing — a general software-development ontology once attached "check for code
duplication" to `class Collection:` at 0.70 confidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.domain import Ontology, _purpose_from, _speaks, as_terms


def a_repo(tmp_path: Path) -> Path:
    (tmp_path / "resolve.py").write_text(
        '"""Resolution through a language server.\n\n'
        'Driven against real code, because the point is that it is not '
        'language-specific."""\n\ndef go():\n    pass\n',
        encoding="utf-8",
    )
    (tmp_path / "tiny.py").write_text('"""Short."""\n', encoding="utf-8")
    (tmp_path / "test_resolve.py").write_text(
        '"""Tests for resolution, which describe a test rather than the work."""\n',
        encoding="utf-8",
    )
    return tmp_path


def test_a_repository_is_read_through_its_own_words(tmp_path: Path):
    """Docstrings rather than names: a name is a label, a docstring is a
    statement of intent."""
    said = _speaks(a_repo(tmp_path))

    assert [where for where, _ in said] == ["resolve.py"]
    assert "language server" in said[0][1]


def test_a_test_does_not_describe_the_work(tmp_path: Path):
    assert not [w for w, _ in _speaks(a_repo(tmp_path)) if "test" in w]


def test_a_purpose_names_this_project_not_software_in_general(tmp_path: Path):
    """The failure this exists to avoid: an ontology that attaches to
    everything separates nothing."""
    root = a_repo(tmp_path)
    purpose = _purpose_from(root, _speaks(root))

    assert root.name in purpose
    assert "language server" in purpose
    assert "not software development in general" in purpose


def test_an_ontology_becomes_terms():
    ontology = Ontology(
        terms=[
            {"id": "a:1", "kind": "activity", "label": "resolve symbols"},
            {"id": "d:1", "kind": "domain", "label": "code analysis"},
            {"id": "x:1", "kind": "activity", "label": ""},
        ]
    )
    got = as_terms(ontology)

    assert len(got) == 2  # the unlabelled one is not a term
    assert {t.kind for t in got} == {"activity", "domain"}


def test_a_repository_that_says_nothing_yields_nothing(tmp_path: Path):
    """Better than an ontology invented from filenames."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    assert len(_speaks(tmp_path)) < 3
