"""Fetching documents, and refusing the ones that are about something else.

Both behaviours here were specified by a real failure. An agent asked for
IPOG's horizontal/vertical growth procedure and got 418 bytes of search
snippet; the same corpus had ingested a paper about measuring impact on Twitter
because it shared the token "t-factor".
"""

from __future__ import annotations

import urllib.error

import pytest

from vesta.acquire import ARXIV, WEB, Reading
from vesta.fetch import (
    ENOUGH_OVERLAP,
    LEAST_USEFUL,
    Fetched,
    gather,
    relevance,
    summarise,
)

SUBJECT = "implement a t-way covering array generator with guaranteed coverage"

ON_TOPIC = (
    "IPOG generates a t-way covering array. Horizontal growth extends each "
    "existing test by adding one value for the new parameter; vertical growth "
    "adds tests to cover the remaining combinations of parameter values. The "
    "algorithm guarantees full t-way coverage of every parameter combination. "
) * 12

OFF_TOPIC = (
    "T-Factor is a metric for measuring the impact of a user on Twitter, based "
    "on followers, retweets and mentions across timelines and hashtags. Social "
    "influence is estimated from the follower graph. "
) * 12


def reading(url: str = "http://x/1", title: str = "A paper") -> Reading:
    return Reading(title=title, url=url, source=WEB, summary="a snippet")


# ── Relevance ────────────────────────────────────────────────────────────


def test_a_paper_about_the_subject_is_relevant():
    assert relevance(ON_TOPIC, SUBJECT) > ENOUGH_OVERLAP


def test_a_paper_sharing_one_token_is_not():
    """The Twitter paper. It shares "t-factor"-ish surface and nothing else."""
    assert relevance(OFF_TOPIC, SUBJECT) < ENOUGH_OVERLAP


def test_relevance_is_computed_over_the_body_not_the_snippet():
    """The distinction is invisible in forty words and obvious in a document:
    a real paper repeats the subject's vocabulary throughout."""
    snippet = "A general strategy for t-way software testing"

    assert relevance(ON_TOPIC, SUBJECT) > relevance(snippet, SUBJECT)


def test_an_empty_subject_admits_everything():
    """No subject is not a reason to reject a document."""
    assert relevance(OFF_TOPIC, "") == 1.0


# ── Gathering ────────────────────────────────────────────────────────────


def gathering(monkeypatch, bodies: dict):
    def fake_document(url, timeout=0):
        if url not in bodies:
            raise urllib.error.URLError("no such host")
        return bodies[url]

    monkeypatch.setattr("vesta.fetch.document", fake_document)


def test_a_relevant_document_is_kept(monkeypatch):
    gathering(monkeypatch, {"http://a": ON_TOPIC})
    got = gather([reading("http://a")], SUBJECT)

    assert got[0].kept
    assert "horizontal growth" in got[0].text.lower()


def test_an_irrelevant_document_is_dropped_with_a_reason(monkeypatch):
    gathering(monkeypatch, {"http://a": OFF_TOPIC})
    got = gather([reading("http://a", "T-Factor on Twitter")], SUBJECT)

    assert not got[0].kept
    assert "about something else" in got[0].dropped


def test_a_paywall_is_not_mistaken_for_a_document(monkeypatch):
    """A short body is an access page, not the paper. Ingesting it would put
    the same abstract-level material back in the corpus."""
    gathering(monkeypatch, {"http://a": "Sign in to continue reading."})
    got = gather([reading("http://a")], SUBJECT)

    assert not got[0].kept
    assert "no readable body" in got[0].dropped


def test_an_unreachable_document_is_reported_not_silently_missing(monkeypatch):
    gathering(monkeypatch, {})
    got = gather([reading("http://nowhere")], SUBJECT)

    assert not got[0].kept
    assert "could not be fetched" in got[0].dropped


def test_every_reading_is_accounted_for(monkeypatch):
    """A build that ingests ten of sixteen looks identical to one that found
    ten, unless the six are named."""
    gathering(monkeypatch, {"http://a": ON_TOPIC, "http://b": OFF_TOPIC})
    got = gather(
        [reading("http://a"), reading("http://b"), reading("http://gone")], SUBJECT
    )

    assert len(got) == 3
    assert sum(1 for g in got if g.kept) == 1
    assert all(g.kept or g.dropped for g in got)


def test_the_summary_names_what_was_dropped(monkeypatch):
    gathering(monkeypatch, {"http://a": ON_TOPIC, "http://b": OFF_TOPIC})
    said = summarise(gather([reading("http://a"), reading("http://b", "Twitter")], SUBJECT))

    assert "1 of 2" in said
    assert "Twitter" in said
