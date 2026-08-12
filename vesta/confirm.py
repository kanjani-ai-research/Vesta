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
from .rules import UNDERIVED, Found, Rule

logger = logging.getLogger("vesta.confirm")

# What a user can say about a candidate.
IS_A_RULE = "rule"          # binding, and worth checking the code against
NOT_A_RULE = "note"         # said once, about one place; do not raise it again
NO_LONGER = "lapsed"        # was a rule, is not now

VERDICTS = (IS_A_RULE, NOT_A_RULE, NO_LONGER)

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

    @property
    def binding(self) -> bool:
        return self.verdict == IS_A_RULE

    def describe(self) -> str:
        said = {IS_A_RULE: "a rule", NOT_A_RULE: "not a rule", NO_LONGER: "no longer"}
        return f"{said.get(self.verdict, self.verdict)}: {(self.stated or self.text)[:80]}"


class Asked(BaseModel):
    """Everything this repository's user has ruled on."""

    verdicts: List[Verdict] = Field(default_factory=list)

    def by_text(self) -> Dict[str, Verdict]:
        return {_key(v.text): v for v in self.verdicts}

    def describe(self) -> str:
        if not self.verdicts:
            return "nothing has been confirmed yet"
        binding = sum(1 for v in self.verdicts if v.binding)
        return (
            f"{len(self.verdicts)} confirmed: {binding} rule(s), "
            f"{len(self.verdicts) - binding} set aside"
        )


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
    already = recall(repo).by_text()
    candidates = [
        rule for rule in found.rules if _key(rule.text) not in already
    ]

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
    kept = [v for v in asked.verdicts if _key(v.text) != key]
    kept.append(
        Verdict(
            text=text,
            verdict=verdict,
            stated=stated.strip(),
            at=at if at is not None else time.time(),
        )
    )
    asked.verdicts = kept
    keep(asked, repo)
    return asked


def apply(found: Found, repo: Path | str) -> Found:
    """Put the user's verdicts back onto what was recovered.

    Where they said a candidate is a rule, it stands and carries whatever
    cleaner statement they gave. Where they said it is not, it is dropped —
    not marked, dropped: a candidate the user has already dismissed should not
    appear in a count of what they have decided.
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
        if not verdict.binding:
            continue
        if verdict.stated:
            rule.stated = verdict.stated
        standing.append(rule)

    found.rules = standing
    found.gaps = [r for r in found.gaps if _key(r.text) in {_key(x.text) for x in standing}]
    return found
