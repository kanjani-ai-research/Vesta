"""Asking the user which corrections are rules, and keeping the answer."""

from __future__ import annotations

import pytest

from vesta import confirm
from vesta.confirm import Verdict
from vesta.rules import Found, Rule


def _found() -> Found:
    return Found(
        rules=[
            Rule(text="never use a bare except", check="behaviour", how="x"),
            Rule(text="do not log in this one spot", check="underived", how="y"),
            Rule(text="type every public function", check="traversal", how="z"),
        ]
    )


def test_nothing_confirmed_yet(tmp_path):
    assert confirm.recall(tmp_path).describe() == "nothing has been confirmed yet"


def test_a_verdict_is_kept(tmp_path):
    confirm.record(tmp_path, "never use a bare except", confirm.IS_A_RULE)
    kept = confirm.recall(tmp_path)
    assert len(kept.verdicts) == 1
    assert kept.verdicts[0].binding


def test_the_same_candidate_is_never_asked_twice(tmp_path):
    """The whole value. Asking again is how a good question becomes a nuisance."""
    found = _found()
    first = confirm.worth_asking(found, tmp_path)
    assert len(first) == 3

    confirm.record(tmp_path, first[0].text, confirm.NOT_A_RULE)
    again = confirm.worth_asking(found, tmp_path)
    assert first[0].text not in [r.text for r in again]
    assert len(again) == 2


def test_candidates_with_evidence_come_first(tmp_path):
    """Ranking uncheckable first looked right and surfaced conversational
    asides. A candidate some check recognises is one there is evidence for."""
    asking = confirm.worth_asking(_found(), tmp_path)
    assert asking[0].check != "underived"
    assert asking[-1].check == "underived"


def test_a_dismissed_candidate_stops_counting(tmp_path):
    found = _found()
    confirm.record(tmp_path, "do not log in this one spot", confirm.NOT_A_RULE)
    kept = confirm.apply(found, tmp_path)
    assert "do not log in this one spot" not in [r.text for r in kept.rules]
    assert len(kept.rules) == 2


def test_a_cleaner_statement_is_carried_onto_the_rule(tmp_path):
    found = _found()
    confirm.record(
        tmp_path, "never use a bare except", confirm.IS_A_RULE, "no bare except anywhere"
    )
    kept = confirm.apply(found, tmp_path)
    rule = next(r for r in kept.rules if r.text == "never use a bare except")
    assert rule.stated == "no bare except anywhere"


def test_a_lapsed_rule_stops_standing(tmp_path):
    found = _found()
    confirm.record(tmp_path, "type every public function", confirm.NO_LONGER)
    kept = confirm.apply(found, tmp_path)
    assert "type every public function" not in [r.text for r in kept.rules]


def test_a_verdict_nobody_recognises_is_kept_safely(tmp_path):
    """The answer came from a person. Losing it to a typo is worse than
    recording the safe reading."""
    confirm.record(tmp_path, "something", "nonsense")
    kept = confirm.recall(tmp_path)
    assert kept.verdicts[0].verdict == confirm.NOT_A_RULE


def test_answering_again_replaces_rather_than_duplicates(tmp_path):
    confirm.record(tmp_path, "a rule", confirm.NOT_A_RULE)
    confirm.record(tmp_path, "a rule", confirm.IS_A_RULE)
    kept = confirm.recall(tmp_path)
    assert len(kept.verdicts) == 1
    assert kept.verdicts[0].binding


def test_whitespace_and_case_do_not_make_a_new_candidate(tmp_path):
    confirm.record(tmp_path, "Never   Use A Bare Except", confirm.IS_A_RULE)
    remaining = confirm.worth_asking(_found(), tmp_path)
    assert "never use a bare except" not in [r.text for r in remaining]


def test_applying_nothing_changes_nothing(tmp_path):
    found = _found()
    assert len(confirm.apply(found, tmp_path).rules) == 3


# ── Abstention, reversal, and the void ──────────────────────────────────────


