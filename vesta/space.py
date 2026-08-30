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


class Basis(str, Enum):
    """What kind of thing a judgement rests on, and so whether it can be re-run.

    A verdict says *what* was decided. This says what the decision was made
    from, which is the only thing that determines whether it can be checked
    again later — and a record that cannot say which of its own conclusions are
    re-checkable is a record that implies all of them are.

    `STRUCTURAL` is a predicate over the graph: reachability, containment, where
    a definition lives. A pure function of graph state, so re-evaluating it
    against the current graph either agrees with what was recorded or does not,
    and either way the answer is a fact.

    `BYTE` is a hash comparison over a recorded span — `authority.check`, and
    nothing else. Also re-runnable, and its three outcomes are already named.

    `EVALUATED` is a judgement pooled from an authority and the evidence put in
    front of it — a skill's own words, and what a traversal found that bears on
    the action. It is re-runnable in a way `ASSERTED` is not, because what was
    shown was recorded and can be shown again. But it is **not deterministic**:
    the same authority over the same evidence may come back differently with no
    code having changed. So replaying one answers a different question than
    replaying a structural judgement — not *does this still hold* but *does it
    still evaluate the same way* — and reporting both under one word would let a
    bundle overstate itself.

    `ASSERTED` is a judgement somebody or something made by reading, with no
    record of what was read, and it is kept apart because **it cannot be
    replayed at all**. An agent that labelled a definition may have misread code
    that has not changed since; re-running the label proves nothing about the
    original reading. Marking these as derived would manufacture confidence that
    no mechanism supports, which is the failure this project has twice had to
    correct in its own detectors.

    The distinction between the last two is the evidence. An evaluated judgement
    carries what it was shown, so a reader who disagrees can argue with the
    inputs; an asserted one carries nothing, so they can only take it or leave
    it.

    Deliberately closed, and small. A general expression language over the graph
    would let a judgement be plausibly wrong in more ways than it can be
    checked, and the point here is the opposite: a fixed set of kinds that each
    replay deterministically, or honestly say how they do not.
    """

    STRUCTURAL = "structural"  # a predicate over the graph; re-evaluable
    BYTE = "byte"              # a hash over a recorded span; comparable
    EVALUATED = "evaluated"    # pooled from an authority and recorded evidence
    ASSERTED = "asserted"      # read and decided; nothing can re-run it


class Outcome(BaseModel):
    """What a member function returned for one rule."""

    verdict: Verdict
    reason: str = ""
    basis: Basis = Basis.ASSERTED

    # For an evaluated verdict: which authority said so, and what it was shown.
    # Kept because the retrieval is deterministic even where the judgement is
    # not — when a pooled verdict turns out wrong the cause is usually what was
    # put in front of it rather than how it reasoned, and a record that blends
    # the two cannot say which.
    authority: str = ""
    evidence: List[str] = Field(default_factory=list)


def survive() -> Outcome:
    return Outcome(verdict=Verdict.SURVIVES)


def sound_prune(reason: str, basis: Basis = Basis.ASSERTED) -> Outcome:
    return Outcome(verdict=Verdict.SOUND_PRUNE, reason=reason, basis=basis)


def demote(reason: str, basis: Basis = Basis.ASSERTED) -> Outcome:
    return Outcome(verdict=Verdict.DEMOTE, reason=reason, basis=basis)


def gap(what: str) -> Outcome:
    # A gap is nothing having been decided, so there is nothing to re-decide.
    # Asserted is the honest basis rather than a kind meaning "none": what it
    # says is that replay cannot confirm this, which is true of a gap for the
    # plainest possible reason.
    return Outcome(verdict=Verdict.GAP, reason=what, basis=Basis.ASSERTED)


def evaluated(reason: str, authority: str = "", evidence: Sequence[str] = ()) -> Outcome:
    """A verdict pooled from an authority and what it was shown.

    **Always a demotion, never a sound prune.** `SOUND_PRUNE` means certain and
    not to be reopened by this pass, and a probabilistic result is precisely not
    that. Allowing an evaluation to prune would let a wrong call silently remove
    the right answer from the space with no way back; as a demotion it costs a
    ranking rather than a candidate, and a later pass can still reach it.

    That is a deliberate ceiling on what a pooled authority may do, and it is
    enforced here rather than left to each caller to remember.
    """
    return Outcome(
        verdict=Verdict.DEMOTE,
        reason=reason,
        basis=Basis.EVALUATED,
        authority=authority,
        evidence=list(evidence),
    )


