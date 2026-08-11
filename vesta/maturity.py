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
                would_search=[_query_for(name, intent)],
            )
        )
    if found:
        return found

    # Nothing matched. That is not evidence the brief is ordinary — the table
    # holds eight shapes and the field has more. Live briefs for this project's
    # own components ("derive ontology axioms over existing ontologies",
    # "resolve references across a codebase in any language") matched none of
    # them, and both needed theory that was expensive to acquire late.
    #
    # So an unmatched brief still gets one aspect and still gets searched. The
    # verdict stays UNDETERMINED and the evidence decides, which is the whole
    # point of looking: a table that silently returns "ordinary" for everything
    # it does not recognise would make the search unreachable exactly where it
    # is most needed.
    return [
        Aspect(
            name="the brief",
            says="no familiar shape matched, so it was taken as a whole",
            verdict=UNDETERMINED,
            confidence=UNCLEAR,
            because=["none of the known shapes matched, which settles nothing"],
            would_search=[_query_for("", intent)],
        )
    ]


# Words a brief spends before it says anything. Dropped from queries because a
# search engine ANDs its terms: "build a system that" contributes four words of
# constraint and no topic, and a first live run returned zero repositories for a
# query that returned six once these were removed.
SAYS_NOTHING = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "with", "by",
    "that", "this", "it", "its", "is", "are", "be", "as", "at", "from", "into",
    "build", "building", "create", "creating", "make", "making", "write",
    "writing", "add", "adding", "implement", "implementing", "system", "service",
    "app", "application", "tool", "project", "need", "needs", "want", "should",
    "we", "i", "our", "my", "using", "use", "new",
}

# How many content words a query keeps. Short enough that an ANDed search still
# matches something, long enough to be about one thing.
QUERY_WORDS = 5

# What it takes to call a field still-moving. Several dated results, spanning
# few enough years that the older work which would have settled the question is
# absent rather than merely unreturned. Both numbers are set to make the claim
# hard: this is the one path to NEEDS_THEORY, and the expensive error is
# reaching it wrongly.
MIN_DATED = 4
STILL_MOVING_SPAN = 4  # years


def _query_for(name: str, intent: str) -> str:
    """A query short and specific enough for a search engine to answer.

    The aspect name leads because it is the topic; the brief supplies the
    subject matter. Both are needed — the name alone returns a textbook, the
    brief alone returns the product nobody has built yet.

    **Which words are kept is decided by specificity, not by word order.** A
    brief's opening words are its most general ones. Taking the first five of
    "generate benchmark items from a knowledge base without repeated
    near-duplicate synthesis" gave "generation generate benchmark items
    knowledge base", which returned eight papers on knowledge-graph recommender
    systems — a real literature, and the wrong one, because "knowledge base"
    is common and "near-duplicate" is not. The discriminating words are the
    rare ones, and they tend to arrive late in a sentence.

    **Adjacent words are kept together, because a technical term is a phrase.**
    Ranking words individually pulled "array" out of "covering array" — five
    letters against "guaranteed" at ten — and the surviving query, "covering
    generator guaranteed coverage", returned generator warranties from a
    hardware retailer. Length is a poor proxy for rarity exactly where a short
    word is the domain noun, so a word immediately beside a chosen one is
    carried with it rather than judged on its own.
    """
    words = [
        word
        for word in re.findall(r"[a-z0-9-]+", intent.lower())
        if word not in SAYS_NOTHING and len(word) > 2 and word != name
        # Dropped outright rather than merely ranked last. A brief with few
        # content words fills its budget regardless of order, so "build an
        # efficient reliable robust parser for arbitrary grammars" kept all four
        # qualifiers and searched for none of the subject.
        and _specificity(word) > 0
    ]
    # Rarest first, ties broken by the order they were written in, so the query
    # is stable for a given brief. A hyphenated or long word is a specific one;
    # this is a crude proxy for rarity and needs no corpus to compute.
    ranked = sorted(
        dict.fromkeys(words),
        key=lambda w: (-_specificity(w), words.index(w)),
    )
    keep = QUERY_WORDS if name else QUERY_WORDS + 1

    # Take the strongest words, then pull in whatever sits immediately beside
    # them: "covering" without "array" is a different subject.
    chosen: List[str] = []
    taken: set = set()
    for word in ranked:
        if len(chosen) >= keep:
            break
        for index, spelled in enumerate(words):
            if spelled != word or index in taken:
                continue
            taken.add(index)
            chosen.append(spelled)
            # A neighbour is carried only if it is worth carrying. Taking one
            # unconditionally reintroduced exactly the words the ranking had
            # just rejected: "generator" dragged "guaranteed" back in, scored
            # zero moments earlier for narrowing nothing.
            neighbour = index + 1
            if (
                len(chosen) < keep
                and neighbour < len(words)
                and neighbour not in taken
                and _specificity(words[neighbour]) > 0
            ):
                taken.add(neighbour)
                chosen.append(words[neighbour])
            break
    # Written back in the brief's own order: a query reads as a phrase to a
    # search engine, and scrambling it costs matches on multi-word terms.
    chosen.sort(key=words.index)
    return " ".join([name, *chosen] if name else chosen)


# Long words that narrow nothing. Length stands in for rarity well enough for
# most of a brief, and fails hardest on ordinary English qualifiers: on length
# alone "guaranteed" outranks "array", and a query that spent two slots on it
# returned generator warranties from a hardware retailer. Listing the offenders
# is cruder than a frequency table and needs no corpus to maintain.
NARROWS_NOTHING = {
    "guaranteed", "efficient", "efficiently", "correct", "correctly", "proper",
    "properly", "robust", "reliable", "reliably", "scalable", "performant",
    "simple", "complete", "completely", "arbitrary", "generic", "general",
    "custom", "various", "multiple", "different", "existing", "standard",
    "appropriate", "suitable", "necessary", "possible", "available",
}


def _specificity(word: str) -> int:
    """How much a word narrows a search, approximately.

    Length and hyphenation stand in for rarity. It is a proxy, and a good enough
    one to separate "near-duplicate" from "base" without shipping a frequency
    table that would have to be maintained per language — provided the ordinary
    qualifiers that are long *and* useless are struck out first.
    """
    if word in NARROWS_NOTHING:
        return 0
    return len(word) + (4 if "-" in word else 0)


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

    # A search that ran on some of its sources bounds the judgement just as a
    # missing search does, only less. The caller should not have to know which
    # sources a search holds to know what it did not look at.
    limit = getattr(search, "why_not", "")
    if limit:
        found.could_not_search = limit

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

    # An aspect whose literature is *entirely* recent is one where the answer is
    # still moving: the older work that would have settled it does not exist.
    # This is the only route to NEEDS_THEORY, and it is deliberately hard to
    # reach — it needs several results, dates on nearly all of them, and none of
    # them old. A single recent paper on a decades-old topic proves nothing.
    dated = [_year_of(r) for r in results]
    known = [year for year in dated if year]
    if len(known) >= MIN_DATED and len(known) >= len(dated) - 1:
        if max(known) - min(known) <= STILL_MOVING_SPAN:
            aspect.verdict = NEEDS_THEORY
            aspect.confidence = LIKELY
            aspect.because.append(
                f"all {len(known)} dated result(s) fall in {min(known)}–{max(known)}, "
                "so there may be no settled answer yet — but recency is weak "
                "evidence and an active field is not the same as an open question"
            )


def _year_of(reading: Any) -> Optional[int]:
    published = getattr(reading, "published", "") or ""
    try:
        return int(published[:4])
    except (TypeError, ValueError):
        return None
