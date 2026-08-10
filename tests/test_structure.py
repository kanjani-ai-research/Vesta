"""Structuring, exercised without Pragmatos running.

What is worth testing is what happens when the service is absent, when the
build fails, and when a corpus does not cover a question — because each of
those can be reported as success by a client that is not careful, and each is a
claim about knowledge the system does not have.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from vesta.acquire import ARXIV, WEB, Found, Reach, Reading
from vesta.structure import Answer, Pragmatos, Structured, structure, write


def found(*readings: Reading, skipped: dict = None, asked: list = None) -> Found:
    return Found(
        readings=list(readings),
        reach=Reach(query="q", asked=asked or [ARXIV], skipped=skipped or {}),
    )


def reading(title: str = "Paxos Made Simple", url: str = "http://a/1") -> Reading:
    return Reading(
        title=title, url=url, source=ARXIV, summary="A consensus protocol.",
        published="2001-01-01", authors=["L Lamport"],
    )


class Fake(Pragmatos):
    """A Pragmatos that is there, or is not, on demand."""

    def __init__(self, available=True, job=None, answer=None, raises=None):
        super().__init__("http://fake")
        self._available = available
        self._job = job or {"state": "complete", "id": "j1"}
        self._answer = answer or {"results": [], "coverage": {}}
        self._raises = raises
        self.built = []

    @property
    def is_available(self):
        return self._available

    def build(self, corpus_id, paths, ontology=None, wait=0):
        if self._raises:
            raise self._raises
        self.built.append((corpus_id, [str(p) for p in paths], ontology))
        return self._job

    def ask(self, corpus_id, query, limit=10):
        return Answer(query=query, **self._answer)


# ── Writing ──────────────────────────────────────────────────────────────


def test_a_reading_is_written_with_its_provenance(tmp_path: Path):
    written = write(found(reading()), tmp_path, query="consensus")

    body = written[0].read_text()
    # The source has to survive into the file: whatever reads the corpus will
    # not have the object the reading came from.
    assert "http://a/1" in body
    assert "arxiv" in body
    assert "L Lamport" in body


def test_what_was_not_searched_is_written_beside_the_readings(tmp_path: Path):
    where = found(reading(), skipped={WEB: "no BRAVE_API_KEY"})
    where.reach.query = "consensus protocols"
    write(where, tmp_path, query="the intent, which is not the query")

    # Beside the readings, not inside them: it is provenance, not material.
    reach = (tmp_path.parent / f"{tmp_path.name}-reach.md").read_text()
    assert "no BRAVE_API_KEY" in reach
    # The query actually sent to the sources, not the intent it came from —
    # they differ, and only the former explains what came back.
    assert "consensus protocols" in reach


def test_two_readings_with_the_same_title_do_not_collide(tmp_path: Path):
    written = write(
        found(reading(url="http://a/1"), reading(url="http://a/2")), tmp_path
    )

    assert len(written) == 2
    assert len({p.name for p in written}) == 2


# ── Building ─────────────────────────────────────────────────────────────


def test_an_absent_pragmatos_is_reported_not_swallowed(tmp_path: Path):
    result = structure(found(reading()), "consensus", tmp_path, pragmatos=Fake(available=False))

    assert not result.is_whole
    assert "not reachable" in result.incomplete
    # The readings still exist and a person can still read them.
    assert result.wrote
    assert (tmp_path / result.wrote[0].split("/")[-1]).exists()


def test_a_failed_build_is_reported(tmp_path: Path):
    result = structure(
        found(reading()),
        "consensus",
        tmp_path,
        pragmatos=Fake(job={"state": "failed", "error": "no credentials"}),
    )

    assert not result.is_whole
    assert "no credentials" in result.incomplete


def test_a_build_that_will_not_start_is_reported(tmp_path: Path):
    result = structure(
        found(reading()),
        "consensus",
        tmp_path,
        pragmatos=Fake(raises=urllib.error.URLError("connection refused")),
    )

    assert not result.is_whole
    assert "could not be started" in result.incomplete


def test_nothing_found_builds_no_corpus(tmp_path: Path):
    fake = Fake()
    result = structure(found(), "consensus", tmp_path, pragmatos=fake)

    assert not result.is_whole
    assert not fake.built  # never asked Pragmatos to build an empty corpus


def test_a_complete_build_is_whole(tmp_path: Path):
    fake = Fake()
    result = structure(found(reading()), "rank documents", tmp_path, pragmatos=fake)

    assert result.is_whole
    assert fake.built
    assert result.corpus_id == "theory-rank-documents"


def test_theory_for_one_intent_is_its_own_corpus(tmp_path: Path):
    """Paper abstracts and source files in one corpus answer each other's
    queries. They are kept apart."""
    a = structure(found(reading()), "rank documents", tmp_path / "a", pragmatos=Fake())
    b = structure(found(reading()), "schedule work", tmp_path / "b", pragmatos=Fake())

    assert a.corpus_id != b.corpus_id


# ── Asking ───────────────────────────────────────────────────────────────


def test_results_without_coverage_are_not_an_answer():
    """The failure this carries Pragmatos' judgement through to avoid.

    A ranked list always has a first element. Reading its presence as success
    is how a corpus that covers nothing appears to cover everything.
    """
    answer = Answer(
        query="how do I rank",
        results=[{"id": "1"}],
        coverage={"gap": {"id": "g1", "why": "no fact addresses this"}},
    )

    assert not answer.answered
    assert "does not cover" in answer.describe()


def test_coverage_without_results_is_not_an_answer_either():
    assert not Answer(query="q", results=[], coverage={}).answered


def test_a_covered_query_with_results_answered():
    assert Answer(
        query="q", results=[{"id": "1"}],
        coverage={"gap": None, "matched_facts": ["f1"]},
    ).answered


def test_results_grounded_in_no_fact_are_not_an_answer():
    """Live: "how should I price a used car" against description-logic papers
    came back answered=true, gap=null, matched_facts=[] — three lexical hits on
    common words. A retrieval grounded in no fact is a text match."""
    answer = Answer(
        query="how should I price a used car",
        results=[{"id": "1"}, {"id": "2"}],
        coverage={"gap": None, "answered": True, "matched_facts": []},
    )

    assert not answer.answered


def test_a_record_without_the_field_is_not_treated_as_empty():
    """Absence predates the field; it is not evidence of no match."""
    assert Answer(query="q", results=[{"id": "1"}], coverage={"gap": None}).answered


def test_a_build_without_embeddings_is_not_reported_as_whole(tmp_path: Path):
    """Built, and not built the way it was asked for.

    Pragmatos falls back to lexical retrieval when sentence-transformers is
    absent — deliberate on its side, and still a bound on the corpus. A live
    build wrote 108 labels and zero vectors while reporting success.
    """
    result = structure(
        found(reading()),
        "consensus",
        tmp_path,
        pragmatos=Fake(job={"state": "complete", "partial": "no embeddings were written"}),
    )

    assert not result.is_whole
    assert "no embeddings" in result.incomplete
