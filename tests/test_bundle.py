"""A witness: one invocation, one output, and whether the way there was sound.

The witness is not the chain. It is a verdict on the chain, taken while the
chain is in hand and kept instead of it — so the tests that matter are the ones
where a chain that looks fine is not, and where a check that always passes would
be worthless.

An earlier version stored every judgement so somebody could work it out later:
712 records, 303kb, of which 681 said the same sentence. Nobody asks why one
particular definition was not the answer.
"""

from __future__ import annotations

import time

import pytest

from vesta.bundle import (
    KEEP,
    SANE,
    UNKNOWN,
    UNSOUND,
    Witness,
    judge,
    keep,
    keep_chain,
    recent,
    witness,
)
from vesta.graph import Graph, Node
from vesta.space import Basis, Verdict
from vesta.space import Witness as Judgement
from vesta.warrant import Convergence, Intervention, Step


def chain(*steps: Step) -> Convergence:
    return Convergence(action="make retries configurable", steps=list(steps))


def judged(verdict: Verdict, basis: Basis, name: str = "x", about: str = "") -> Judgement:
    return Judgement(
        verdict=verdict, basis=basis, path="a.py", name=name, about=about, reason="because"
    )


# ── Whether the chain was sane ──────────────────────────────────────────────


def test_a_chain_that_contracted_and_explained_itself_is_sound(tmp_path):
    trail = chain(
        Step(sites=100, population=100),
        Step(
            sites=98,
            population=100,
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, "a"),
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, "b"),
            ],
        ),
    )

    held = witness("make retries configurable", trail, tmp_path, output="do it here")

    assert held.verdict == SANE
    assert held.sound
    assert all(f.held for f in held.findings)


def test_candidates_that_vanish_unexplained_are_caught(tmp_path):
    """The failure this whole record exists to prevent.

    A set that got smaller for reasons nobody can name is not a decision — it is
    an accident that happened to narrow, and it reads identically to one.
    """
    trail = chain(Step(sites=100, population=100), Step(sites=4, population=100))

    held = witness("x", trail, tmp_path, output="an answer")

    assert held.verdict == UNSOUND
    failed = [f for f in held.findings if not f.held]
    assert any("accounted for" in f.check for f in failed)


def test_a_pooled_verdict_that_closed_the_space_is_caught(tmp_path):
    """The strongest available check on the part that cannot be re-verified.

    An evaluated judgement may demote but never exclude, because it is never
    certain enough to close a space — and whether a run honoured that is a
    structural fact, checkable even though the verdicts themselves are not.
    """
    trail = chain(
        Step(sites=100, population=100),
        Step(
            sites=99,
            population=100,
            witness=[judged(Verdict.SOUND_PRUNE, Basis.EVALUATED)],
        ),
    )

    held = witness("x", trail, tmp_path, output="an answer")

    assert held.verdict == UNSOUND
    assert any(
        "no pooled verdict closed the space" in f.check
        for f in held.findings
        if not f.held
    )


def test_a_space_that_never_contracted_is_not_sound(tmp_path):
    """One step is not a decision, however confident the output."""
    trail = chain(Step(sites=100, population=100))

    held = witness("x", trail, tmp_path, output="an answer")

    assert held.verdict == UNSOUND
    assert any("contracted" in f.check for f in held.findings if not f.held)


def test_an_output_resting_on_nothing_is_caught(tmp_path):
    """A conclusion drawn from an empty space came from outside the chain —
    the shape of an answer decided elsewhere and narrated afterwards."""
    trail = chain(
        Step(sites=100, population=100),
        Step(
            sites=0,
            population=100,
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(100)
            ],
        ),
    )

    held = witness("x", trail, tmp_path, output="an answer anyway")

    assert held.verdict == UNSOUND
    assert any(
        "rests on what survived" in f.check for f in held.findings if not f.held
    )


def test_something_excluded_coming_back_is_caught(tmp_path):
    """A sound prune is certain and this pass does not reopen it. Something
    returning means the exclusion was wrong or the space was rebuilt from
    elsewhere, and a reader needs to know which."""
    trail = chain(
        Step(sites=2, population=2),
        Step(
            sites=1,
            population=2,
            witness=[judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, about="n1")],
        ),
        Step(sites=2, population=2, admissible=["n1"]),
    )

    held = witness("x", trail, tmp_path, output="an answer")

    assert any("came back" in f.check for f in held.findings if not f.held)


def test_a_chain_with_no_steps_is_not_judged(tmp_path):
    """Nothing to judge is a third answer. Calling it sound would vouch for
    reasoning that never happened."""
    held = witness("x", chain(), tmp_path, output="an answer")

    assert held.verdict == UNKNOWN
    assert not held.sound
    assert "nothing to judge" in held.describe()


# ── What the witness carries, and what it does not ──────────────────────────


