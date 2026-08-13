"""What to do when somebody asks for something mid-build.

Three answers, and which one applies is decided by where the request lands
against the contract rather than by how reasonable it sounds.

**It changes agreed behaviour → refused.** Not weighed, not scored. The
behaviours were agreed before any code existed and they do not move: a contract
that follows the user's mind is not a contract, and a loop chasing one never
terminates. They can continue to completion, start over, or have the change
after delivery. That is their choice and Vesta does not make it for them.

**It names no behaviour at all → "sure".** A request that cannot be written as
*someone can do something* has nothing to build against. Whether it is absurd is
not the test and is none of Vesta's business — "add a convolutional neural
network to my todo list" may be perfectly sensible. What decides is only whether
it says what it does and who for. Noted, and nothing else said about it.

**Anything else → judged on spread.** Tool choices, structure, an inferred
detail somebody wants different. None of these touch what the system does, so
none of them touch the contract. What decides is blast radius: the same change
is trivial behind one adapter and a different project when the substrate leaked
into forty call sites. `touches` counts that, so it is a measurement rather than
an intuition.

**What this cannot know is how hard a refactor is.** Forty mechanical call-site
edits and four subtle semantic ones count the same. So the numbers are reported
rather than reduced to a verdict nobody can argue with — spread, depth, and what
they reach — and the threshold is stated in the open where somebody can disagree
with it.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from .contract import Contract
from .contract import recall as recall_contract

logger = logging.getLogger("vesta.asked")

# How far a change can reach before it stops being something to absorb without
# comment. Stated here rather than buried: a threshold nobody can find is one
# nobody can argue with.
#
# Twelve definitions is about a module. Beyond that a change is no longer
# something done in passing while building something else, whatever it is.
ABSORB_UNDER = 12

# What to do about it.
REFUSED = "refused"        # changes what was agreed; a different project
ABSORB = "absorb"          # small, and touches no behaviour
AFTER = "after"            # real, but too big to take on mid-build
SURE = "sure"              # names no behaviour; nothing to do


class Landing(BaseModel):
    """Where a request lands against the contract, and what follows."""

    said: str
    verdict: str = SURE

    # What it would reach, when it reaches anything. Reported rather than
    # reduced: a count of definitions is a fact, and how hard they are to
    # change is not.
    reaches: int = 0
    behaviours: List[str] = Field(default_factory=list)

    def describe(self) -> str:
        if self.verdict == REFUSED:
            names = ", ".join(f'"{b}"' for b in self.behaviours[:2])
            return (
                f"That changes what was agreed — it alters {names}. "
                "This is a different project now."
            )
        if self.verdict == SURE:
            return "Sure."
        if self.verdict == ABSORB:
            return f"Doing that; it reaches {self.reaches} definition(s)."
        return (
            f"That reaches {self.reaches} definition(s) and would undo work "
            "already done. Better after delivery than in the middle."
        )

    def what_to_say(self) -> str:
        """What to put to the user, including what they can do about it."""
        said = self.describe()
        if self.verdict == REFUSED:
            return (
                f"{said}\n\n"
                "You can carry on to completion as agreed, start over with the "
                "new behaviour in the contract, or have this after delivery. "
                "Which?"
            )
        if self.verdict == AFTER:
            return f"{said}\n\nKeeping it for after delivery unless you say otherwise."
        return said


def _names(said: str) -> set:
    """The words in a request that could name something in the code."""
    return {
        word.lower()
        for word in re.findall(r"[A-Za-z_][\w.]{2,}", said)
    }


def _stem(word: str) -> str:
    """Enough of a word to match its plural. Not linguistics — a suffix."""
    low = word.lower()
    for ending in ("ies", "es", "s"):
        if len(low) > 4 and low.endswith(ending):
            return low[: -len(ending)]
    return low


def _touches_a_behaviour(said: str, agreed: Contract) -> List[str]:
    """Behaviours a request may alter.

    **This is deliberately over-eager, and it is not the decision.** Whether a
    request changes what the system does is a judgement about meaning: "tasks
    should be shared between users" alters "a user can file a task" without
    repeating a word of it, and no amount of matching finds that reliably. The
    agent reading the request makes that call, on the host's inference, the
    same as every other judgement here.

    What this does is flag anything that might, because the two mistakes are
    not symmetric. A false match costs a question the user answers in a
    sentence. A miss means building a change that invalidates work already
    agreed and done, and nobody finds out until the contract no longer
    describes the product.
    """
    wanted = {_stem(word) for word in _names(said)}
    if not wanted:
        return []

    found = []
    for behaviour in agreed.behaviours:
        words = {
            _stem(word)
            for word in re.findall(r"[A-Za-z_][\w]{3,}", behaviour.does)
            if word.lower() not in _EVERYWHERE
        }
        if words and wanted & words:
            found.append(behaviour.does)
    return found


# Words that appear in almost any behaviour and so distinguish nothing.
_EVERYWHERE = {
    "user", "users", "system", "they", "them", "this", "that", "with", "from",
    "when", "then", "their", "there", "which", "what", "have", "into", "have",
    "does", "doing", "make", "made", "will", "must", "should", "each", "some",
    "able", "want", "wants", "thing", "things",
}

# What marks a request as being about what the system does, rather than how it
# is built. These are refused whether or not they name a behaviour in the same
# words, because a behavioural change that slipped through is the expensive
# mistake and a question is the cheap one.
ABOUT_BEHAVIOUR = re.compile(
    r"\b(shared|share|private|public|multi[- ]?user|per[- ]?user|"
    r"instead of (?:a |the )?(?:user|person|customer)|"
    r"also (?:be able to|let|allow)|should (?:also |now )?(?:be able|allow|let)|"
    r"anyone can|nobody can|only .{0,20}can|no longer|stop being able)\b",
    re.I,
)

# What marks a request as being about how something is built rather than what
# it does. These are the changes that can be absorbed or deferred; a request
# with none of them and no behaviour match names nothing to act on.
STRUCTURAL = re.compile(
    r"\b(use|using|switch|replace|move|rename|refactor|split|merge|extract|"
    r"instead of|rather than|library|framework|database|db|store|storage|"
    r"file|module|package|class|function|format|style|layout|structure)\b",
    re.I,
)


def where_it_lands(
    said: str,
    repo: Path | str,
    reaches: Optional[int] = None,
) -> Landing:
    """What to do about something the user asked for mid-build.

    `reaches` is how many definitions the change would touch, which the caller
    counts with `touches` — it is not recomputed here, because two answers that
    can disagree is worse than one.
    """
    landing = Landing(said=said.strip(), reaches=reaches or 0)
    if not landing.said:
        return landing

    agreed = recall_contract(repo)
    if agreed is None or not agreed.signed:
        # Nothing has been agreed, so nothing can be departed from. Anything
        # goes, which is the right answer before a contract exists.
        landing.verdict = ABSORB
        return landing

    # A request that plainly asks about *what the system does* is refused
    # whether or not it names a behaviour in the same words: "tasks should be
    # shared rather than private" alters "a user can file a task" without
    # repeating any of it.
    if ABOUT_BEHAVIOUR.search(landing.said):
        landing.verdict = REFUSED
        landing.behaviours = _touches_a_behaviour(landing.said, agreed) or [
            b.does for b in agreed.behaviours[:2]
        ]
        return landing

    # A request that plainly asks about *how it is built* is structural, even
    # though it names the same nouns the behaviours do. Every refactor in a
    # todo app mentions tasks, and refusing on that basis would refuse all of
    # them — which is not a strict contract, it is a broken tool.
    structural = bool(STRUCTURAL.search(landing.said))

    altered = _touches_a_behaviour(landing.said, agreed)
    if altered and not structural:
        landing.verdict = REFUSED
        landing.behaviours = altered
        return landing

    if not structural:
        # Names no behaviour and asks for nothing structural. That is *not*
        # the same as naming nothing at all: "add a test for filing" is
        # ordinary work, and answering it with "sure" would be a tool refusing
        # to do its job politely. Only a request that also reaches nothing in
        # the code is inert.
        landing.verdict = SURE if not landing.reaches else ABSORB
        return landing

    landing.verdict = ABSORB if landing.reaches < ABSORB_UNDER else AFTER
    return landing


def act(said: str, repo: Path | str, reaches: Optional[int] = None) -> Landing:
    """Decide, and record whatever the decision implies."""
    from .contract import defer, note

    landing = where_it_lands(said, repo, reaches=reaches)

    if landing.verdict == REFUSED:
        defer(repo, landing.said)
    elif landing.verdict == AFTER:
        defer(repo, landing.said)
    elif landing.verdict == SURE:
        note(repo, landing.said)

    return landing
