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
    # Acquired here, so it says so: nothing this machine scraped may look
    # like something a publisher stood behind.
    # Keyed by repository, not by intent.
    assert result.corpus_id.startswith("theory.local.")


def test_one_repository_is_one_knowledge_base(tmp_path: Path):
    """Two tasks in one project accumulate into one KB.

    Keying by task would give a project a scatter of single-purpose corpora
    that never accumulate: theory acquired for one piece of work would be
    invisible to the next, which is the opposite of the point.
    """
    repo = tmp_path / "one-project"
    repo.mkdir()
    a = structure(found(reading()), "rank documents", tmp_path / "a", pragmatos=Fake(), repo=repo)
    b = structure(found(reading()), "schedule work", tmp_path / "b", pragmatos=Fake(), repo=repo)

    assert a.corpus_id == b.corpus_id


def test_two_repositories_do_not_share_a_knowledge_base(tmp_path: Path):
    """Theory acquired for a compiler is not evidence about a payments
    service, and a query reaching across projects retrieves on surface
    similarity alone."""
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(); two.mkdir()
    a = structure(found(reading()), "x", tmp_path / "a", pragmatos=Fake(), repo=one)
    b = structure(found(reading()), "x", tmp_path / "b", pragmatos=Fake(), repo=two)

    assert a.corpus_id != b.corpus_id


def test_the_same_project_by_two_paths_is_one_knowledge_base(tmp_path: Path):
    """A live client returned both `/private/tmp/x` and `/tmp/x` for one
    directory. Treating those as two projects would split a KB in half."""
    from vesta.structure import corpus_id

    repo = tmp_path / "project"
    repo.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(repo)
    except OSError:
        pytest.skip("symlinks are not available here")

    assert corpus_id(repo) == corpus_id(link)


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


def test_an_empty_matched_facts_does_not_reject_a_real_answer():
    """`matched_facts` is empty for good retrievals too.

    A rule requiring one was tried and removed: live, "how do I know an
    extension is conservative" returned the right passage with
    `matched_facts: []`, so the rule rejected the questions the corpus answers
    best. It suppressed one bad case by suppressing the good ones with it.
    """
    answer = Answer(
        query="how do I know an extension is conservative",
        results=[{"id": "1", "score": 1.4}],
        coverage={"gap": None, "answered": True, "matched_facts": []},
    )

    assert answer.answered


def test_a_gap_still_means_the_corpus_did_not_cover_it():
    """What Pragmatos does judge reliably is carried through unchanged."""
    answer = Answer(
        query="what is the best pizza in chicago",
        results=[{"id": "1"}],
        coverage={"gap": {"id": "g1", "why": "no fact addresses this"}},
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


# ── Knowledge bases that predate the current naming ──────────────────────


def a_store(tmp_path: Path, *corpus_ids: str) -> Path:
    """A store shaped like Pragmatos', with rows in every keyed table."""
    import sqlite3

    path = tmp_path / "pragmatos.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE corpora (id TEXT PRIMARY KEY, title TEXT)")
    for table in ("sources", "chunks", "labels", "embeddings", "gaps", "variants", "bindings"):
        db.execute(f"CREATE TABLE {table} (corpus TEXT, payload TEXT)")
    for name in corpus_ids:
        db.execute("INSERT INTO corpora VALUES (?, ?)", (name, "t"))
        for table in ("sources", "chunks", "labels", "embeddings", "gaps", "variants", "bindings"):
            db.execute(f"INSERT INTO {table} VALUES (?, ?)", (name, "x"))
    db.commit()
    db.close()
    return path


def rows_for(path: Path, corpus: str) -> int:
    import sqlite3

    db = sqlite3.connect(path)
    total = sum(
        db.execute(f"SELECT count(*) FROM {t} WHERE corpus = ?", (corpus,)).fetchone()[0]
        for t in ("sources", "chunks", "labels", "embeddings", "gaps", "variants", "bindings")
    )
    db.close()
    return total


def test_a_rename_moves_every_table(tmp_path: Path):
    """The schema cascades on delete but enforcement is off, so a partial
    rename detaches rows silently rather than failing."""
    from vesta.structure import rename_corpus

    store = a_store(tmp_path, "theory.local.old-name")

    assert rename_corpus("theory.local.old-name", "theory.local.new-abcd1234", store)
    assert rows_for(store, "theory.local.old-name") == 0
    assert rows_for(store, "theory.local.new-abcd1234") == 7


def test_a_rename_onto_an_existing_corpus_is_refused(tmp_path: Path):
    """Two knowledge bases claiming one name is worse than one misnamed: a
    merge would mix material with no way to tell them apart afterwards."""
    from vesta.structure import rename_corpus

    store = a_store(tmp_path, "theory.local.old", "theory.local.taken-abcd1234")

    assert not rename_corpus("theory.local.old", "theory.local.taken-abcd1234", store)
    assert rows_for(store, "theory.local.old") == 7


def test_an_orphan_is_adopted_by_a_repository_with_none(tmp_path: Path):
    """Rebuilding would re-spend a user's money on reading they already paid
    for."""
    from vesta.structure import adopt, corpus_id

    repo = tmp_path / "project"
    repo.mkdir()
    store = a_store(tmp_path, "theory.local.some-old-intent-name")

    assert adopt(repo, store)
    assert rows_for(store, corpus_id(repo)) == 7


def test_two_orphans_are_left_alone(tmp_path: Path):
    """Guessing which belongs to this project would be worse than saying so."""
    from vesta.structure import adopt

    repo = tmp_path / "project"
    repo.mkdir()
    store = a_store(tmp_path, "theory.local.one-intent", "theory.local.another-intent")

    assert not adopt(repo, store)


def test_a_repository_with_its_own_kb_adopts_nothing(tmp_path: Path):
    from vesta.structure import adopt, corpus_id

    repo = tmp_path / "project"
    repo.mkdir()
    store = a_store(tmp_path, corpus_id(repo), "theory.local.an-orphan")

    assert not adopt(repo, store)


def test_a_current_name_is_not_mistaken_for_an_orphan(tmp_path: Path):
    from vesta.structure import _is_current_scheme

    assert _is_current_scheme("theory.local.vesta-20bb90f3")
    assert _is_current_scheme("theory.pub.causum.thing-0f26fad7")
    assert not _is_current_scheme("theory.local.implement-a-t-way-covering-array")
    assert not _is_current_scheme("theory-conservative-extensions")


def test_the_local_backend_is_held_not_rebuilt():
    """It caches the embedding encoder, and rebuilding per call threw that
    cache away: a warm consultation reloaded model weights and took 3.5s
    where it should take a fraction of that."""
    from vesta.structure import Local, best_backend

    first = best_backend(for_reading=True)
    if not isinstance(first, Local):
        pytest.skip("pragmatos is not installed")

    assert best_backend(for_reading=True) is first
