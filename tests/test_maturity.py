"""Whether a build needs theory.

The property under test throughout is the asymmetry. Calling novel work settled
costs a lookup; calling settled work novel makes the system propose that a
working architecture be abandoned. Every test here checks the classifier fails
in the cheap direction.
"""

from __future__ import annotations

from vesta.maturity import (
    CLEAR,
    LIKELY,
    NEEDS_THEORY,
    SETTLED,
    UNCLEAR,
    UNDETERMINED,
    Aspect,
    judge,
    read,
)


def found(name: str, verdict: str = NEEDS_THEORY) -> Aspect:
    return Aspect(name=name, says="x", verdict=verdict, would_search=["q"])


# ── The default ──────────────────────────────────────────────────────────


def test_with_no_search_everything_is_settled():
    """A deployment that cannot check the literature should not be guessing at
    novelty. Silence is not discovery."""
    result = judge("build a system that deduplicates submissions by similarity")

    assert result.is_ordinary
    assert all(a.verdict == SETTLED for a in result.aspects)
    assert "No search is configured" in result.could_not_search


def test_an_ordinary_brief_reads_as_ordinary():
    result = judge("build a REST API with FastAPI and Postgres for storing users")

    assert result.is_ordinary
    assert "established work" in result.ask()


def test_nothing_found_settles_nothing():
    """A search returning nothing means the query was wrong or the field is
    unindexed. Treating it as evidence of novelty is how a classifier invents
    hard problems."""
    result = judge("build a scheduler", search=lambda q: [])

    for aspect in result.aspects:
        assert aspect.verdict == UNDETERMINED
        assert any("settles neither way" in b for b in aspect.because)


def test_a_failed_search_is_not_a_verdict():
    def broken(query):
        raise RuntimeError("the network is down")

    result = judge("build a consensus protocol", search=broken)

    assert result.is_ordinary, "a broken search must not produce a novelty claim"
    for aspect in result.aspects:
        assert aspect.verdict == UNDETERMINED


# ── Naming a tool is evidence for settledness ────────────────────────────


def test_naming_a_technology_counts_toward_settled():
    """A brief that says 'rate-limit with Redis' has already chosen, and the
    choice is the ordinary one. A classifier treating specificity as difficulty
    would flag every competent brief."""
    aspects = read("rate-limit the API with Redis and a token bucket")

    scheduling = [a for a in aspects if a.name == "scheduling"]
    assert scheduling
    assert any("already chosen" in b for b in scheduling[0].because)


def test_a_brief_matching_no_known_shape_is_undetermined_not_ordinary():
    """The table is eight shapes and the field is larger than eight shapes.

    Briefs for this project's own components — deriving ontology axioms,
    resolving references across languages — matched none of them, and both
    needed theory that cost real work to acquire late. An unmatched brief is
    therefore still searched, and the evidence decides rather than the table.
    """
    aspects = read("build a page that lists users and lets you edit them")

    assert len(aspects) == 1
    assert aspects[0].verdict == UNDETERMINED
    # Still searchable: an aspect nobody can look up cannot be corrected.
    assert aspects[0].would_search and aspects[0].would_search[0].strip()


def test_an_unmatched_brief_is_never_called_novel_on_its_own():
    """Undetermined is not a novelty claim, and must not become one unasked."""
    judged = judge("build a page that lists users and lets you edit them")

    assert not judged.needs_theory
    assert judged.is_ordinary


# ── Aspects, not whole briefs ────────────────────────────────────────────


def test_a_brief_is_judged_in_parts():
    """A brief is rarely uniformly hard. Judging the whole would lose that a
    settled web service can contain a non-trivial similarity problem."""
    aspects = read(
        "a web service that deduplicates submissions by semantic similarity "
        "and schedules them for review"
    )

    assert {a.name for a in aspects} >= {"search", "scheduling"}


# ── The output is a question ─────────────────────────────────────────────


def test_the_output_asks_rather_than_instructs():
    """A wrong answer that is visible costs a moment; one that acts costs a
    system."""
    result = judge("build a thing")
    result.aspects = [found("concurrency")]

    asked = result.ask()
    assert "Does that match how you see it" in asked
    assert "it will not be looked into" in asked


def test_disagreement_is_made_cheap():
    result = judge("build a thing")
    result.aspects = [found("consistency")]

    assert "say so" in result.ask()


def test_an_ordinary_verdict_still_invites_correction():
    """The classifier can be wrong in the cheap direction too, and a user who
    knows better should be able to say so without being asked."""
    assert "disagree" in judge("build a CRUD app").ask()


def test_what_would_be_searched_is_inspectable_before_it_is_paid_for():
    aspects = read("build a consensus protocol for replicated state")

    assert aspects
    assert all(a.would_search for a in aspects)


# ── Reporting ────────────────────────────────────────────────────────────


def test_a_judgement_says_how_much_it_could_not_establish():
    result = judge("build a distributed cache with quorum reads")

    assert result.could_not_search
    assert result.could_not_search in result.ask()


def test_every_verdict_carries_its_reasons():
    """A judgement a user cannot check is one they have to take on faith."""
    result = judge("build a scheduler with backpressure")

    assert result.aspects
    assert all(a.because for a in result.aspects)