def test_abstention_is_neither_enforced_nor_dismissed(tmp_path):
    """Closing a dialog is a signal, not a verdict. Reading it as "not a rule"
    would discard a rule the user might have kept."""
    found = _found()
    confirm.record(tmp_path, "never use a bare except", confirm.ABSTAINED)
    kept = confirm.apply(found, tmp_path)

    standing = [r.text for r in kept.rules]
    assert "never use a bare except" not in standing  # not enforced
    assert confirm.recall(tmp_path).waiting  # and not dismissed either


def test_what_is_waiting_is_reported(tmp_path):
    confirm.record(tmp_path, "a", confirm.ABSTAINED)
    confirm.record(tmp_path, "b", confirm.IS_A_RULE)
    asked = confirm.recall(tmp_path)
    assert len(asked.waiting) == 1
    assert "waiting on you" in asked.describe()
    assert "1 rule(s)" in asked.describe()


def test_an_abstention_is_not_asked_again_in_passing(tmp_path):
    """The user saw it and moved on. Putting it back in the queue is nagging."""
    found = _found()
    first = confirm.worth_asking(found, tmp_path)
    confirm.record(tmp_path, first[0].text, confirm.ABSTAINED)
    again = [r.text for r in confirm.worth_asking(found, tmp_path)]
    assert first[0].text not in again


def test_a_note_can_become_a_rule(tmp_path):
    """"Said once about one place" becomes "this holds everywhere" often
    enough that a terminal verdict would lose real rules."""
    found = _found()
    confirm.record(tmp_path, "never use a bare except", confirm.NOT_A_RULE)
    assert "never use a bare except" not in [
        r.text for r in confirm.apply(_found(), tmp_path).rules
    ]

    confirm.record(tmp_path, "never use a bare except", confirm.IS_A_RULE)
    kept = confirm.apply(_found(), tmp_path)
    assert "never use a bare except" in [r.text for r in kept.rules]


def test_changing_your_mind_is_recorded(tmp_path):
    """When somebody reversed a decision is part of the decision."""
    confirm.record(tmp_path, "a rule", confirm.NOT_A_RULE)
    confirm.record(tmp_path, "a rule", confirm.IS_A_RULE)
    verdict = confirm.recall(tmp_path).verdicts[0]
    assert verdict.was == confirm.NOT_A_RULE
    assert "was not a rule" in verdict.describe()


def test_answering_the_same_way_twice_is_not_a_change(tmp_path):
    confirm.record(tmp_path, "a rule", confirm.IS_A_RULE)
    confirm.record(tmp_path, "a rule", confirm.IS_A_RULE)
    assert confirm.recall(tmp_path).verdicts[0].was == ""


def test_a_long_verdict_is_cut_at_a_word_not_mid_word():
    """A bare slice cut "unless" down to "unl" with nothing marking that
    anything was removed — a summary that reads as complete when it is not."""
    long_text = "there should be one env file for the whole project unless the deploy target needs its own"
    verdict = Verdict(text=long_text, verdict=confirm.IS_A_RULE)

    found = verdict.describe()

    assert found.endswith("…")
    shown = found.split(": ", 1)[1][:-1].strip()
    assert long_text.startswith(shown)


def test_reopening_puts_a_candidate_back_in_question(tmp_path):
    found = _found()
    confirm.record(tmp_path, "never use a bare except", confirm.NOT_A_RULE)
    assert "never use a bare except" not in [
        r.text for r in confirm.worth_asking(found, tmp_path)
    ]

    confirm.reopen(tmp_path, "never use a bare except")
    assert "never use a bare except" in [
        r.text for r in confirm.worth_asking(found, tmp_path)
    ]


def test_a_declared_rule_stands_though_nothing_recovered_it(tmp_path):
    """The void: Vesta reads transcripts, so a constraint nobody ever had to
    correct leaves no trace. Filtering what was recovered can never surface it."""
    confirm.declare(tmp_path, "every module opens with a docstring")
    kept = confirm.apply(_found(), tmp_path)
    texts = [r.text for r in kept.rules]
    assert "every module opens with a docstring" in texts
    assert len(texts) == 4  # the three recovered, plus the one declared


