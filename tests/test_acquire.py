"""Acquisition, exercised without a network.

The sources themselves are thin wrappers over HTTP; what is worth testing is
what happens when one of them is missing, failing, or empty — because those are
the paths where a search quietly becomes evidence it is not.
"""

from __future__ import annotations

import urllib.error

import pytest

from vesta import acquire, maturity
from vesta.acquire import ARXIV, REPOSITORY, WEB, Reading, Search


def reading(title: str, url: str, source: str = ARXIV) -> Reading:
    return Reading(title=title, url=url, source=source)


def test_a_search_without_a_key_skips_the_web_and_says_so():
    search = Search.from_environment({})
    found = search.for_("consensus")

    assert WEB in found.reach.skipped
    assert acquire.BRAVE_KEY in found.reach.skipped[WEB]
    assert not found.reach.is_complete


def test_a_search_without_a_key_still_runs_the_free_sources():
    search = Search(
        fetch={
            ARXIV: lambda q, limit=8: [reading("Paxos", "http://a/1")],
            REPOSITORY: lambda q, limit=8: [reading("etcd", "http://g/1", REPOSITORY)],
        }
    )
    found = search.for_("consensus")

    assert len(found) == 2
    assert found.reach.asked == [ARXIV, REPOSITORY]


def test_a_failing_source_does_not_fail_the_search():
    def broken(query, limit=8):
        raise urllib.error.URLError("no route to host")

    search = Search(
        brave_key="k",
        fetch={
            ARXIV: broken,
            WEB: lambda q, limit=8: [reading("A blog", "http://b/1", WEB)],
            REPOSITORY: lambda q, limit=8: [],
        },
    )
    found = search.for_("byzantine")

    # The reachable source's result survives, and the unreachable one is named
    # rather than silently absent.
    assert len(found) == 1
    assert ARXIV in found.reach.skipped
    assert "no route to host" in found.reach.skipped[ARXIV]
    assert WEB in found.reach.asked


def test_the_same_url_from_two_sources_is_one_reading():
    search = Search(
        brave_key="k",
        fetch={
            ARXIV: lambda q, limit=8: [reading("Raft", "http://x/raft")],
            WEB: lambda q, limit=8: [reading("Raft", "http://x/raft/", WEB)],
            REPOSITORY: lambda q, limit=8: [],
        },
    )
    found = search.for_("raft")

    assert len(found) == 1
    # The first source to find it keeps the attribution: it is what was
    # actually consulted first, and inventing a merged provenance would claim
    # a comparison across sources that nothing supports.
    assert found.readings[0].source == ARXIV


def test_a_reading_carries_which_source_found_it():
    search = Search(
        brave_key="k",
        fetch={
            ARXIV: lambda q, limit=8: [reading("Paper", "http://a/1")],
            WEB: lambda q, limit=8: [reading("Post", "http://b/1", WEB)],
            REPOSITORY: lambda q, limit=8: [reading("Repo", "http://g/1", REPOSITORY)],
        },
    )
    by_source = search.for_("anything").by_source()

    assert set(by_source) == {ARXIV, WEB, REPOSITORY}


def test_nothing_found_leaves_an_aspect_undetermined_not_novel():
    """The failure this whole module is shaped to avoid.

    An empty result is evidence about the query or the index, never about the
    problem. A classifier reading silence as discovery invents hard problems.
    """
    empty = Search(
        brave_key="k",
        fetch={ARXIV: lambda q, limit=8: [], WEB: lambda q, limit=8: [], REPOSITORY: lambda q, limit=8: []},
    )
    judged = maturity.judge("rank documents by relevance", search=empty)

    assert judged.aspects
    for aspect in judged.aspects:
        assert aspect.verdict == maturity.UNDETERMINED
    assert not judged.needs_theory


def test_a_search_missing_the_web_bounds_the_judgement():
    keyless = Search(
        brave_key="",
        fetch={
            ARXIV: lambda q, limit=8: [reading("Paper", "http://a/1")],
            REPOSITORY: lambda q, limit=8: [],
        },
    )
    judged = maturity.judge("schedule work under backpressure", search=keyless)

    assert acquire.BRAVE_KEY in judged.could_not_search
    assert judged.could_not_search in judged.ask()


def test_a_complete_search_bounds_nothing():
    full = Search(
        brave_key="k",
        fetch={
            ARXIV: lambda q, limit=8: [reading("Paper", "http://a/1")],
            WEB: lambda q, limit=8: [reading("Post", "http://b/1", WEB)],
            REPOSITORY: lambda q, limit=8: [reading("Repo", "http://g/1", REPOSITORY)],
        },
    )
    judged = maturity.judge("schedule work under backpressure", search=full)

    assert judged.could_not_search == ""


def test_a_source_that_raises_is_reported_per_query_not_remembered():
    """A rate limit on one query says nothing about the next one."""
    calls = {"n": 0}

    def sometimes(query, limit=8):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError("u", 403, "rate limited", {}, None)
        return [reading("Later", "http://a/2")]

    search = Search(fetch={ARXIV: sometimes})

    assert ARXIV in search.for_("first").reach.skipped
    assert len(search.for_("second")) == 1


# ── The one route to NEEDS_THEORY ────────────────────────────────────────


def dated(year: int, n: int = 1) -> list:
    return [
        Reading(title=f"P{year}-{i}", url=f"http://a/{year}/{i}", source=ARXIV,
                published=f"{year}-01-01")
        for i in range(n)
    ]


def searching(readings: list) -> Search:
    return Search(
        brave_key="k",
        fetch={
            ARXIV: lambda q, limit=8: list(readings),
            WEB: lambda q, limit=8: [],
            REPOSITORY: lambda q, limit=8: [],
        },
    )


def test_a_literature_that_is_entirely_recent_may_need_theory():
    """Where the older work that would have settled a question does not exist."""
    judged = maturity.judge(
        "rank documents by relevance",
        search=searching(dated(2024, 3) + dated(2025, 3)),
    )

    assert judged.needs_theory
    assert "2024" in " ".join(judged.needs_theory[0].because)


def test_a_field_with_old_work_is_settled_however_much_recent_work_it_has():
    """The failure mode that matters: an active field is not an open question.

    Consensus has papers from this year and papers from the eighties. A
    classifier reading the recent ones as novelty would propose redesigning
    around a solved problem.
    """
    judged = maturity.judge(
        "replicate state with consensus",
        search=searching(dated(2025, 5) + dated(1985, 1)),
    )

    assert not judged.needs_theory
    assert all(a.verdict == maturity.SETTLED for a in judged.aspects)


def test_too_few_dated_results_will_not_carry_a_novelty_claim():
    judged = maturity.judge(
        "rank documents by relevance", search=searching(dated(2025, 3))
    )

    assert not judged.needs_theory


def test_undated_results_will_not_carry_a_novelty_claim():
    """A blog post has no date. Absence of a date is not evidence of recency."""
    undated = [
        Reading(title=f"Post {i}", url=f"http://b/{i}", source=WEB) for i in range(6)
    ]
    judged = maturity.judge(
        "rank documents by relevance", search=searching(dated(2025, 4) + undated)
    )

    assert not judged.needs_theory


def test_a_novelty_finding_is_still_phrased_as_a_question():
    judged = maturity.judge(
        "rank documents by relevance", search=searching(dated(2024, 3) + dated(2025, 3))
    )
    asked = judged.ask()

    assert "may need" in asked
    assert "?" in asked
    # Never an instruction, and never a licence to redesign anything.
    for word in ("must", "should redesign", "rewrite", "replace the"):
        assert word not in asked.lower()
