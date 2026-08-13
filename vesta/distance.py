"""How far a repository is from done, measured without asking a model.

An agent working in a loop needs a stopping condition. The obvious one — ask
the model whether it is finished — is the one that cannot work: the model that
wrote the code is the model judging it, and the judge has an interest. The
leading loop plugin states the problem plainly in its own prompt: *"Do not
output false promises to escape the loop, even if you think you're stuck."*
That instruction exists because the failure it names is the normal case.

**A traversable graph and a domain map afford a better answer.** The graph says
what is connected to what; the ontology says what the work is for. Between them
a repository can be asked questions with answers that are facts rather than
opinions — how much of it nothing refers to, how much of it nothing names, how
many rules its own author set that it no longer honours, how much the resolver
could not read at all. None of those is a judgement, and none of them can be
talked out of.

**Distance is a combination, not a number anybody should trust alone.** Each
signal is partial and each has a way of being wrong: a repository with no
ontology scores badly for a reason that has nothing to do with its code, and a
codebase of pure interfaces will always have definitions nothing refers to. So
they are reported separately as well as combined, and the combination is only
ever used the way it can be used honestly — to say whether the last iteration
moved things forward or back.

**What this measures is not correctness.** A repository can be at zero distance
and still do the wrong thing: no defect finder catches a misunderstood
requirement. This measures whether a codebase is *internally coherent and
consistent with what its author said* — which is what an agent can be held to
without a human in the loop, and it is strictly more than "the model said it
was finished".
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.distance")

# What each signal contributes. Deliberately unequal: a rule the user set and
# the code breaks is a fact about their intent being violated, while a
# definition nothing refers to may be a public interface. The weights say which
# evidence is worth more, and they are stated here rather than buried so that
# anybody disagreeing can see exactly what to argue with.
WEIGHTS: Dict[str, float] = {
    "rules_broken": 3.0,      # the author said so and the code disagrees
    "unresolved": 2.0,        # the resolver could not read it: answers are short
    "defects": 1.0,           # found without being asked
    "unnamed": 0.5,           # code no ontology term covers
    "unattached": 0.5,        # named work no code performs
}


class Reading(BaseModel):
    """One measurement of how far a repository is from done."""

    at: float = 0.0

    # Facts about the code, each countable and none of them a judgement.
    definitions: int = 0
    unresolved: int = 0
    defects: int = 0
    rules_standing: int = 0
    rules_broken: int = 0
    named: int = 0
    unattached: int = 0

    # What could not be established. A reading missing a signal is not a
    # reading of zero — it is a reading with a hole, and saying so is the
    # difference between a measurement and a guess.
    missing: List[str] = Field(default_factory=list)

    @property
    def unnamed(self) -> int:
        """Definitions no ontology term covers."""
        return max(0, self.definitions - self.named)

    @property
    def coverage(self) -> float:
        if not self.definitions:
            return 0.0
        return self.named / self.definitions

    @property
    def distance(self) -> float:
        """One number, for comparing a reading with the one before it.

        Normalised by size, so a repository does not look worse for being
        bigger. Never compare this between two different projects — the scale
        is arbitrary and only its movement means anything.
        """
        size = max(self.definitions, 1)
        return (
            WEIGHTS["rules_broken"] * self.rules_broken
            + WEIGHTS["unresolved"] * self.unresolved
            + WEIGHTS["defects"] * self.defects
            + WEIGHTS["unnamed"] * self.unnamed / 10
            + WEIGHTS["unattached"] * self.unattached
        ) / size * 100

    @property
    def settled(self) -> bool:
        """Whether there is nothing left that this can see.

        Deliberately strict about rules and holes and lenient about ontology
        coverage: a rule the author set and the code breaks is unfinished work,
        while a definition nothing has named is unfinished *description*, and
        an agent should not loop forever writing labels.
        """
        # A repository with no code in it is not a finished one. This is the
        # state every project starts in, so a loop that reads it as settled
        # stops before writing a line — and "nothing is wrong" is true of an
        # empty directory in exactly the way that means nothing.
        return (
            self.definitions > 0
            and self.rules_broken == 0
            and self.unresolved == 0
            and self.defects == 0
            and not self.missing
        )

    def describe(self) -> str:
        if self.missing:
            gaps = ", ".join(self.missing)
            return f"cannot say — {gaps}"
        if not self.definitions:
            return "nothing built yet"
        if self.settled:
            return f"settled — {self.definitions} definitions, nothing outstanding"
        parts = []
        if self.rules_broken:
            parts.append(f"{self.rules_broken} rule(s) broken")
        if self.unresolved:
            parts.append(f"{self.unresolved} file(s) unreadable")
        if self.defects:
            parts.append(f"{self.defects} defect(s)")
        if self.unnamed:
            parts.append(f"{self.unnamed} definition(s) unnamed")
        return f"{self.distance:.1f} from done — " + ", ".join(parts)


class Movement(BaseModel):
    """What changed between two readings, and whether it was progress."""

    before: Reading
    after: Reading

    @property
    def closer(self) -> bool:
        return self.after.distance < self.before.distance

    @property
    def moved(self) -> float:
        return self.before.distance - self.after.distance

    @property
    def stalled(self) -> bool:
        """Nothing measurable changed.

        The signal a loop needs most. An agent that iterates without moving is
        an agent that will iterate forever, and every stopping condition based
        on the model's own opinion is blind to it.
        """
        return abs(self.moved) < 0.01

    def describe(self) -> str:
        if self.stalled:
            return "no measurable change"
        way = "closer" if self.closer else "further"
        return f"{abs(self.moved):.1f} {way} — {self.after.describe()}"

    def what_changed(self) -> List[str]:
        """Each signal that moved, so a report can say what actually happened."""
        said = []
        for name, before, after in (
            ("rules broken", self.before.rules_broken, self.after.rules_broken),
            ("unreadable files", self.before.unresolved, self.after.unresolved),
            ("defects", self.before.defects, self.after.defects),
            ("unnamed definitions", self.before.unnamed, self.after.unnamed),
        ):
            if before != after:
                way = "↓" if after < before else "↑"
                said.append(f"{name} {before} {way} {after}")
        return said


def _afresh(root: Path) -> None:
    """Drop everything remembered about this repository.

    Every cache here exists because something is read on a path that runs
    before a prompt, and paying for it twice a second is worse than being
    briefly out of date. A loop measuring its own progress is the one caller
    for which that trade is wrong: it reads, changes the code, and reads again
    within the same process, and a remembered answer makes the change invisible.

    Found by measuring: a function was deleted and the reading did not move,
    because the graph, the file listing and the file contents were all still
    the ones from before the edit.
    """
    from .held import forget

    forget(root)

    from . import patterns

    patterns._LISTED.clear()
    patterns._READ.clear()


def measure(repo: Path | str, at: Optional[float] = None) -> Reading:
    """Take one reading. Every signal is counted; none is judged.

    A signal that cannot be established is recorded as missing rather than as
    zero, because a repository nobody could read is not a repository with no
    defects.
    """
    import warnings

    root = Path(repo).expanduser().resolve()

    # A directory that is not there reads as a repository with nothing wrong
    # with it, and a loop measuring one would declare victory on its first
    # iteration. An empty reading and an unreadable one must never look alike.
    if not root.is_dir():
        reading = Reading(at=at if at is not None else time.time())
        reading.missing.append(f"{root} is not a directory")
        return reading

    _afresh(root)
    reading = Reading(at=at if at is not None else time.time())

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        try:
            from .held import graph_for

            # Never trusted. `trust_for` returns any graph written recently
            # without checking whether the tree changed, which is right for a
            # hook answering a prompt and exactly wrong here: this is called
            # before and after an edit, and a remembered graph makes the edit
            # invisible. A measurement that cannot see change measures nothing.
            graph = graph_for(root, rebuild=True)
            reading.definitions = len(graph.nodes)
            reading.unresolved = len(graph.holes)
        except Exception as exc:  # noqa: BLE001 - a hole is not a zero
            logger.info("no graph for %s: %s", root, exc)
            reading.missing.append("the graph could not be built")
            return reading

        try:
            from .patterns import survey

            found = survey(graph, root)
            reading.defects = sum(len(f.sites) for f in found.found)
        except Exception as exc:  # noqa: BLE001
            logger.info("no defect survey: %s", exc)
            reading.missing.append("defects could not be surveyed")

        try:
            from .traverse import recall as recall_map

            mapped = recall_map(root)
            if mapped is not None:
                reading.named = len({a.node for a in mapped.attachments})
                reading.unattached = len(mapped.unattached)
        except Exception as exc:  # noqa: BLE001
            logger.info("no ontology: %s", exc)

        try:
            from . import confirm
            from .enforce import against
            from .rules import from_sessions, recall_rules

            rules = confirm.apply(recall_rules(root) or from_sessions(root), root)
            reading.rules_standing = len(rules.standing)
            if rules.standing:
                verdict = against(rules, graph, root)
                reading.rules_broken = len(verdict.broken)
        except Exception as exc:  # noqa: BLE001
            logger.info("rules could not be checked: %s", exc)
            reading.missing.append("rules could not be checked")

    return reading


def between(before: Reading, after: Reading) -> Movement:
    """What one iteration achieved."""
    return Movement(before=before, after=after)
