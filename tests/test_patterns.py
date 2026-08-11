"""Things worth fixing, found without being asked.

The governing constraint is that unusual is not wrong. A first attempt reported
ninety-two definitions nothing refers to and almost all were tests — nothing
*should* refer to a test — so every pattern here is tested for what it
deliberately does not report, not only for what it finds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.dynamic import Blindspot, Unresolved
from vesta.graph import Edge, Graph, Node
from vesta.patterns import (
    hardcoded_language_lists,
    survey,
    swallowed_failures,
    unreachable_definitions,
    unresolvable_reach,
)


def node(name, path="a.py", line=0, container=""):
    return Node(id=f"{path}:{line}:{name}", name=name, path=path, line=line,
                kind=12, container=container)


@pytest.fixture
def empty() -> Blindspot:
    return Blindspot()


# ── Hardcoded language lists ─────────────────────────────────────────────


def test_a_language_table_is_found(tmp_path: Path, empty):
    (tmp_path / "resolve.py").write_text(
        'Server(languages=["rust"], suffixes=[".rs"])\n', encoding="utf-8"
    )
    found = hardcoded_language_lists(Graph(root=str(tmp_path)), tmp_path, empty)

    assert found and found[0].where == "resolve.py"
    assert "cannot handle" in found[0].why


def test_a_test_fixture_naming_a_language_is_not_reported(tmp_path: Path, empty):
    """A fixture naming a language is naming it on purpose."""
    (tmp_path / "test_resolve.py").write_text(
        'Server(languages=["x"], suffixes=[".x"])\n', encoding="utf-8"
    )

    assert not hardcoded_language_lists(Graph(root=str(tmp_path)), tmp_path, empty)


# ── Swallowed failures ───────────────────────────────────────────────────


def test_a_discarded_error_is_found(tmp_path: Path, empty):
    (tmp_path / "a.py").write_text(
        "try:\n    go()\nexcept OSError:\n    pass\n", encoding="utf-8"
    )
    found = swallowed_failures(Graph(root=str(tmp_path)), tmp_path, empty)

    assert found and found[0].line == 3


def test_a_handler_that_records_is_not_reported(tmp_path: Path, empty):
    """Only the ones that vanish. A handler that logs, re-raises, or returns
    something naming the failure is doing its job."""
    (tmp_path / "a.py").write_text(
        "try:\n    go()\nexcept OSError as exc:\n    logger.warning(exc)\n",
        encoding="utf-8",
    )

    assert not swallowed_failures(Graph(root=str(tmp_path)), tmp_path, empty)


# ── Unreachable definitions ──────────────────────────────────────────────


def test_a_test_is_never_reported_as_unreferenced(tmp_path: Path, empty):
    """The ninety-two. Nothing refers to a test, by design."""
    graph = Graph(root=str(tmp_path), nodes={
        n.id: n for n in [node("test_a_thing", "tests/test_x.py")]
    })

    assert not unreachable_definitions(graph, tmp_path, empty)


def test_a_private_helper_is_not_reported(tmp_path: Path, empty):
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in [node("_helper")]})

    assert not unreachable_definitions(graph, tmp_path, empty)


def test_something_reached_only_by_name_is_not_reported(tmp_path: Path):
    """The graph cannot see it; that is not the same as nothing using it."""
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in [node("why_not")]})
    blind = Blindspot(found=[Unresolved(path="x.py", line=1, name="why_not")])

    assert not unreachable_definitions(graph, tmp_path, blind)


def test_a_genuinely_unreferenced_definition_is_found(tmp_path: Path, empty):
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in [node("orphaned")]})
    found = unreachable_definitions(graph, tmp_path, empty)

    assert found and found[0].what == "orphaned"
    assert found[0].confidence == "worth a look"


def test_a_referenced_definition_is_not_reported(tmp_path: Path, empty):
    used, user = node("used"), node("user", line=9)
    graph = Graph(root=str(tmp_path), nodes={used.id: used, user.id: user},
                  edges=[Edge(source=user.id, target=used.id)])

    assert not [f for f in unreachable_definitions(graph, tmp_path, empty)
                if f.what == "used"]


# ── Dynamic reach ────────────────────────────────────────────────────────


def test_dynamic_access_in_a_test_is_not_reported(tmp_path: Path):
    """In a test it is usually the subject rather than an accident."""
    blind = Blindspot(found=[Unresolved(path="tests/test_x.py", line=1, name="thing")])

    assert not unresolvable_reach(Graph(root=str(tmp_path)), tmp_path, blind)


# ── The survey ───────────────────────────────────────────────────────────


def test_every_finding_says_why_it_matters(tmp_path: Path):
    """A finding a reader cannot act on or dismiss in one pass is noise."""
    (tmp_path / "a.py").write_text(
        "try:\n    go()\nexcept OSError:\n    pass\n", encoding="utf-8"
    )
    found = survey(Graph(root=str(tmp_path)), tmp_path)

    assert found.found
    assert all(f.why for f in found.found)


def test_a_clean_repository_says_so(tmp_path: Path):
    (tmp_path / "a.py").write_text('"""Fine."""\n', encoding="utf-8")
    found = survey(Graph(root=str(tmp_path)), tmp_path)

    assert not found.found
    assert "nothing found" in found.describe()
