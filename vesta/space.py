"""Refining a flat check into survivors, prunes, demotions, and gaps.

`enforce.against` checks every standing rule the same way: run its derived
check, report the sites. That treats a rule with no check the same as a rule
whose check ran and found nothing — both come back with an empty `sites`
list, and only `Finding.undecided` tells them apart, which is discoverable
but not forced: nothing about the shape of the result makes a caller notice
the difference.

Nor does it distinguish a rule that failed for a reason nothing will
change — the code genuinely violates it, keep flagging it — from a check that
found nothing because its own subject does not exist anywhere in the
repository. `enforce.run_check` already makes that second judgement inline,
for `COUNT_AT_LEAST` with nothing found: "nothing matching the rule's subject
exists here, so the rule is neither honoured nor broken." That is a sound
exclusion — nothing about *this pass* should reopen it, because nothing about
the repository will change what made it true — and today it is a string
buried in `Finding.undecided` rather than something a caller can act on.

**A pruned rule states why, and whether reconsidering it makes sense.** A
sound prune is certain and this pass should not revisit it. A demotion is a
priority judgement rather than a certainty — a rule with no derived check
might still be real, and treating "nothing could check this" as equivalent
to "checked and holds" is exactly the gap `enforce.Verdict.describe` already
goes out of its way to keep separate in its own counts. Naming the two apart,
with a reason attached to each, is what this adds.

**Every move is witnessed.** A caller told "3 held, 2 broken" cannot ask why
a fourth rule is absent from both counts. A witness entry for every rule —
survived, pruned, demoted, or a gap — makes the absence itself inspectable
rather than requiring the caller to already know to ask.

**This is not a general algebra.** It is scoped to the one place Vesta
checks a flat collection against a graph: `enforce.against`. A second caller
with a genuinely different shape — refining a Procedure's steps, or a
cross-project Intention set — earns its own extension of this when it
exists, not a speculative one built in advance of it. `propagate.py`'s own
discipline is the same: "depth is bounded, and the bound is a stated cost."
Generality nobody has asked for yet is an unstated cost wearing the same
disguise.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, List, Sequence

from pydantic import BaseModel, Field

from .rules import Rule


class Verdict(str, Enum):
    """What a member function decided about one rule."""

    SURVIVES = "survives"
    SOUND_PRUNE = "sound_prune"  # reasoned, and this pass should not reopen it
    DEMOTE = "demote"            # a priority judgement, reversible and reopenable
    GAP = "gap"                  # nothing could decide — emitted, never dropped


class Outcome(BaseModel):
    """What a member function returned for one rule."""

    verdict: Verdict
    reason: str = ""


def survive() -> Outcome:
    return Outcome(verdict=Verdict.SURVIVES)


def sound_prune(reason: str) -> Outcome:
    return Outcome(verdict=Verdict.SOUND_PRUNE, reason=reason)


def demote(reason: str) -> Outcome:
    return Outcome(verdict=Verdict.DEMOTE, reason=reason)


def gap(what: str) -> Outcome:
    return Outcome(verdict=Verdict.GAP, reason=what)


# A member judges one rule. Scoped to Rule specifically rather than a generic
# candidate type — there is exactly one caller today (enforce.py), and
# widening this ahead of a second real one is the same unstated-generality
# cost the module docstring argues against.
Member = Callable[[Rule], Outcome]


class Witness(BaseModel):
    """One rule, and what happened to it."""

    rule: str
    verdict: Verdict
    reason: str = ""

    def describe(self) -> str:
        marks = {
            Verdict.SURVIVES: "✓",
            Verdict.SOUND_PRUNE: "✗ (sound)",
            Verdict.DEMOTE: "↓",
            Verdict.GAP: "?",
        }
        mark = marks[self.verdict]
        reason = f" — {self.reason}" if self.reason else ""
        return f"{mark} {self.rule}{reason}"


class Result(BaseModel):
    """What refinement found: survivors, and why everything else did not."""

    survivors: List[Rule] = Field(default_factory=list)
    pruned: List[Witness] = Field(default_factory=list)
    demoted: List[Witness] = Field(default_factory=list)
    gaps: List[Witness] = Field(default_factory=list)
    witness: List[Witness] = Field(default_factory=list)

    def describe(self) -> str:
        parts = [f"{len(self.survivors)} survive"]
        if self.pruned:
            parts.append(f"{len(self.pruned)} soundly excluded")
        if self.demoted:
            parts.append(f"{len(self.demoted)} demoted")
        if self.gaps:
            parts.append(f"{len(self.gaps)} gap(s)")
        return ", ".join(parts)


def refine(rules: Sequence[Rule], members: Sequence[Member]) -> Result:
    """Run every rule through every member in order; the first non-survive wins.

    A rule every member lets through survives. One a member excludes stops
    there — later members never see it, since a sound prune or a demotion is
    already a decided answer about that rule, not a candidate for a second
    opinion.
    """
    result = Result()
    for rule in rules:
        label = rule.stated or rule.text
        outcome = Outcome(verdict=Verdict.SURVIVES)
        for member in members:
            outcome = member(rule)
            if outcome.verdict != Verdict.SURVIVES:
                break

        entry = Witness(rule=label, verdict=outcome.verdict, reason=outcome.reason)
        result.witness.append(entry)
        if outcome.verdict == Verdict.SURVIVES:
            result.survivors.append(rule)
        elif outcome.verdict == Verdict.SOUND_PRUNE:
            result.pruned.append(entry)
        elif outcome.verdict == Verdict.DEMOTE:
            result.demoted.append(entry)
        else:
            result.gaps.append(entry)

    return result
