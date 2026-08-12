"""Raising a rule at the moment work depends on it.

A list of twenty-four rules to review is a list nobody reviews. The same rule
raised while somebody edits the file it governs is a question they already care
about — so the scope is what a change touches, and the whole interaction is one
question with three answers.

Most of these test silence. A prompt that interrupts work has to be right, and
the cost of a wrong one is that the next is ignored.
"""

from __future__ import annotations

import pytest

from vesta import confirm
from vesta.bearing import on, worth_raising
from vesta.enforce import Finding, Site
from vesta.rules import Rule

BROKEN = Rule(
    text="one .env for v3, not one per service",
    names=[".env"],
    check="artefact",
    how="x",
)
HOLDS = Rule(
    text="pin every dependency", names=["pyproject.toml"], check="artefact", how="y"
)
ELSEWHERE = Rule(
    text="never a bare except", names=["retry"], check="behaviour", how="z"
)

FINDINGS = [
    Finding(
        rule="one .env for v3, not one per service",
        said="one .env for v3",
        sites=[Site(path="services/api/.env", line=1, what="a second .env")],
    ),
    Finding(rule="pin every dependency", said="pin every dependency", sites=[]),
]

TOUCHED = ["services/api/.env", "services/api/main.py"]


def test_a_rule_the_work_breaks_is_raised():
    raised = worth_raising(FINDINGS, [BROKEN, HOLDS, ELSEWHERE], TOUCHED)
    assert [b.rule for b in raised] == [BROKEN.text]


def test_a_rule_that_holds_is_not_raised():
    """Interrupting somebody to say a rule is being followed is noise."""
    raised = worth_raising(FINDINGS, [HOLDS], TOUCHED)
    assert raised == []


def test_a_rule_about_other_files_is_not_raised():
    raised = worth_raising(FINDINGS, [ELSEWHERE], TOUCHED)
    assert raised == []


def test_nothing_is_raised_when_nothing_is_touched():
    assert worth_raising(FINDINGS, [BROKEN], []) == []


def test_only_one_is_raised_at_a_time():
    """This interrupts work. A second question is a conversation nobody
    agreed to have."""
    also = Rule(text="another about env", names=[".env"], check="artefact", how="q")
    findings = FINDINGS + [
        Finding(
            rule="another about env",
            said="another about env",
            sites=[Site(path="services/api/.env", line=9, what="x")],
        )
    ]
    assert len(worth_raising(findings, [BROKEN, also], TOUCHED)) == 1


def test_a_rule_that_could_not_be_checked_is_not_raised(tmp_path):
    """A gap is worth knowing about and is not evidence of anything. Raising
    it as though it were would put an unanswerable question to somebody."""
    findings = [
        Finding(
            rule="one .env for v3, not one per service",
            said="one .env for v3",
            undecided="no check covers what this constrains",
        )
    ]
    assert worth_raising(findings, [BROKEN], TOUCHED) == []
    # It is still reported as bearing on the work, just not put to anybody.
    assert [b.rule for b in on(findings, [BROKEN], TOUCHED)] == [BROKEN.text]


def test_something_already_left_unanswered_is_not_raised_again(tmp_path):
    """They saw it and moved on. Asking again mid-task is the nagging this
    exists to avoid."""
    confirm.record(tmp_path, BROKEN.text, confirm.ABSTAINED)
    assert worth_raising(FINDINGS, [BROKEN], TOUCHED, repo=tmp_path) == []


def test_a_rule_they_confirmed_is_still_raised_when_broken(tmp_path):
    """Confirming a rule is not agreeing to break it. If the code disagrees,
    that is exactly when they want to know."""
    confirm.record(tmp_path, BROKEN.text, confirm.IS_A_RULE)
    raised = worth_raising(FINDINGS, [BROKEN], TOUCHED, repo=tmp_path)
    assert [b.rule for b in raised] == [BROKEN.text]


def test_the_least_broken_comes_first():
    """One site is a question about that place; twenty is a rule nobody has
    been following, which is a conversation rather than a prompt."""
    many = Rule(text="broken everywhere", names=[".env"], check="artefact", how="q")
    findings = FINDINGS + [
        Finding(
            rule="broken everywhere",
            said="broken everywhere",
            sites=[Site(path="services/api/.env", line=n, what="x") for n in range(9)],
        )
    ]
    raised = worth_raising(findings, [many, BROKEN], TOUCHED, limit=2)
    assert raised[0].rule == BROKEN.text


