"""Keeping what a framework already worked out.

The semantics the rest of the project could not compute. String overlap
attaches `_resolve_with` to "resolve symbol references" because a token appears
in both; an agent reading the same file wrote a three-tier account of how it
fails. Only one of those is understanding, and it was being thrown away.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vesta.graph import Graph, Node
from vesta.harvest import from_sessions


def node(name: str, path: str, line: int) -> Node:
    return Node(id=f"{path}:{line}:{name}", name=name, path=path, line=line, kind=12)


@pytest.fixture
def code() -> Graph:
    nodes = [node("for_", "vesta/acquire.py", 463), node("judge", "vesta/maturity.py", 360)]
    return Graph(root="/x", nodes={n.id: n for n in nodes})


def transcript(tmp_path: Path, *says: str) -> Path:
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"message": {"role": "assistant", "content": [{"type": "text", "text": s}]}})
            for s in says
        ),
        encoding="utf-8",
    )
    return path


ACCOUNT = (
    "`Search.for_` (`vesta/acquire.py:464`) sorts failures into three tiers, and "
    "each tier has a different consequence for whether the source is retried. A "
    "standing failure is never retried; a rejected key removes the source."
)


def test_an_account_is_attached_where_its_author_pointed(code: Graph, tmp_path: Path):
    got = from_sessions(code, tmp_path, transcripts=[transcript(tmp_path, ACCOUNT)])

    assert got.notes
    target = next(n for n in code.nodes.values() if n.name == "for_")
    assert got.for_node(target.id)


def test_prose_citing_nothing_is_not_attached(code: Graph, tmp_path: Path):
    """Attribution is by citation, not by inference: a wrong attachment should
    mean the author pointed wrongly, not that a heuristic guessed."""
    said = "I have the full picture now and will summarise what the module does " * 3
    got = from_sessions(code, tmp_path, transcripts=[transcript(tmp_path, said)])

    assert not got.notes


def test_a_citation_the_graph_cannot_place_is_counted(code: Graph, tmp_path: Path):
    """A large number means the graph and the transcripts disagree about the
    repository, which a caller should be able to see."""
    said = (
        "The logic in `vendor/unknown.py:12` handles this case, and it matters "
        "because the surrounding code assumes the vendor module has already "
        "normalised its input before anything downstream reads it."
    )
    got = from_sessions(code, tmp_path, transcripts=[transcript(tmp_path, said)])

    assert got.unplaced == 1
    assert not got.notes


def test_a_short_label_is_not_an_account(code: Graph, tmp_path: Path):
    """Prose too short to explain anything is not worth keeping."""
    got = from_sessions(code, tmp_path, transcripts=[transcript(tmp_path, "See vesta/acquire.py:464.")])

    assert not got.notes


def test_one_definition_cited_twice_in_a_passage_is_one_account(code: Graph, tmp_path: Path):
    doubled = ACCOUNT + " Again, `vesta/acquire.py:464` is the place to change."
    got = from_sessions(code, tmp_path, transcripts=[transcript(tmp_path, doubled)])

    target = next(n for n in code.nodes.values() if n.name == "for_")
    assert len(got.for_node(target.id)) == 1


def test_a_bare_filename_resolves_to_the_definition(code: Graph, tmp_path: Path):
    """Agents cite paths as they please; a suffix match is what resolves them."""
    said = ACCOUNT.replace("vesta/acquire.py:464", "acquire.py:464")
    got = from_sessions(code, tmp_path, transcripts=[transcript(tmp_path, said)])

    assert got.notes


def test_only_assistant_prose_is_harvested(code: Graph, tmp_path: Path):
    """A user's question about a file is not an account of it."""
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps({
        "message": {"role": "user", "content": [{"type": "text", "text": ACCOUNT}]}
    }), encoding="utf-8")

    assert not from_sessions(code, tmp_path, transcripts=[path]).notes


def test_a_note_carries_when_and_where_it_came_from(code: Graph, tmp_path: Path):
    """An agent can be confidently wrong, so a claim must be weighable."""
    got = from_sessions(code, tmp_path, transcripts=[transcript(tmp_path, ACCOUNT)])

    assert got.notes[0].session
    assert got.notes[0].at > 0
