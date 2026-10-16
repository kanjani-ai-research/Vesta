"""The seam between an agent's judgement and Vesta's records.

An agent decides and produces prose; Vesta needs structure. Everything here
parses, validates against the graph, and writes — it judges nothing, because
judging is what moved to the host's inference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.derive import read_attachments, read_terms
from vesta.graph import Graph, Node


def a_graph(tmp_path: Path) -> Graph:
    nodes = [
        Node(id="n1", name="advance", path="pipe.py", line=6, kind=12),
        Node(id="n2", name="note", path="audit.py", line=1, kind=12),
    ]
    return Graph(root=str(tmp_path), nodes={n.id: n for n in nodes})


def test_terms_are_parsed_from_prose():
    """An agent asked for a list will preface it, number it, or bullet it.
    Refusing the batch over a stray line would make the seam brittle exactly
    where it must not be."""
    got = read_terms(
        "Here is what I found:\n\n"
        "domain: record pipelines\n"
        "- activity: move a record to the next stage\n"
        "  role: pipeline stage\n"
        "this line is not a term\n"
    )

    assert [t.kind for t in got] == ["domain", "activity", "role"]
    assert got[1].label == "move a record to the next stage"


def test_a_term_too_short_to_mean_anything_is_dropped():
    assert not read_terms("domain: ab\n")


def test_an_attachment_is_placed_against_the_graph(tmp_path: Path):
    graph = a_graph(tmp_path)
    placed, refused = read_attachments(
        "pipe.py:7 advance | move a record to the next stage\n", graph
    )

    assert placed == [("n1", "move a record to the next stage")]
    assert not refused


def test_an_attachment_pointing_nowhere_is_refused(tmp_path: Path):
    """A map that points nowhere is worse than a smaller one."""
    graph = a_graph(tmp_path)
    placed, refused = read_attachments("pipe.py:900 ghost | something\n", graph)

    assert not placed
    assert "no definition there" in refused[0]


def test_a_line_off_by_one_still_places(tmp_path: Path):
    """An agent reading a file may be a line out either way."""
    graph = a_graph(tmp_path)
    placed, _ = read_attachments("pipe.py:8 advance | moving records\n", graph)

    assert placed and placed[0][0] == "n1"


def test_a_bare_filename_places_against_a_full_path(tmp_path: Path):
    nodes = {"n1": Node(id="n1", name="go", path="src/deep/mod.py", line=0, kind=12)}
    graph = Graph(root=str(tmp_path), nodes=nodes)

    placed, _ = read_attachments("deep/mod.py:1 go | doing the thing\n", graph)
    assert placed


def test_an_unbuilt_graph_says_so_rather_than_answering_emptily(tmp_path: Path, monkeypatch):
    """An empty list reads as "this repository has none" — a false answer that
    sends an agent away. A silence and an answer must not look alike."""
    import vesta.derive as derive
    import vesta.ready as ready

    monkeypatch.setattr(ready, "STATE", tmp_path / "prepared")
    monkeypatch.setattr(ready, "prepare", lambda root: None)
    monkeypatch.setattr(
        ready, "readiness", lambda root: type("S", (), {"can_answer": False, "describe": lambda self: "not prepared"})()
    )

    said = derive._waiting(tmp_path)
    assert said and "background" in said


# ── What a binding records about the code it names ──────────────────────────


def test_a_written_binding_carries_identity_and_bytes(tmp_path, monkeypatch):
    """Writing the id alone is what left 68% of this repository's map dangling.

    A binding records what it points at — so a line inserted above it does not
    orphan it — and what the bytes were, so a later reader can tell a claim that
    still stands from one whose code changed underneath it. Neither is
    recoverable afterwards: an id is a hash, and a hash of a region nobody kept
    cannot be compared with anything.
    """
    import vesta.derive as derive
    from vesta.home import VESTA_HOME

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    (tmp_path / "app.py").write_text(
        '"""App."""\n\n\ndef parse_retry(spec):\n    """Read it."""\n    return spec\n',
        encoding="utf-8",
    )

    derive.write_terms(tmp_path, "activity: retry a failed request")
    mapped, refused = derive.write_attachments(
        tmp_path, "app.py:4 parse_retry | retry a failed request"
    )

    assert not refused
    binding = mapped.attachments[0]
    assert binding.path == "app.py"
    assert binding.name == "parse_retry"
    assert binding.region and binding.region_hash


def test_bindings_on_one_definition_hash_its_region_once(tmp_path, monkeypatch):
    """Several terms commonly attach to the same definition, and each would
    otherwise re-read and re-hash the same file."""
    import vesta.derive as derive

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    (tmp_path / "app.py").write_text(
        '"""App."""\n\n\ndef parse_retry(spec):\n    """Read it."""\n    return spec\n',
        encoding="utf-8",
    )

    derive.write_terms(
        tmp_path, "activity: retry a failed request\nactivity: wait and try again"
    )
    mapped, _ = derive.write_attachments(
        tmp_path,
        "app.py:4 parse_retry | retry a failed request\n"
        "app.py:4 parse_retry | wait and try again",
    )

    assert len(mapped.attachments) == 2
    first, second = mapped.attachments
    assert first.region_hash == second.region_hash
    assert first.label != second.label


def test_more_definitions_are_offered_than_a_small_repository_has(tmp_path, monkeypatch):
    """The limit is a coverage ceiling, not a page size.

    It defaulted to 80, and on this repository that bound 79 of 646 definitions
    — seven in eight never offered, so never bound, so unreachable by any
    question asked in the vocabulary of the work. A miss like that looks exactly
    like a matcher that failed, which sends somebody to fix the wrong thing.
    """
    import inspect

    from vesta.derive import definitions_worth_reading

    default = inspect.signature(definitions_worth_reading).parameters["limit"].default
    assert default >= 400


def test_a_label_naming_no_term_is_refused_not_invented(tmp_path, monkeypatch):
    """A label the ontology does not have is a typo, not a new word.

    This used to invent a `loose:` term with an empty kind and carry on. The
    attachment then existed, pointed at real code, and was bound to a term
    nothing had heard of — so it answered nothing, `neighbours` could never
    match it, and nobody was told. Measured on this repository, an agent
    paraphrasing its own labels produced 51 of them in one pass, caught only by
    reading the stored JSON by hand.
    """
    import vesta.derive as derive

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    (tmp_path / "app.py").write_text(
        '"""App."""\n\n\ndef parse_retry(spec):\n    """Read it."""\n    return spec\n',
        encoding="utf-8",
    )

    derive.write_terms(tmp_path, "activity: retry a failed request")
    mapped, refused = derive.write_attachments(
        tmp_path, "app.py:4 parse_retry | retrying a failed request"
    )

    assert not mapped.attachments, "nothing bound to a term nobody named"
    assert refused and "no term is named" in refused[0]
    assert "retrying a failed request" in refused[0], "says which label was wrong"


def test_an_exact_label_still_attaches(tmp_path, monkeypatch):
    """The refusal must not be so strict that the ordinary case stops working."""
    import vesta.derive as derive

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    (tmp_path / "app.py").write_text(
        '"""App."""\n\n\ndef parse_retry(spec):\n    """Read it."""\n    return spec\n',
        encoding="utf-8",
    )

    derive.write_terms(tmp_path, "activity: retry a failed request")
    mapped, refused = derive.write_attachments(
        tmp_path, "app.py:4 parse_retry | retry a failed request"
    )

    assert not refused
    assert len(mapped.attachments) == 1
    assert mapped.attachments[0].kind == "activity", "a real term, not a loose one"


# ── A term's id is a function of what it says ───────────────────────────────


def test_a_term_id_comes_from_its_content_not_the_process():
    from vesta.derive import term_id

    first = read_terms("activity: resolving a reference")[0]
    again = read_terms("- activity:  resolving a   reference ")[0]
    assert first.id == again.id == term_id("activity", "resolving a reference")
    assert term_id("activity", "resolving a reference") == "activity:" + term_id("activity", "Resolving A Reference").split(":")[1]
    assert term_id("activity", "x") != term_id("role", "x")
    assert read_terms("activity: resolving a reference\nactivity: resolving a reference")[1].id == first.id


def test_rederiving_the_ontology_keeps_the_attachments_reachable(tmp_path, monkeypatch):
    """508 of 558 attachments pointed at ids no ontology would produce again."""
    from vesta.derive import write_attachments, write_terms
    from vesta.held import graph_for
    from vesta.traverse import recall as recall_map

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "store.py").write_text(
        '"""Keeping things, which is what a store is for and nothing else is."""\n\n\n'
        'def keep(item):\n    """Keep one."""\n    return item\n',
        encoding="utf-8",
    )
    graph_for(root, rebuild=True)
    write_terms(root, "activity: keeping an item\nactivity: a word nobody attaches")
    mapped, refused = write_attachments(root, "store.py:4 keep | keeping an item")
    assert not refused and len(mapped.attachments) == 1

    # The old world: a map written against ids that will never recur.
    stale = recall_map(root)
    stale.attachments[0].term = "activity:0-12345"
    from vesta.traverse import keep as keep_map
    keep_map(stale, root)

    # The author rephrases one term and re-derives; the attached one is kept.
    found = write_terms(root, "activity: keeping an item\nactivity: a word somebody rephrased")
    current = {t["id"] for t in found.terms}
    attached = recall_map(root).attachments[0]
    assert attached.term in current
    assert attached.label == "keeping an item"

    # And a term that is gone leaves its attachment as it was, not dropped.
    write_terms(root, "activity: something else entirely")
    left = recall_map(root).attachments
    assert len(left) == 1 and left[0].label == "keeping an item"


def test_a_label_carrying_its_kind_still_repoints(tmp_path, monkeypatch):
    """112 of 124 stale attachments on one project said "role: x" against a
    term labelled "x", and a verbatim match moved none of them."""
    from vesta.derive import bare_label, repoint, write_attachments, write_terms
    from vesta.domain import recall as recall_ontology
    from vesta.held import graph_for
    from vesta.traverse import keep as keep_map
    from vesta.traverse import recall as recall_map

    assert bare_label("role:  Graph Node   and edge") == "graph node and edge"
    assert bare_label("graph node and edge") == "graph node and edge"

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "store.py").write_text(
        '"""Keeping things, which is what a store is for and nothing else is."""\n\n\n'
        'def keep(item):\n    """Keep one."""\n    return item\n',
        encoding="utf-8",
    )
    graph_for(root, rebuild=True)
    write_terms(root, "role: keeping an item")
    write_attachments(root, "store.py:4 keep | keeping an item")
    stale = recall_map(root)
    stale.attachments[0].term = "role:0-99999"
    stale.attachments[0].label = "role: Keeping an item"
    keep_map(stale, root)

    assert repoint(root, recall_ontology(root)) == 1
    fixed = recall_map(root).attachments[0]
    assert fixed.term == recall_ontology(root).terms[0]["id"]
    assert fixed.label == "keeping an item" and fixed.kind == "role"
