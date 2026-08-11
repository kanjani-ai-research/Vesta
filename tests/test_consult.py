"""Consulting what was already acquired.

The half that closes the loop. Without it the system searches the web every
time and the theory it acquired last week is a folder nobody opens.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from vesta.consult import LOCAL, PUBLISHED, Consultation, consult, corpus_for, known, origin_of
from vesta.structure import Answer


class Corpus:
    """A backend holding one canned answer."""

    def __init__(self, results=None, coverage=None, can_read=True, raises=None):
        self.base_url = "fake"
        self._results = results if results is not None else []
        self._coverage = coverage if coverage is not None else {"gap": None}
        self.can_read = can_read
        self.is_available = can_read
        self._raises = raises
        self.asked: List[str] = []

    def ask(self, corpus_id, query, limit=10):
        self.asked.append(query)
        if self._raises:
            raise self._raises
        return Answer(query=query, results=self._results, coverage=self._coverage)


def passage(text: str, score: float = 1.0) -> dict:
    return {"text": text, "score": score, "source_id": "s1", "fact_id": "f1"}


def test_the_corpus_name_matches_what_acquisition_would_have_written():
    """One definition, used by both sides: a naming rule implemented twice
    agrees only until one copy changes."""
    from vesta.structure import corpus_id

    intent = "derive ontology axioms conservative extensions"
    assert corpus_for(intent) == corpus_id(intent)


def test_a_local_corpus_and_a_published_one_do_not_share_a_name():
    """The whole point of the namespace. A corpus this machine scraped and one
    somebody put their name to are different evidence about the same subject,
    and a user must be able to tell which answered."""
    intent = "conservative extensions"
    mine = corpus_for(intent)
    theirs = corpus_for(intent, origin=PUBLISHED, publisher="causum")

    assert mine != theirs
    assert origin_of(mine) == LOCAL
    assert origin_of(theirs) == PUBLISHED
    assert "causum" in theirs


def test_a_published_corpus_without_a_publisher_says_it_is_unattributed():
    """"Governed" is a claim somebody makes; an unattributable one is worth
    less and should not be able to hide that."""
    assert "unattributed" in corpus_for("x", origin=PUBLISHED)


def test_an_unnamespaced_id_reads_as_local():
    """Ids written down before the namespace existed still resolve, and resolve
    to the weaker claim rather than the stronger one."""
    assert origin_of("theory-conservative-extensions") == LOCAL


def test_a_corpus_that_answers_is_reported_as_knowing():
    found = consult(
        "how do I know an extension is conservative",
        corpus_id="c",
        pragmatos=Corpus([passage("If the extension is not conservative...", 1.4)]),
    )

    assert found.knew
    assert found.best == pytest.approx(1.4)
    assert "conservative" in found.cites[0].text


def test_a_corpus_with_nothing_says_so_rather_than_guessing():
    found = consult("anything", corpus_id="c", pragmatos=Corpus([]))

    assert not found.knew
    assert not found.unavailable  # asked and empty, not unreachable
    assert "has nothing" in found.describe()


def test_a_gap_means_the_corpus_did_not_cover_it():
    found = consult(
        "what is the best pizza",
        corpus_id="c",
        pragmatos=Corpus([passage("something")], coverage={"gap": {"id": "g1"}}),
    )

    assert not found.knew


def test_an_unreachable_corpus_is_not_an_empty_one():
    """Conflating them is how a system searches the web because a file was
    missing."""
    found = consult("anything", corpus_id="c", pragmatos=Corpus(can_read=False))

    assert not found.knew
    assert found.unavailable
    assert "could not consult" in found.describe()


def test_a_failing_query_is_reported_not_swallowed():
    found = consult(
        "anything", corpus_id="c", pragmatos=Corpus(raises=RuntimeError("db is locked"))
    )

    assert not found.knew
    assert "db is locked" in found.unavailable


def test_reading_does_not_require_credentials_to_build():
    """A corpus is SQLite. Requiring model credentials to *read* one made
    consulting acquired theory report "no corpus backend" on a machine holding
    a perfectly good corpus."""
    from vesta.structure import Local

    local = Local()
    if not local.can_read:
        pytest.skip("pragmatos is not installed")
    # can_read is the weaker gate and must not depend on the stronger one.
    assert local.can_read or not local.is_available


def test_the_score_is_reported_rather_than_thresholded():
    """An off-topic question can still match on surface similarity. The reader
    is better placed to judge that than a constant in this file."""
    weak = consult("unrelated", corpus_id="c", pragmatos=Corpus([passage("x", 0.7)]))

    assert weak.knew  # a retrieval happened and is not hidden
    assert "0.70" in weak.describe()


def test_several_questions_share_one_backend():
    corpus = Corpus([passage("y", 1.1)])
    found = known(["a", "b", "c"], corpus_id="c", pragmatos=corpus)

    assert len(found) == 3
    assert corpus.asked == ["a", "b", "c"]