def test_progress_is_kept_as_numbers_not_records(tmp_path):
    """`746 → 34 → 18 → 1` is the progress a reader checks, and it is four
    integers rather than seven hundred records."""
    trail = chain(
        Step(sites=100, population=100),
        Step(
            sites=20,
            population=100,
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(80)
            ],
        ),
    )

    held = witness("x", trail, tmp_path, output="here")

    assert held.narrowed == [100, 20]
    assert held.ruled_out == 80


def test_a_witness_stays_small(tmp_path, monkeypatch):
    """Small by construction rather than by compression.

    Storing the reasoning instead came to 303kb for a single invocation, which
    is a record nobody keeps — and a trail nobody keeps answers nothing.
    """
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    trail = chain(
        Step(sites=900, population=900),
        Step(
            sites=12,
            population=900,
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(888)
            ],
        ),
    )

    path = keep(witness("x", trail, tmp_path / "proj", output="here"), tmp_path / "proj")

    assert path.stat().st_size < 60_000


def test_where_the_reasoning_came_from_is_counted(tmp_path):
    """The question is what share rested on judgement, not which judgements."""
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=7,
            population=10,
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, "a"),
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, "b"),
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, "c"),
                Judgement(
                    verdict=Verdict.DEMOTE,
                    basis=Basis.EVALUATED,
                    path="a.py",
                    name="d",
                    authority="retry-policy",
                ),
            ],
        ),
    )

    held = witness("x", trail, tmp_path, output="here")

    assert held.computed == 3
    assert held.judged == 1
    assert held.authorities == ["retry-policy"]
    assert held.pooled == pytest.approx(0.25)


def test_the_limit_of_a_pooled_judgement_is_stated(tmp_path):
    """Said whenever any of it was pooled, because this is what a reader has to
    know: asked again, that part may answer differently with no code having
    changed."""
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=9,
            population=10,
            witness=[
                Judgement(
                    verdict=Verdict.DEMOTE,
                    basis=Basis.EVALUATED,
                    path="a.py",
                    name="d",
                    authority="retry-policy",
                )
            ],
        ),
    )

    said = witness("x", trail, tmp_path, output="here").describe()

    assert "re-evaluate rather than re-verify" in said
    assert "retry-policy" in said


def test_what_survived_is_named_so_a_reader_can_look(tmp_path):
    node = Node(id="n1", name="parse_retry", path="retry.py", line=10, kind=12)
    graph = Graph(root="/x", nodes={node.id: node})
    trail = chain(
        Step(sites=2, population=2),
        Step(
            sites=1,
            population=2,
            admissible=["n1"],
            witness=[judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL)],
        ),
    )

    held = witness("x", trail, tmp_path, output="here", graph=graph)

    assert held.stood_on == ["retry.py:11 parse_retry"]


# ── Keeping them ────────────────────────────────────────────────────────────


def test_witnesses_are_bounded_on_write(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))

    for n in range(KEEP + 15):
        keep(Witness(intent=f"run {n}", at=time.time() + n), tmp_path / "proj")

    assert len(recent(tmp_path / "proj", limit=999)) == KEEP


def test_the_most_recent_comes_back_first(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))

    for n in range(3):
        keep(Witness(intent=f"run {n}", at=time.time() + n), tmp_path / "proj")

    assert [w.intent for w in recent(tmp_path / "proj", 3)] == ["run 2", "run 1", "run 0"]


def test_one_unreadable_witness_does_not_hide_the_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    from vesta.bundle import _where

    keep(Witness(intent="good", at=time.time()), tmp_path / "proj")
    (_where(tmp_path / "proj") / "9999999999999.json").write_text(
        "{ not json", encoding="utf-8"
    )

    assert [w.intent for w in recent(tmp_path / "proj", 9)] == ["good"]