def test_a_declared_rule_carries_a_check_where_one_fits(tmp_path):
    confirm.declare(tmp_path, "every module opens with a docstring")
    rule = next(
        r
        for r in confirm.apply(_found(), tmp_path).rules
        if "docstring" in r.text
    )
    assert rule.stated
    assert rule.check


def test_declaring_nothing_records_nothing(tmp_path):
    confirm.declare(tmp_path, "   ")
    assert confirm.recall(tmp_path).verdicts == []


def test_a_declared_rule_is_marked_as_such(tmp_path):
    confirm.declare(tmp_path, "a standing rule")
    verdict = confirm.recall(tmp_path).verdicts[0]
    assert verdict.declared
    assert "declared" in verdict.describe()


def test_a_declared_rule_survives_being_reconsidered(tmp_path):
    """Set aside and restored, it is still a rule Vesta could not have found."""
    confirm.declare(tmp_path, "a standing rule")
    confirm.record(tmp_path, "a standing rule", confirm.NO_LONGER)
    confirm.record(tmp_path, "a standing rule", confirm.IS_A_RULE)
    assert confirm.recall(tmp_path).verdicts[0].declared


# ── Adjudicating without pasting a sentence ─────────────────────────────────


def test_a_candidate_has_a_short_handle(tmp_path):
    """`--text '<the exact wording>'` is not something anybody does twice."""
    handle = confirm.handle("never use a bare except")
    assert len(handle) == 4
    assert handle.isalnum()


def test_a_handle_is_stable_across_wording_noise(tmp_path):
    assert confirm.handle("Never   Use A Bare  Except") == confirm.handle(
        "never use a bare except"
    )


def test_a_candidate_is_found_by_its_handle(tmp_path):
    confirm.record(tmp_path, "never use a bare except", confirm.ABSTAINED)
    handle = confirm.handle("never use a bare except")
    assert confirm.find(tmp_path, handle) == "never use a bare except"


def test_a_candidate_is_found_by_a_fragment(tmp_path):
    """Somebody who types part of it means that one."""
    confirm.record(tmp_path, "never use a bare except", confirm.ABSTAINED)
    assert confirm.find(tmp_path, "bare except") == "never use a bare except"


def test_an_unknown_handle_is_taken_at_face_value(tmp_path):
    """So declaring something new still works through the same door."""
    assert confirm.find(tmp_path, "something nobody said") == "something nobody said"


def test_the_queue_drops_candidates_a_tightened_extractor_would_reject(tmp_path):
    """Otherwise the queue never gets cleaner than the day it was worst.

    Nothing re-runs the constraint test once a verdict is persisted, so
    tightening the extractor left every fragment already captured sitting in
    the queue — including "it should be conditional, I don't know whether your
    assertion holds", a sentence in which the user disclaimed the very thing
    they were being asked to confirm.
    """
    confirm.record(
        tmp_path,
        "it should be conditional, I don't know whether your assertion holds",
        confirm.ABSTAINED,
    )
    confirm.record(tmp_path, "one .env for v3, not one per service", confirm.ABSTAINED)

    waiting = [v.text for v in confirm.recall(tmp_path).waiting]

    # A real rule stays, including one the harvest-time gate would reject —
    # candidates reach this queue by paths that gate never saw.
    assert "one .env for v3, not one per service" in waiting
    assert not any("don't know" in text for text in waiting)


def test_a_verdict_the_user_gave_is_not_overruled_by_a_later_change(tmp_path):
    """Re-testing applies to the queue, not to decisions already made.

    A user who said "yes, that is a rule" settled it. Tightening what Vesta
    would have captured does not un-settle what they told it.
    """
    said = "it should be conditional, I don't know whether your assertion holds"
    confirm.record(tmp_path, said, confirm.IS_A_RULE)

    asked = confirm.recall(tmp_path)
    assert not asked.waiting
    assert any(v.text == said and v.settled for v in asked.verdicts)
