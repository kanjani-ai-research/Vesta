"""Asking the user the one question nothing else can answer.

Vesta recovers rules from what a user told agents in their own project. On this
repository that produced 29 candidates, 0 standing, and 21 that nothing can
check — because a passing remark and a standing decision look identical in a
transcript, and no amount of pattern work separates them. "don't use bare
except" is a rule; "don't use bare except here, it swallows the retry" is a
note about one place.

**Only the person who said it knows which it was.** A model can guess, and a
wrong guess is expensive in both directions: a false rule nags forever about
code that is fine, and a missed rule means the same correction gets made again
next week. One keystroke from the user settles it.

**So the question is asked once, and the answer is kept.** A candidate the user
has ruled on is never asked about again — that is the whole value, and asking
twice would spend the goodwill that makes the first question worth answering.
The answer is kept per repository, beside everything else Vesta derives.

**No answer is final.** "Said once about one place" becomes "this holds
everywhere" often enough that treating a note as terminal would lose real
rules. Asked once means not asked *again unprompted*; a user who says so can
change any verdict, and the earlier one is kept rather than overwritten,
because when somebody changed their mind is part of what they decided.

**And what was never said cannot be recovered at all.** Vesta reads
transcripts, so it knows only the constraints a user happened to state to an
agent — everything they never had to correct is invisible. Those gaps are a
void only the user can fill, so a rule can also be declared outright rather
than confirmed.

**Nothing here elicits.** This decides what is worth asking and records what
came back; the asking belongs to whatever surface is in front of the user, and
`sidecar` does it over MCP. Keeping the two apart is what lets the same verdicts
be set from a terminal, a test, or a form.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from .home import kept_at
from .rules import UNDERIVED, Found, Rule, _names_in, derive

logger = logging.getLogger("vesta.confirm")

# What a user can say about a candidate.
IS_A_RULE = "rule"          # binding, and worth checking the code against
NOT_A_RULE = "note"         # said once, about one place; do not raise it again
NO_LONGER = "lapsed"        # was a rule, is not now

# And what they can decline to say.
#
# **Abstention is a signal, not an absence.** Somebody who closes the dialog has
# told us something real: this one is not answerable in a moment, or not now.
# Recording it as "not a rule" would discard a rule they might have kept, and
# recording nothing would ask them the same question tomorrow — the surest way
# to make a useful question into a nuisance.
#
# So it is kept as its own state, and it yields: an abstained candidate is not
# enforced, not dismissed, and stays on a list the user can settle deliberately
# rather than in passing.
ABSTAINED = "abstained"

VERDICTS = (IS_A_RULE, NOT_A_RULE, NO_LONGER, ABSTAINED)

# How many to put in front of someone at once. A list of twenty-nine questions
# is not answered; it is closed.
AT_ONCE = 5


class Verdict(BaseModel):
    """What the user said about one candidate."""

    text: str
    verdict: str = NOT_A_RULE
    # What they meant, where they said it more precisely than the transcript
    # did. A rule stated cleanly is a rule that can be checked.
    stated: str = ""
    at: float = 0.0
    # What this was before, if the user has changed their mind. Kept because
    # when somebody reversed a decision is part of the decision.
    was: str = ""
    # Declared outright rather than recovered from a transcript. A rule Vesta
    # could never have found, because it was never said to an agent.
    declared: bool = False

    @property
    def binding(self) -> bool:
        return self.verdict == IS_A_RULE

    @property
    def settled(self) -> bool:
        """Whether the user has actually decided. Abstention has not."""
        return self.verdict != ABSTAINED

    def describe(self) -> str:
        said = {
            IS_A_RULE: "a rule",
            NOT_A_RULE: "not a rule",
            NO_LONGER: "no longer",
            ABSTAINED: "waiting on you",
        }
        how = said.get(self.verdict, self.verdict)
        if self.was:
            how = f"{how} (was {said.get(self.was, self.was)})"
        if self.declared:
            how = f"{how}, declared"
        return f"{how}: {(self.stated or self.text)[:80]}"


class Asked(BaseModel):
    """Everything this repository's user has ruled on."""

    verdicts: List[Verdict] = Field(default_factory=list)

    def by_text(self) -> Dict[str, Verdict]:
        return {_key(v.text): v for v in self.verdicts}

    @property
    def waiting(self) -> List[Verdict]:
        """Candidates the user has seen and not yet decided.

        Candidates whose own sentence withdraws the claim are dropped, because
        nothing re-runs any test once a verdict is persisted — so tightening
        the extractor would leave every already-captured fragment sitting here
        and the queue would never get cleaner than the day it was worst. "it
        should be conditional, I don't know whether your assertion holds"
        asked a user to confirm something they had already said they could not.

        **Only that.** The first attempt re-ran the whole `constrains` test
        here, which was wrong twice over: it is the gate for scanning raw
        transcripts, deliberately conservative, and candidates reach this
        queue by other paths that were never subject to it. It dropped "one
        .env for v3, not one per service" — a real rule, correctly extracted —
        and it would have dropped every rule a user declared outright, since a
        declared rule has no reason to match a harvesting pattern.

        A candidate the user already settled is untouched either way. Their
        verdict is theirs and a later change of ours does not overrule it.
        """
        from .rules import UNSURE

        return [
            v for v in self.verdicts if not v.settled and not UNSURE.search(v.text)
        ]

    def lately(self, since: float) -> List[Verdict]:
        """What was recorded recently.

        A rule captured while somebody was working on something else is agreed
        to in the moment and forgotten by the afternoon. If one was captured
        wrongly, the cost is only that nobody notices — so what was recorded
        today is worth being able to see today, rather than whenever the rules
        next get audited.
        """
        return sorted(
            (v for v in self.verdicts if v.at >= since),
            key=lambda v: -v.at,
        )

    def describe(self) -> str:
        decided = [v for v in self.verdicts if v.settled]
        if not decided and not self.waiting:
            return "nothing has been confirmed yet"

        binding = sum(1 for v in decided if v.binding)
        said = (
            f"{len(decided)} confirmed: {binding} rule(s), "
            f"{len(decided) - binding} set aside"
        )
        if self.waiting:
            said += f"; {len(self.waiting)} waiting on you"
        return said