# A member judges one rule. Scoped to Rule specifically rather than a generic
# candidate type — there is exactly one caller today (enforce.py), and
# widening this ahead of a second real one is the same unstated-generality
# cost the module docstring argues against.
Member = Callable[[Rule], Outcome]


class Witness(BaseModel):
    """One rule, and what happened to it.

    **Kept small on purpose.** A witness is written once per candidate, and a
    decision space is the whole repository at step zero — so a trajectory over
    an ordinary project carries hundreds of these and a bundle is mostly
    witness. Measured before this mattered: 730 judgements, 183kb of witness in
    a 201kb bundle, of which three distinct reasons and a `rule` string
    reconstructible from `path` and `name` in every single entry.

    So `rule` is derived rather than stored, and a reason repeated across a
    step is stored once by the step rather than on each entry. Neither loses
    anything a reader can ask for.
    """

    verdict: Verdict
    reason: str = ""
    # Where the reason lives when a step has folded its repeats into one list.
    # -1 while the reason is held here. Set only on the way to disk; a reader
    # always sees `reason` populated.
    says: int = -1

    # What was judged, as opposed to how it looked when it was judged.
    #
    # `rule` is a display string — for a candidate definition it reads
    # "retry.py:11 parse_retry" — and a display string changes when the line
    # moves. That makes a judgement unaddressable: a reader who sees an
    # exclusion that should not have happened cannot say "not this one again",
    # because the name they would say it about is not the name it will have
    # next run. Identity is what makes a judgement something to argue with
    # rather than something to read.
    #
    # Empty for a judgement about something with no location — a rule the user
    # stated, a whole action — and that is not a gap: those are already
    # identified by their own text, which is what `rule` holds for them.
    about: str = ""
    path: str = ""
    line: int = 0
    name: str = ""

    # What this judgement was about, in the form a reader wants to see. Held as
    # a field only where there is no location to build it from — a rule the
    # user stated, or an action — because for a definition it is exactly
    # `path:line name` and storing that beside the parts is the same string
    # twice. Measured: true of 730 entries out of 730.
    said: str = ""

    @property
    def rule(self) -> str:
        """The subject, however it was identified."""
        if self.said:
            return self.said
        if self.path and self.name:
            return f"{self.path}:{self.line + 1} {self.name}"
        return self.about

    # What this judgement rests on, and so whether replaying it means anything.
    # Defaults to the kind that claims least: a judgement whose basis nobody
    # stated is one nothing can re-run, and assuming otherwise is how a record
    # comes to imply that all of its reasoning is checkable.
    basis: Basis = Basis.ASSERTED

    # Which authority reached this verdict, and what it was shown to reach it.
    # Empty for every basis but `EVALUATED`, where they are the whole of what
    # makes the judgement inspectable rather than merely stated.
    authority: str = ""
    evidence: List[str] = Field(default_factory=list)

    @property
    def replayable(self) -> bool:
        """Whether re-running this against the current repository means anything.

        Structural and byte judgements only. An evaluated one *can* be re-run —
        the evidence was recorded — but re-running it may disagree with no code
        having changed, so counting it here would let a bundle report as
        deterministic a share of its reasoning that is not. `rerunnable` is the
        weaker property, kept separate for exactly that reason.
        """
        return self.basis in (Basis.STRUCTURAL, Basis.BYTE)

    @property
    def rerunnable(self) -> bool:
        """Whether the inputs to this judgement were recorded at all.

        True of an evaluated judgement as well as a computed one. What separates
        them is that re-running a computation answers *does this still hold*,
        and re-running an evaluation answers *does it still evaluate the same
        way* — different questions, and a reader must be told which they have.
        """
        return self.basis != Basis.ASSERTED

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

    @property
    def replayable(self) -> float:
        """What share of these judgements re-running could confirm.

        Reported rather than assumed, because the alternative is a record that
        implies all of its reasoning is checkable when some of it was somebody
        reading. One is a claim a reader can verify; the other is one they can
        only take or leave, and telling them which is which is the difference
        between an audit and a summary.
        """
        if not self.witness:
            return 0.0
        return sum(1 for w in self.witness if w.replayable) / len(self.witness)

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

        entry = Witness(
            said=label,
            verdict=outcome.verdict,
            reason=outcome.reason,
            basis=outcome.basis,
            authority=outcome.authority,
            evidence=outcome.evidence,
        )
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
