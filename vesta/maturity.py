"""Whether a thing to be built is settled work or needs theory.

The gate on everything else. A build that is ordinary needs no literature, and
going to look for some wastes a user's money and attention. A build with a
genuinely hard part needs the theory *before* the code, because the cost of
learning it afterwards is a rewrite.

**The errors are asymmetric and the dangerous one is not the obvious one.**
Calling something novel when it is mature costs a lookup. Calling something
*mature* when it is novel costs a rewrite — but worse than either, a system that
declares novelty too readily starts proposing that established patterns be
abandoned. "Restricted by existing design patterns, else redesign the entire
system" is a sentence that reads as insight and destroys an architecture. So
this defaults to settled, requires evidence to say otherwise, and its output is
never a directive.

**A named technology is often exactly what makes something ordinary.** "Build a
REST API with FastAPI" is settled precisely because the API is named; the naming
is evidence *for* maturity, not against it. A classifier that treated technical
specificity as difficulty would flag every competent brief.

**What it produces is a question, not an instruction.** The finding is "this
aspect may need theory, here is why, do you agree" — put to a user who usually
knows more about their own build than any classifier does. A wrong answer that
is visible costs a moment; a wrong answer that acts costs a system.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.maturity")

# What a judgement can be. Three values rather than two, because "I could not
# establish this" is a real answer and collapsing it into either of the others
# is how a classifier comes to state things it does not know.
SETTLED = "settled"          # a known solution exists and is the right one
NEEDS_THEORY = "needs_theory"  # the hard part has no off-the-shelf answer
UNDETERMINED = "undetermined"  # not enough evidence either way
VERDICTS = (SETTLED, NEEDS_THEORY, UNDETERMINED)

# How sure the evidence makes it. Reported alongside the verdict rather than
# folded into it: a settled verdict held weakly and one held strongly are
# different situations for a user deciding whether to look further.
CLEAR = "clear"
LIKELY = "likely"
UNCLEAR = "unclear"

# Signals that a brief describes ordinary work. Presence is evidence *for*
# settledness — naming a framework is what a competent brief does, and treating
# specificity as difficulty would flag every good one.
NAMES_A_TOOL = re.compile(
    r"\b(fastapi|django|flask|rails|express|react|vue|svelte|postgres|mysql|"
    r"sqlite|redis|mongo|kafka|rabbitmq|docker|kubernetes|terraform|s3|"
    r"stripe|oauth|jwt|rest|graphql|grpc|crud)\b",
    re.I,
)

# Shapes that recur in work with a hard part. Not a novelty detector — every
# one of these has mature solutions — but a marker that the *choice among*
# solutions has consequences a brief may not have considered.
HAS_A_HARD_SHAPE = {
    "concurrency": r"\b(concurren|parallel|race|lock|atomic|thread|async)\w*\b",
    "consistency": r"\b(consisten|consensus|replica|distribut|partition|quorum)\w*\b",
    "search": r"\b(rank|relevan|retriev|index|similarity|embedding|nearest)\w*\b",
    "scheduling": r"\b(schedul|queue|priorit|throttl|backpressure|rate.?limit)\w*\b",
    "generation": r"\b(generat|synthes|sampl|diversit|augment)\w*\b",
    "verification": r"\b(verif|prove|invariant|sound|complete|refut)\w*\b",
    "optimisation": r"\b(optimi[sz]|minimi[sz]|maximi[sz]|constraint|solver)\b",
    "inference": r"\b(infer|predict|classif|cluster|train|fine.?tun)\w*\b",
}


class Aspect(BaseModel):
    """One part of a build, judged on its own.

    A brief is rarely uniformly hard. "A web service that deduplicates
    submissions by semantic similarity" is a settled web service and a
    non-trivial similarity problem, and judging the whole would lose that.
    """

    name: str
    says: str = Field(description="What about the build this covers")
    verdict: str = SETTLED
    confidence: str = UNCLEAR
    # Why. Shown to the user rather than kept, because a judgement a user
    # cannot check is one they have to take on faith.
    because: List[str] = Field(default_factory=list)
    # What would be looked up, if the user agrees it is worth looking. Named
    # here so the search is inspectable before it is paid for.
    would_search: List[str] = Field(default_factory=list)

    @property
    def wants_theory(self) -> bool:
        return self.verdict == NEEDS_THEORY

    def describe(self) -> str:
        mark = {
            SETTLED: "settled",
            NEEDS_THEORY: "may need theory",
            UNDETERMINED: "undetermined",
        }[self.verdict]
        return f"{self.name}: {mark} ({self.confidence})"


class Judgement(BaseModel):
    """What a brief needs, as a question put to the user."""

    intent: str
    aspects: List[Aspect] = Field(default_factory=list)
    # Set where no search could run. A judgement made without the ability to
    # check the literature is weaker than one made with it, and saying so is
    # the difference between a limit and a silent failure.
    could_not_search: str = ""

    @property
    def needs_theory(self) -> List[Aspect]:
        return [a for a in self.aspects if a.wants_theory]

    @property
    def is_ordinary(self) -> bool:
        return not self.needs_theory

    def ask(self) -> str:
        """The question to put to a user. Never an instruction.

        Phrased so agreement is a decision and disagreement is cheap. A user
        who says "no, that is standard" has cost themselves a sentence; a
        system that had instead acted on its own judgement would have cost them
        an architecture.
        """
        if self.is_ordinary:
            said = (
                "This looks like established work. Nothing here obviously needs "
                "theory beyond what is already known — say if you disagree."
            )
            # A settled verdict reached without checking anything is weaker
            # than one reached by looking, and the user is the one who should
            # decide whether that matters. Reporting the limit only when theory
            # *was* found would hide it in exactly the case where the user has
            # least reason to suspect it.
            return f"{said}\n({self.could_not_search})" if self.could_not_search else said
        lines = ["Some of this may need more than established practice:"]
        for aspect in self.needs_theory:
            lines.append(f"  • {aspect.name} — {aspect.says}")
            for reason in aspect.because[:2]:
                lines.append(f"      {reason}")
        lines.append("")
        lines.append(
            "Does that match how you see it? If any of these is settled work "
            "in your view, say so and it will not be looked into."
        )
        if self.could_not_search:
            lines.append(f"({self.could_not_search})")
        return "\n".join(lines)

    def describe(self) -> str:
        if self.is_ordinary:
            return f"{len(self.aspects)} aspect(s), all settled"
        return (
            f"{len(self.needs_theory)} of {len(self.aspects)} aspect(s) "
            "may need theory"
        )


# ── Judging ──────────────────────────────────────────────────────────────


def read(intent: str) -> List[Aspect]:
    """Aspects visible in a brief without asking anything of anyone.

    Cheap, deterministic, and deliberately reluctant. This proposes *candidates*
    for a closer look; nothing here concludes that anything is novel, because
    matching a word is not evidence about a problem.
    """
    found: List[Aspect] = []
    text = intent.lower()

    named = NAMES_A_TOOL.findall(text)
    for name, pattern in sorted(HAS_A_HARD_SHAPE.items()):
        hits = re.findall(pattern, text, re.I)
        if not hits:
            continue
        because = [f"the brief mentions {', '.join(sorted(set(h.lower() for h in hits))[:3])}"]
        if named:
            # Naming a technology is evidence *for* settledness. A brief that
            # says "rate-limit with Redis" has already chosen, and the choice
            # is the ordinary one.
            because.append(
                f"but it also names {', '.join(sorted(set(n.lower() for n in named))[:3])}, "
                "which usually means the approach is already chosen"
            )
        found.append(
            Aspect(
                name=name,
                says=f"the brief touches {name}",
                verdict=UNDETERMINED,
                confidence=UNCLEAR,
                because=because,
                would_search=[f"{name} {' '.join(intent.split()[:6])}"],
            )
        )
    return found


def judge(
    intent: str,
    aspects: Optional[Sequence[Aspect]] = None,
    ask_model: Optional[Callable] = None,
    search: Optional[Callable] = None,
) -> Judgement:
    """Whether a brief needs theory, and for which parts.

    `ask_model` and `search` are both optional and the judgement degrades
    honestly without either: with neither, everything reads as settled and the
    result says why it could not establish more. That is the right default —
    a deployment with no search configured should not be guessing at novelty.
    """
    found = Judgement(intent=intent, aspects=list(aspects or read(intent)))

    if search is None:
        found.could_not_search = (
            "No search is configured, so nothing was checked against the "
            "literature. Every aspect is treated as settled."
        )
        for aspect in found.aspects:
            aspect.verdict = SETTLED
            aspect.confidence = UNCLEAR
            aspect.because.append("not checked — no search configured")
        return found

    for aspect in found.aspects:
        _establish(aspect, search)

    return found


def _establish(aspect: Aspect, search: Callable) -> None:
    """Look, and let what comes back decide.

    A search returning established, well-cited material about an aspect is
    evidence the aspect is settled — the opposite of what a naive reading might
    suggest. Novelty is claimed only where the search finds the question open:
    competing approaches, recent work, or nothing at all.
    """
    try:
        results = search(aspect.would_search[0]) if aspect.would_search else []
    except Exception as exc:  # noqa: BLE001 - a failed search is not a verdict
        aspect.verdict = UNDETERMINED
        aspect.confidence = UNCLEAR
        aspect.because.append(f"the search failed: {exc}")
        return

    if not results:
        # Nothing found is not evidence of novelty. It is evidence the query
        # was wrong, or the field is not indexed, and treating silence as
        # discovery is how a classifier comes to invent hard problems.
        aspect.verdict = UNDETERMINED
        aspect.confidence = UNCLEAR
        aspect.because.append("the search returned nothing, which settles neither way")
        return

    aspect.because.append(f"{len(results)} result(s) found")
    aspect.verdict = SETTLED
    aspect.confidence = LIKELY