def handle(text: str) -> str:
    """A short name for a candidate, so nobody has to paste a sentence.

    `vesta learn --text '<the exact wording>'` is not a thing anybody does
    twice: it means selecting a line out of a terminal, quoting it correctly,
    and getting it byte-identical. A four-character handle derived from the
    text is stable across runs without being stored, and short enough to type.
    """
    import hashlib

    return hashlib.sha256(_key(text).encode("utf-8")).hexdigest()[:4]


def find(repo: Path | str, said: str, found: Optional[Found] = None) -> str:
    """The full text of whatever the user meant, from a handle or a fragment.

    Three ways to name a candidate, in order of how likely each is to be what
    somebody typed: its handle, a distinctive fragment of it, or the whole
    thing. All resolve to the same rule.
    """
    said = said.strip()
    if not said:
        return ""

    known = [v.text for v in recall(repo).verdicts]
    if found is not None:
        known.extend(r.text for r in found.rules)

    for text in known:
        if handle(text) == said.lower():
            return text
    for text in known:
        if said.lower() in text.lower():
            return text
    return said


def _key(text: str) -> str:
    """One candidate's identity, stable across whitespace and case.

    Matched on the text rather than an id: candidates are recovered fresh from
    transcripts each time, so an id assigned during one recovery means nothing
    during the next.
    """
    return " ".join(text.lower().split())[:200]


def _where(repo: Path | str) -> Path:
    return kept_at(repo, "confirmed").with_suffix(".json")


def recall(repo: Path | str) -> Asked:
    """What this repository's user has already ruled on."""
    path = _where(repo)
    if not path.is_file():
        return Asked()
    try:
        return Asked.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Asked()