def test_the_chain_is_local_and_optional(tmp_path, monkeypatch):
    """Kept for somebody debugging their own session. Not part of the witness,
    and nothing depends on having it later."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    trail = chain(Step(sites=10, population=10), Step(sites=2, population=10))

    path = keep_chain(trail, tmp_path / "proj")

    assert path.is_file()
    assert "chains" in str(path)
    assert not witness("x", trail, tmp_path / "proj").chain_at


# ── Whether it landed where the standard said it should ─────────────────────


def test_a_narrowing_outside_the_predicted_region_is_caught(tmp_path):
    """The one check that speaks to correctness rather than only to shape.

    It can, because the region was worked out *before* the chain ran and from a
    different source — the standard's words crossed with the intent, against the
    repository's own graph and vocabulary. Two derivations agreeing is evidence;
    a chain checked against its own inputs is not.
    """
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=2,
            population=10,
            admissible=["far", "wide"],
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(8)
            ],
        ),
    )

    held = witness(
        "x", trail, tmp_path, output="here",
        expected=type("E", (), {"where": ["near", "close"], "because": []})(),
    )

    assert held.verdict == UNSOUND
    failed = next(f for f in held.findings if not f.held)
    assert "outside the region the standard predicts" in failed.detail


def test_a_narrowing_inside_the_predicted_region_holds(tmp_path):
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=2,
            population=10,
            admissible=["near", "close"],
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(8)
            ],
        ),
    )

    held = witness(
        "x", trail, tmp_path, output="here",
        expected=type("E", (), {"where": ["near", "close", "also"], "because": []})(),
    )

    assert held.verdict == SANE


def test_no_prediction_is_not_a_violation(tmp_path):
    """Where the standard says nothing about this work there is no region to be
    outside of, and reporting every landing as out of bounds would make an
    absent authority look like a violated one."""
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=2,
            population=10,
            admissible=["a", "b"],
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(8)
            ],
        ),
    )

    held = witness("x", trail, tmp_path, output="here")

    assert held.verdict == SANE
    bounds = next(f for f in held.findings if "belongs" in f.check)
    assert bounds.held
    assert "no standard predicted a region" in bounds.detail


def test_the_standard_relied_on_travels_with_the_record(tmp_path):
    """A sound process that followed a wrong standard and an unsound process are
    the same outcome and different failures. A record that cannot tell them
    apart leaves both unattributable.
    """
    trail = chain(Step(sites=10, population=10), Step(sites=2, population=10,
                  admissible=["a"], witness=[judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL)]))

    held = witness(
        "x", trail, tmp_path, output="here",
        expected=type("E", (), {"where": ["a"], "because": ["every retry must be bounded"]})(),
        standard="retry-policy@ab12cd34",
        standard_digest="ab12cd34ef56",
    )

    assert held.standard == "retry-policy@ab12cd34"
    assert held.standard_digest == "ab12cd34ef56"
    assert held.stood_by == ["every retry must be bounded"]
    said = held.describe()
    assert "judged against retry-policy@ab12cd34" in said
    assert "every retry must be bounded" in said


def test_the_vocabulary_that_decided_the_region_is_named(tmp_path):
    """As load-bearing as the standard, because the predicted region is read
    through it.

    A record judged in-bounds under one vocabulary and out under another is not
    contradicting itself — it is being read against a standard that moved, and
    without a version nobody can tell those apart.
    """
    trail = chain(
        Step(sites=10, population=10),
        Step(sites=2, population=10, admissible=["a"],
             witness=[judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL)]),
    )

    held = witness("x", trail, tmp_path, output="here", vocabulary="bff8d95182b1dc91")

    assert held.vocabulary == "bff8d95182b1dc91"
    assert "read through vocabulary bff8d951" in held.describe()


# ── Guided mode in the witness ──────────────────────────────────────────────


def test_a_blind_record_carrying_interventions_is_malformed(tmp_path):
    """There was nothing to intervene with: the mode says guidance never saw
    the region, and the record contradicts itself."""
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=9, population=10, admissible=["a"],
            witness=[judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL)],
            interventions=[Intervention(about="a", evidence="e")],
        ),
    )

    held = witness("x", trail, tmp_path, output="here")

    assert held.verdict == UNSOUND
    assert any(
        "contradicts itself" in f.detail for f in held.findings if not f.held
    )


def test_a_guided_witness_carries_mode_interventions_and_friction(tmp_path):
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=2, population=10, admissible=["a", "b"],
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(8)
            ],
            interventions=[
                Intervention(
                    step=1, path="a.py", line=10, name="b",
                    evidence="the evidence kept this at standing",
                    action="demoted — outside the region",
                )
            ],
        ),
    )
    trail.mode = "guided"

    held = witness(
        "x", trail, tmp_path, output="here",
        expected=type("E", (), {"where": ["a", "b"], "because": []})(),
    )

    assert held.mode == "guided"
    assert len(held.interventions) == 1
    assert held.friction == pytest.approx(1 / 8)
    assert "guided — 1 intervention(s)" in held.describe()
    assert held.verdict == SANE


def test_an_out_of_region_survivor_is_the_guided_modes_strongest_flag(tmp_path):
    """Guidance demoted it and the evidence kept it anyway — a flag that exists
    only because guidance may not remove."""
    trail = chain(
        Step(sites=10, population=10),
        Step(
            sites=2, population=10, admissible=["a", "stray"],
            witness=[
                judged(Verdict.SOUND_PRUNE, Basis.STRUCTURAL, f"n{i}")
                for i in range(8)
            ],
            interventions=[Intervention(about="stray", evidence="kept by evidence")],
        ),
    )
    trail.mode = "guided"

    held = witness(
        "x", trail, tmp_path, output="here",
        expected=type("E", (), {"where": ["a"], "because": []})(),
    )

    failed = next(f for f in held.findings if not f.held and "belongs" in f.check)
    assert "notwithstanding guidance" in failed.detail
    assert "overcame" in failed.detail
