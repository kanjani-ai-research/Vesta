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


# ── Bugs a live agent found ──────────────────────────────────────────────


def test_a_doubled_path_is_rewritten_to_one_the_graph_knows(code: Graph):
    """A live agent said "the path was doubled" and read the file the long way.

    An account cites paths relative to whatever root its session had; replayed
    from a different root, `vesta/acquire.py` becomes `vesta/vesta/acquire.py`
    and leads nowhere.
    """
    from vesta.harvest import anchor

    said = anchor("the tiers are in vesta/vesta/acquire.py:464", code)

    assert "vesta/vesta" not in said
    assert "vesta/acquire.py:464" in said


def test_a_bare_filename_is_rewritten_to_its_full_path(code: Graph):
    from vesta.harvest import anchor

    assert "vesta/acquire.py:464" in anchor("see acquire.py:464", code)


def test_a_path_the_graph_does_not_know_is_left_alone(code: Graph):
    """Rewriting a citation to something unrelated is worse than leaving it."""
    from vesta.harvest import anchor

    assert "vendor/thing.py:12" in anchor("see vendor/thing.py:12", code)


def test_a_stamp_is_written_once_and_not_re_anchored(code: Graph, tmp_path: Path, monkeypatch):
    """The bug that made authority circular.

    Re-stamping from the current code on every read meant a note always
    described what the code looks like now, so nothing was ever superseded and
    the check said "current" forever — which is the same as not checking.
    """
    import vesta.harvest as harvest

    monkeypatch.setattr(harvest, "NOTES", tmp_path / "notes")
    monkeypatch.setattr(harvest, "_HARVESTED", {})
    calls = {"n": 0}
    real = harvest.from_sessions

    def counting_region(graph, node, root):
        calls["n"] += 1
        return ("m.py:1-9", f"hash-{calls['n']}")

    monkeypatch.setattr("vesta.authority.bounded_region", counting_region)
    t = transcript(tmp_path, ACCOUNT)

    first = real(code, tmp_path, transcripts=[t])
    harvest._HARVESTED.clear()
    second = real(code, tmp_path, transcripts=[t])

    # The second read must reuse the first stamp, not compute a new one.
    assert first.notes[0].region_hash == second.notes[0].region_hash


# ── Whose transcript this is ────────────────────────────────────────────────


def _transcript(directory: Path, name: str, records: list) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    return path


def _spoke(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool_said(text: str) -> dict:
    return {
        "type": "user",
        "toolUseResult": {"stdout": text},
        "message": {"role": "user", "content": text},
    }


def test_a_session_that_only_ran_commands_against_a_repo_is_not_its_history(
    tmp_path, monkeypatch
):
    """The defect, found by looking at what a run had actually read.

    A session spent building something else, which happened to run commands
    against `~/Research/taguchi` to test a tool, mentioned that path 59 times
    — past the threshold — entirely in tool results and assistant output. The
    user never named it once, and the whole transcript was admitted as that
    repository's own history.
    """
    from vesta import harvest

    monkeypatch.setattr(harvest, "TRANSCRIPTS", tmp_path / "projects")
    monkeypatch.setattr(harvest, "_MATCHED", {})
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))

    elsewhere = tmp_path / "projects" / "-Users-someone-other-work"
    _transcript(
        elsewhere,
        "session",
        [_spoke("let's test the tool")]
        + [_tool_said(f"ran against /repo/target run {n}") for n in range(40)],
    )

    assert harvest._sessions_for(Path("/repo/target")) == []


def test_a_session_where_the_user_worked_on_it_is_its_history(
    tmp_path, monkeypatch
):
    """The case the matching exists for: the host keys a project by where the
    agent was launched, so work on a repository is often recorded elsewhere."""
    from vesta import harvest

    monkeypatch.setattr(harvest, "TRANSCRIPTS", tmp_path / "projects")
    monkeypatch.setattr(harvest, "_MATCHED", {})
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))

    launched_above = tmp_path / "projects" / "-Users-someone"
    _transcript(
        launched_above,
        "session",
        [_spoke(f"work on /repo/target, the thing in /repo/target please {n}")
         for n in range(30)],
    )

    assert len(harvest._sessions_for(Path("/repo/target"))) == 1


def test_only_the_user_naming_it_counts(tmp_path):
    from vesta import harvest

    path = _transcript(
        tmp_path,
        "s",
        [
            _spoke("please look at /repo/target"),
            _tool_said("/repo/target /repo/target /repo/target"),
            {"type": "assistant", "message": {"role": "assistant",
                                              "content": "/repo/target"}},
        ],
    )

    assert harvest._user_named(path, "/repo/target") == 1


def test_a_summary_replaying_a_path_is_not_the_user_naming_it(tmp_path):
    """A compaction summary quotes whole conversations back, so it names
    every path that was ever discussed."""
    from vesta import harvest

    path = _transcript(
        tmp_path,
        "s",
        [
            _spoke(
                "This session is being continued from a previous conversation "
                "that ran out of context. We worked on /repo/target at length."
            )
        ],
    )

    assert harvest._user_named(path, "/repo/target") == 0
