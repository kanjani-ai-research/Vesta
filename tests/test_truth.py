"""The measurement, tested before the thing it measures.

A harness that flatters the approach it grades is worse than no harness, so the
properties here are about the grading being honest: a complete baseline must
score complete recall, an empty prediction must score zero rather than divide by
zero, and every approach must be graded by the identical path.
"""

from __future__ import annotations

from vesta.truth import (
    Change,
    Result,
    Score,
    compare,
    grade,
    same_file,
    usable,
)


def change(changed, tests, repo="x") -> Change:
    return Change(commit="a" * 40, repo=repo, changed=changed, touched_tests=tests)


# ── Scoring ──────────────────────────────────────────────────────────────


def test_a_perfect_prediction_scores_one():
    found = Score(predicted={"t/a.py"}, actual={"t/a.py"})

    assert found.precision == 1.0 and found.recall == 1.0 and found.f1 == 1.0


def test_what_moved_and_was_not_predicted_is_the_dangerous_direction():
    found = Score(predicted={"t/a.py"}, actual={"t/a.py", "t/b.py"})

    assert found.missed == {"t/b.py"}
    assert found.recall == 0.5
    assert not found.spurious


def test_an_empty_prediction_scores_zero_rather_than_dividing():
    found = Score(predicted=set(), actual={"t/a.py"})

    assert found.precision == 0.0 and found.recall == 0.0 and found.f1 == 0.0


def test_predicting_everything_is_complete_and_imprecise():
    found = Score(predicted={f"t/{n}.py" for n in range(10)}, actual={"t/1.py"})

    assert found.recall == 1.0
    assert found.precision == 0.1


# ── Usability ────────────────────────────────────────────────────────────


def test_a_commit_with_no_source_change_has_no_input():
    assert not change([], ["tests/test_a.py"]).is_usable


def test_a_commit_with_no_test_change_has_no_label():
    assert not change(["a/b.py"], []).is_usable


def test_only_usable_commits_are_graded():
    changes = [
        change(["a/b.py"], ["tests/test_b.py"]),
        change([], ["tests/test_c.py"]),
        change(["a/d.py"], []),
    ]

    assert len(usable(changes)) == 1


# ── Aggregation ──────────────────────────────────────────────────────────


def test_completeness_counts_commits_where_nothing_was_missed():
    """The number that matters most for a correctness claim: an approach with
    good average recall that misses something on a third of changes is not one
    anybody should rely on to say "safe to change"."""
    result = Result(
        name="x",
        scores=[
            Score(predicted={"a"}, actual={"a"}),
            Score(predicted={"a"}, actual={"a", "b"}),
        ],
    )

    assert result.never_missed == 0.5


def test_averages_are_per_commit_not_pooled():
    """Pooling would let one commit that changed forty files dominate, and the
    question is how well an approach does on a change."""
    result = Result(
        name="x",
        scores=[
            Score(predicted={"a"}, actual={"a"}),
            Score(predicted={f"x{n}" for n in range(40)}, actual={"x0"}),
        ],
    )

    assert abs(result.precision - (1.0 + 1 / 40) / 2) < 0.001


def test_every_approach_is_graded_by_the_same_path():
    """A comparison cannot be flattered by measuring approaches differently."""
    changes = [change(["a/b.py"], ["tests/test_b.py"])]
    results = compare(changes, {
        "nothing": lambda c: set(),
        "convention": lambda c: same_file(c.changed),
    })

    assert [r.name for r in results] == ["nothing", "convention"]
    assert results[0].recall == 0.0
    assert results[1].recall == 1.0


# ── The convention baseline ──────────────────────────────────────────────


def test_the_convention_maps_a_module_to_its_test():
    assert same_file(["vesta/truth.py"]) == {"tests/test_truth.py"}


def test_the_convention_ignores_package_markers():
    """A change to __init__.py names no test, and guessing tests/test___init__
    would be a spurious prediction on almost every commit."""
    assert same_file(["vesta/__init__.py"]) == set()