def keep(asked: Asked, repo: Path | str) -> Path:
    path = _where(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(asked.model_dump_json(), encoding="utf-8")
    return path


def worth_asking(found: Found, repo: Path | str, limit: int = AT_ONCE) -> List[Rule]:
    """Candidates whose answer would change something, most useful first.

    A candidate is worth a question when confirming it would let the code be
    held to something, and when there is reason to think it is a rule at all.

    Those pull the same way, which was not obvious. Ranking uncheckable
    candidates first looks right — most to gain — and is wrong: on this
    repository it surfaced five conversational asides, because a candidate that
    no check recognises *and* that only a loose pattern admitted is usually not
    a rule. A candidate some check does recognise is one the harvester has
    evidence for, and confirming it turns evidence into enforcement.

    Repetition counts for as much as it can, which here is little: a correction
    said twice is a correction that stuck, but in practice almost nothing is
    said twice in the same words. Never asked before comes first regardless —
    asking twice is how a useful question becomes an annoyance.
    """
    # Anything already decided is done with. An abstention is not decided, but
    # it is not asked again in passing either — the user has seen it once and
    # moved on, and `waiting` is where it is settled deliberately.
    seen = recall(repo).by_text()
    candidates = [rule for rule in found.rules if _key(rule.text) not in seen]

    def usefulness(rule: Rule) -> tuple:
        return (
            -(rule.check != UNDERIVED),  # something can check it: real evidence
            -len(rule.said),             # said often: most likely to have stuck
            len(rule.text),              # short: a rule states one thing
        )

    candidates.sort(key=usefulness)
    return candidates[:limit]


def record(
    repo: Path | str,
    text: str,
    verdict: str,
    stated: str = "",
    at: Optional[float] = None,
    declared: bool = False,
) -> Asked:
    """Keep what the user said about one candidate.

    A verdict nobody recognises is kept as "not a rule" rather than refused: the
    answer came from a person, and losing it to a spelling mistake is worse than
    recording the safe reading of it.
    """
    if verdict not in VERDICTS:
        logger.info("unknown verdict %r, keeping as %s", verdict, NOT_A_RULE)
        verdict = NOT_A_RULE

    asked = recall(repo)
    key = _key(text)
    before = asked.by_text().get(key)
    kept = [v for v in asked.verdicts if _key(v.text) != key]
    kept.append(
        Verdict(
            text=text,
            verdict=verdict,
            stated=stated.strip(),
            at=at if at is not None else time.time(),
            # What it was, when this reverses something. Only a real change is
            # recorded: answering the same way twice is not a change of mind.
            was=before.verdict if before and before.verdict != verdict else "",
            declared=declared or bool(before and before.declared),
        )
    )
    asked.verdicts = kept
    keep(asked, repo)
    return asked


def declare(
    repo: Path | str, rule: str, at: Optional[float] = None
) -> Asked:
    """Record a rule the user states outright, that nothing recovered.

    Vesta reads transcripts, so it finds only what somebody happened to say to
    an agent. A constraint they have simply always observed — never argued
    about, never corrected — leaves no trace to recover, and no amount of
    reading finds it. That gap is a void only its author can fill.

    A declared rule is a standing rule from the moment it is said: it was not a
    guess in need of confirmation, so there is nothing to confirm.
    """
    said = rule.strip()
    if not said:
        return recall(repo)
    return record(repo, said, IS_A_RULE, stated=said, at=at, declared=True)


def reopen(repo: Path | str, text: str) -> Asked:
    """Put a candidate back into question.

    Because a verdict is not a life sentence. "Said once, about one place"
    becomes "this holds everywhere" often enough that treating a note as final
    would lose real rules — and a rule that stops applying needs a way back
    that is not deleting the file.
    """
    asked = recall(repo)
    key = _key(text)
    remaining = [v for v in asked.verdicts if _key(v.text) != key]
    if len(remaining) != len(asked.verdicts):
        asked.verdicts = remaining
        keep(asked, repo)
    return asked


def apply(found: Found, repo: Path | str) -> Found:
    """Put the user's verdicts back onto what was recovered.

    Where they said a candidate is a rule, it stands and carries whatever
    cleaner statement they gave. Where they said it is not, it is dropped —
    not marked, dropped: a candidate the user has already dismissed should not
    appear in a count of what they have decided.

    **An abstention yields.** It is neither enforced nor dropped: the user has
    not said it is a rule, so nothing is held to it, and they have not said it
    is not, so it stays to be settled. It leaves the standing set and joins the
    list of what is waiting on them.
    """
    said = recall(repo).by_text()
    if not said:
        return found

    standing: List[Rule] = []
    for rule in found.rules:
        verdict = said.get(_key(rule.text))
        if verdict is None:
            standing.append(rule)
            continue
        if verdict.verdict == ABSTAINED:
            continue  # yields: not enforced, and not dismissed either
        if not verdict.binding:
            continue
        if verdict.stated:
            rule.stated = verdict.stated
        standing.append(rule)

    # Rules the user declared outright. These are in no transcript, so nothing
    # recovered them and nothing above could have kept them — filtering alone
    # would silently discard exactly the constraints only the user could supply.
    have = {_key(r.text) for r in standing}
    for verdict in said.values():
        if not verdict.declared or not verdict.binding:
            continue
        if _key(verdict.text) in have:
            continue
        said = verdict.stated or verdict.text
        kind, how = derive(said)
        standing.append(
            Rule(
                text=verdict.text,
                stated=said,
                check=kind,
                how=how,
                # What the rule is about. Without this a declared rule bears on
                # nothing — it can never be raised when work touches what it
                # governs, which is most of the value of having stated it.
                names=_names_in(said),
                first=verdict.at,
                last=verdict.at,
            )
        )

    found.rules = standing
    found.gaps = [r for r in found.gaps if _key(r.text) in {_key(x.text) for x in standing}]
    return found
