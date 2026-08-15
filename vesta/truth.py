"""Ground truth, from history that already happened.

The claim this project makes is measurable: given a change, name what breaks.
A claim like that is worth nothing asserted and everything measured, so the
measurement comes first — before the graph it grades, so that the graph is built
against a score rather than scored after the fact.

**The ground truth is the repository's own commits.** A commit that changes
source and tests together is an experiment somebody already ran: the source
change is the input, and the tests touched in the same commit are what the
author believed it affected. That belief is imperfect — authors miss things,
and a test changed for unrelated reasons is noise — but it is *independent* of
whatever this system predicts, which is the property that matters.

**Two baselines, both honest.** A prediction is only interesting against what a
competent engineer already has. The first baseline is every test in the
repository — trivially complete recall, useless precision, and the thing a
developer does when they have no better information. The second is
find-references: the transitive callers of a changed function, which is what an
IDE or language server supplies today. Beating the first is easy. Beating the
second is the actual bar.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field


class Change(BaseModel):
    """One commit, as an experiment that already ran."""

    commit: str
    subject: str = ""
    # Which repository this came from. Carried because a corpus spans several,
    # and a baseline that answers "every test" needs to know every test in
    # *which* repository — a first attempt returned one repo's tests for every
    # commit and scored a recall of 0.33 on a baseline that is complete by
    # construction.
    repo: str = ""
    # What the author changed, outside tests. The input to a prediction.
    changed: List[str] = Field(default_factory=list)
    # Which test files moved in the same commit. What the author believed the
    # change affected — the closest thing to a label this data has.
    touched_tests: List[str] = Field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """Whether this commit can grade anything.

        A commit with no source change has no input; one with no test change
        has no label. Both are common — a docs commit, a test-only refactor —
        and neither is evidence of anything.
        """
        return bool(self.changed and self.touched_tests)

    def describe(self) -> str:
        return (
            f"{self.commit[:8]} {self.subject[:48]}: "
            f"{len(self.changed)} source, {len(self.touched_tests)} test file(s)"
        )


class Score(BaseModel):
    """How well a prediction matched what actually moved."""

    predicted: Set[str] = Field(default_factory=set)
    actual: Set[str] = Field(default_factory=set)

    @property
    def hit(self) -> Set[str]:
        return self.predicted & self.actual

    @property
    def missed(self) -> Set[str]:
        """What moved and was not predicted. The dangerous direction."""
        return self.actual - self.predicted

    @property
    def spurious(self) -> Set[str]:
        return self.predicted - self.actual

    @property
    def precision(self) -> float:
        return len(self.hit) / len(self.predicted) if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return len(self.hit) / len(self.actual) if self.actual else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def describe(self) -> str:
        return (
            f"precision {self.precision:.2f}, recall {self.recall:.2f}, "
            f"f1 {self.f1:.2f} "
            f"({len(self.hit)} hit, {len(self.missed)} missed, "
            f"{len(self.spurious)} spurious)"
        )


class Result(BaseModel):
    """One approach, over one corpus of commits."""

    name: str
    scores: List[Score] = Field(default_factory=list)

    @property
    def commits(self) -> int:
        return len(self.scores)

    @property
    def precision(self) -> float:
        """Averaged per commit, not pooled.

        Pooling would let one commit that changed forty files dominate the
        number, and the question is how well the approach does on a change,
        not on a corpus.
        """
        return _mean(s.precision for s in self.scores)

    @property
    def recall(self) -> float:
        return _mean(s.recall for s in self.scores)

    @property
    def f1(self) -> float:
        return _mean(s.f1 for s in self.scores)

    @property
    def never_missed(self) -> float:
        """Share of commits where nothing that moved went unpredicted.

        The number that matters most for a correctness claim. An approach with
        good average recall that misses something on a third of changes is not
        one anybody should rely on to say "safe to change".
        """
        if not self.scores:
            return 0.0
        return sum(1 for s in self.scores if not s.missed) / len(self.scores)

    def describe(self) -> str:
        return (
            f"{self.name:<24} p={self.precision:.2f} r={self.recall:.2f} "
            f"f1={self.f1:.2f} complete={self.never_missed:.0%} "
            f"over {self.commits} commit(s)"
        )


# ── Reading history ──────────────────────────────────────────────────────


def usable(changes: Sequence[Change]) -> List[Change]:
    return [c for c in changes if c.is_usable]


def _commits(repo: Path | str, limit: int) -> List[Tuple[str, str]]:
    out = _git(repo, "log", f"-{limit}", "--format=%H%x00%s")
    found = []
    for line in out.splitlines():
        if "\x00" in line:
            commit, subject = line.split("\x00", 1)
            found.append((commit, subject))
    return found


def _files_in(repo: Path | str, commit: str) -> List[str]:
    out = _git(repo, "show", "--name-only", "--format=", commit)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _git(repo: Path | str, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return ""


# ── Baselines ────────────────────────────────────────────────────────────


def same_file(changed: Sequence[str]) -> Set[str]:
    """The test file named after each changed module.

    A convention-following baseline, and a surprisingly strong one in a repo
    where `vesta/truth.py` is tested by `tests/test_truth.py`. Worth measuring
    precisely because it is what a careful developer would guess, and a graph
    that cannot beat a naming convention has not earned its complexity.
    """
    found: Set[str] = set()
    for path in changed:
        stem = Path(path).stem
        if stem in ("__init__", "__main__"):
            continue
        found.add(f"tests/test_{stem}.py")
    return found


def grade(predicted: Set[str], change: Change) -> Score:
    return Score(predicted=set(predicted), actual=set(change.touched_tests))


def compare(
    changes: Sequence[Change], approaches: Dict[str, object]
) -> List[Result]:
    """Every approach over every usable commit.

    `approaches` maps a name to a callable taking a Change and returning the
    set of test files it predicts. Baselines and the graph are graded by the
    identical path, so a comparison cannot be flattered by measuring them
    differently.
    """
    results = [Result(name=name) for name in approaches]
    for change in usable(changes):
        for result, predict in zip(results, approaches.values()):
            result.scores.append(grade(predict(change), change))  # type: ignore[operator]
    return results


def _mean(values) -> float:
    collected = list(values)
    return sum(collected) / len(collected) if collected else 0.0