def test_what_is_asked_uses_their_words_and_does_not_accuse():
    """The code disagreeing with a rule means one of them is out of date, and
    which one is not Vesta's to say."""
    raised = worth_raising(FINDINGS, [BROKEN], TOUCHED)
    asked = raised[0].ask()
    assert "one .env for v3" in asked
    assert "services/api/.env" in asked
    assert "still stand" in asked
    for accusation in ("wrong", "mistake", "should not", "violat"):
        assert accusation not in asked.lower()


def test_a_rule_is_named_by_a_handle():
    raised = worth_raising(FINDINGS, [BROKEN], TOUCHED)
    assert raised[0].name == confirm.handle(BROKEN.text)


def test_a_rule_naming_nothing_bears_on_nothing():
    """Rather than bearing on everything, which is how a prompt becomes noise."""
    vague = Rule(text="be careful", names=[], check="underived", how="")
    assert on(FINDINGS, [vague], TOUCHED) == []


def test_a_declared_rule_bears_on_the_files_it_names(tmp_path):
    """Without this a rule the user stated could never be raised — it would
    bear on nothing, which is most of the value of having stated it."""
    from vesta.rules import Found

    confirm.declare(tmp_path, "one .env for the whole project, not one per service")
    rule = confirm.apply(Found(), tmp_path).rules[0]
    assert rule.names, "a declared rule names nothing and so governs nothing"
    from vesta.bearing import _covers

    assert _covers(rule, ["services/api/.env"])


def test_a_rule_without_a_check_is_never_put_to_anybody(tmp_path):
    """The honest limit of this feature.

    `enforce` can only check a rule that carries an executable check, and
    writing one is judgement — the `vesta-rules` agent's work, on the host's
    inference. Until a rule has been through that, `bears_on` stays silent
    about it. Silence is right: an unchecked rule is a gap, and raising a gap
    as though it were a violation would put an unanswerable question to
    somebody in the middle of their work.
    """
    from vesta.enforce import against
    from vesta.graph import Graph
    from vesta.rules import Found

    confirm.declare(tmp_path, "never use a bare except in retry.py")
    found = confirm.apply(Found(), tmp_path)
    verdict = against(found, Graph(root=str(tmp_path)), tmp_path)

    assert verdict.findings, "the rule was not checked at all"
    assert all(f.undecided for f in verdict.findings)
    assert worth_raising(verdict.findings, found.standing, ["retry.py"]) == []


# ── Abstention: what Vesta could not answer ─────────────────────────────────


UNCHECKABLE = [
    Finding(
        rule="one .env for v3, not one per service",
        said="one .env for v3",
        undecided="no known check covers what this constrains",
    )
]


def test_a_rule_nothing_can_check_reads_differently_from_one_that_holds():
    """The two look the same from outside and are not: one is an answer, the
    other is Vesta declining to give one."""
    from vesta.bearing import on

    abstained = on(UNCHECKABLE, [BROKEN], TOUCHED)[0]
    held = on(FINDINGS, [HOLDS], ["pyproject.toml"])[0]

    assert abstained.abstained
    assert not held.abstained
    assert "could not tell" in abstained.describe()
    assert "holds" in held.describe()
    assert abstained.describe() != held.describe()


def test_what_could_not_be_checked_is_reported():
    from vesta.bearing import unanswered

    found = unanswered(UNCHECKABLE, [BROKEN], TOUCHED)
    assert [b.rule for b in found] == [BROKEN.text]


def test_a_rule_that_holds_is_not_an_abstention():
    from vesta.bearing import unanswered

    assert unanswered(FINDINGS, [HOLDS], ["pyproject.toml"]) == []


def test_a_broken_rule_is_not_an_abstention():
    """It was checked, and the answer was no."""
    from vesta.bearing import unanswered

    assert unanswered(FINDINGS, [BROKEN], TOUCHED) == []


def test_an_abstention_is_queued_for_deliberate_settling(tmp_path):
    """Yields rather than interrupting, and queues rather than vanishing —
    which is what abstention already means everywhere else here."""
    from vesta.bearing import queue

    assert queue(UNCHECKABLE, [BROKEN], TOUCHED, tmp_path) == 1
    waiting = confirm.recall(tmp_path).waiting
    assert [v.text for v in waiting] == [BROKEN.text]


def test_a_queued_abstention_stays_out_of_enforcement(tmp_path):
    """A rule nothing could check is not a rule the code was held to."""
    from vesta.bearing import queue
    from vesta.rules import Found

    queue(UNCHECKABLE, [BROKEN], TOUCHED, tmp_path)
    kept = confirm.apply(Found(rules=[BROKEN]), tmp_path)
    assert BROKEN.text not in [r.text for r in kept.rules]
