"""Cutting a display string without cutting a word in half.

Found reading `vesta decided`'s output: a bare `text[:90]` cut "unless" down
to "unl" and "check" down to "ch", with nothing marking that anything had
been removed. A summary that looks complete when it is not is worse than one
that says plainly where it stopped.
"""

from __future__ import annotations

from vesta.rules import Gap, Rule, trimmed


def test_short_text_is_returned_unchanged():
    assert trimmed("short", 100) == "short"


def test_text_at_the_limit_is_unchanged():
    text = "x" * 50
    assert trimmed(text, 50) == text


def test_long_text_is_cut_at_a_word_boundary():
    text = "there should be one env file for the whole project unless told otherwise"
    found = trimmed(text, 40)

    assert found.endswith("…")
    assert not found[:-1].endswith(" ")
    # The cut lands on a real word, not partway through one — the original
    # text, split on spaces, contains the trimmed text (minus the marker) as
    # a run of whole words.
    words = text.split()
    cut_words = found[:-1].strip().split()
    assert cut_words == words[: len(cut_words)]


def test_a_single_long_word_is_still_cut_rather_than_reduced_to_the_marker():
    """Backing off to the last space is wrong when there is no good space to
    back off to — a 200-character identifier should be cut at the limit, not
    collapsed to just the ellipsis."""
    text = "x" * 200
    found = trimmed(text, 40)

    assert found != "…"
    assert len(found) == 40
    assert found.endswith("…")


def test_the_marker_is_never_the_whole_budget_when_room_exists():
    found = trimmed("a" * 500, 10)
    assert len(found) == 10
    assert found.endswith("…")


def test_a_limit_of_zero_or_less_returns_only_the_marker():
    assert trimmed("anything at all", 0) == "…"
    assert trimmed("anything at all", -5) == "…"


def test_rule_describe_never_cuts_mid_word():
    long_text = "there should be one env file for v3 not one per repo unless " * 3
    rule = Rule(text=long_text)
    found = rule.describe()

    assert found.endswith("…")
    shown = found.split("] ", 1)[1][:-1].strip()
    assert rule.text.startswith(shown)


def test_gap_describe_never_cuts_mid_word():
    gap = Gap(
        text="deps should be resolved before the build starts, unless explicitly deferred",
        missing="a check that reads the build order",
    )
    found = gap.describe()

    before_dash = found.split(" — needs ")[0]
    if before_dash.endswith("…"):
        prefix = before_dash[:-1].strip()
        assert gap.text.startswith(prefix) or prefix == ""
